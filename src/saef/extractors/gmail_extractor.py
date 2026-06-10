from __future__ import annotations

import base64
import re
from datetime import date
from pathlib import Path
from typing import Any

from saef.config import Settings
from saef.core.comparator import validar_factura
from saef.extractors.base import Extractor
from saef.models import FacturaExtraida, Proveedor


SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


# Configuracion OAuth para Gmail:
# 1. Entra a Google Cloud Console con la cuenta propietaria del proyecto.
# 2. Crea un proyecto o usa uno existente.
# 3. Habilita la API "Gmail API" para ese proyecto.
# 4. Configura la pantalla de consentimiento OAuth.
# 5. Crea credenciales tipo "OAuth client ID" con aplicacion "Desktop app".
# 6. Descarga el JSON del cliente OAuth.
# 7. Guarda ese JSON como credentials/gmail_oauth_client.json.
# 8. No subas ese archivo ni credentials/gmail_token.json al repositorio.
# 9. La primera ejecucion abre el navegador para autorizar lectura de Gmail.
# 10. El token queda en credentials/gmail_token.json para ejecuciones futuras.
# 11. En servidor, genera el token localmente y copialo de forma segura.
# 12. Si cambias los permisos SCOPES, borra el token y autoriza de nuevo.


class GmailExtractor(Extractor):
    name = "gmail"

    def __init__(self, proveedor: Proveedor, settings: Settings) -> None:
        super().__init__(proveedor)
        self.settings = settings

    def extraer(self, periodo: str) -> list[FacturaExtraida]:
        start, end = month_bounds(periodo)
        service = self._gmail_service()
        message_ids = self._search_messages(service, start, end)
        invoices: list[FacturaExtraida] = []

        for message_id in message_ids:
            message = (
                service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
            for part in pdf_attachment_parts(message.get("payload", {})):
                filename = safe_filename(part["filename"] or f"{message_id}.pdf")
                content = self._attachment_bytes(service, message_id, part)
                target = self._target_path(periodo, message_id, filename)
                target.write_bytes(content)
                invoices.append(self._invoice_from_pdf(target, periodo))

        return invoices

    def _gmail_service(self) -> Any:
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError(
                "Instala las dependencias de Gmail con: pip install -r requirements.txt"
            ) from exc

        credentials_path = self.settings.gmail_credentials_path
        token_path = self.settings.gmail_token_path
        credentials = None

        if token_path.exists():
            credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())

        if not credentials or not credentials.valid:
            if not credentials_path.exists():
                raise RuntimeError(
                    f"No existe {credentials_path}. Revisa los pasos OAuth en "
                    "src/saef/extractors/gmail_extractor.py."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
            credentials = flow.run_local_server(port=0)

        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(credentials.to_json(), encoding="utf-8")
        return build("gmail", "v1", credentials=credentials)

    def _search_messages(self, service: Any, start: date, end: date) -> list[str]:
        query = build_gmail_query(
            start=start,
            end=end,
            sender=self.proveedor.remitente,
            subject=self.proveedor.asunto,
        )
        message_ids: list[str] = []
        page_token = None

        while True:
            params = {"userId": "me", "q": query}
            if page_token:
                params["pageToken"] = page_token
            request = service.users().messages().list(**params)
            response = request.execute()
            message_ids.extend(message["id"] for message in response.get("messages", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                return message_ids

    def _attachment_bytes(self, service: Any, message_id: str, part: dict[str, Any]) -> bytes:
        if part.get("data"):
            return decode_gmail_data(part["data"])

        attachment_id = part["attachment_id"]
        attachment = (
            service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute()
        )
        return decode_gmail_data(attachment["data"])

    def _target_path(self, periodo: str, message_id: str, filename: str) -> Path:
        provider_dir = slugify(self.proveedor.nombre)
        target_dir = self.settings.storage_dir / periodo / provider_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        target = target_dir / filename
        if target.exists():
            target = target_dir / f"{message_id}_{filename}"
        return target

    def _invoice_from_pdf(self, path: Path, periodo: str) -> FacturaExtraida:
        try:
            from invoice_automation.extractor import extract_invoice_from_pdf

            extracted = extract_invoice_from_pdf(path, platform=self.name)
            invoice = FacturaExtraida(
                proveedor=self.proveedor.nombre,
                numero=extracted.invoice_number or path.stem,
                fecha=extracted.issue_date,
                valor=extracted.total,
                moneda=extracted.currency,
                ruta_pdf=path,
                periodo=periodo,
            )
        except Exception:
            invoice = FacturaExtraida(
                proveedor=self.proveedor.nombre,
                numero=path.stem,
                ruta_pdf=path,
                periodo=periodo,
            )

        invoice.estado = validar_factura(invoice)
        return invoice


def month_bounds(periodo: str) -> tuple[date, date]:
    year_text, month_text = periodo.split("-", maxsplit=1)
    year = int(year_text)
    month = int(month_text)
    start = date(year, month, 1)
    if month == 12:
        return start, date(year + 1, 1, 1)
    return start, date(year, month + 1, 1)


def build_gmail_query(
    *,
    start: date,
    end: date,
    sender: str | None,
    subject: str | None,
) -> str:
    parts = [
        f"after:{start:%Y/%m/%d}",
        f"before:{end:%Y/%m/%d}",
        "has:attachment",
        "filename:pdf",
    ]
    if sender:
        parts.append(f"from:{sender}")
    if subject:
        clean_subject = subject.replace('"', "")
        parts.append(f'subject:"{clean_subject}"')
    return " ".join(parts)


def pdf_attachment_parts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for part in walk_message_parts(payload):
        filename = part.get("filename") or ""
        mime_type = part.get("mimeType") or ""
        body = part.get("body") or {}
        is_pdf = filename.lower().endswith(".pdf") or mime_type == "application/pdf"
        has_content = body.get("attachmentId") or body.get("data")
        if is_pdf and has_content:
            matches.append(
                {
                    "filename": filename,
                    "attachment_id": body.get("attachmentId"),
                    "data": body.get("data"),
                }
            )
    return matches


def walk_message_parts(part: dict[str, Any]) -> list[dict[str, Any]]:
    parts = [part]
    for child in part.get("parts") or []:
        parts.extend(walk_message_parts(child))
    return parts


def decode_gmail_data(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("utf-8"))


def safe_filename(filename: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename).strip()
    return cleaned or "factura.pdf"


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower())
    return cleaned.strip("-") or "proveedor"

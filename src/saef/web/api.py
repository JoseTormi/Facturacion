from __future__ import annotations

import html
from urllib.parse import quote
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from saef.config import settings
from saef.core.database import Database
from saef.extractors.registry import build_extractors
from saef.models import FacturaExtraida, PeriodoConsulta
from saef.web.auth import (
    authenticated_username,
    clear_session_cookie,
    create_session_token,
    require_authenticated_user,
    set_session_cookie,
    verify_credentials,
)


STATIC_DIR = Path(__file__).parent / "static"
database = Database(settings.database_path)


class EjecutarRequest(BaseModel):
    modo: Literal["mes", "anio", "rango"] = "mes"
    mes: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    anio: int | None = Field(default=None, ge=1900, le=9998)
    fecha_inicio: date | None = None
    fecha_fin: date | None = None

    @model_validator(mode="after")
    def validate_periodo(self) -> "EjecutarRequest":
        self.to_periodo()
        return self

    def to_periodo(self) -> PeriodoConsulta:
        if self.modo == "mes":
            if not self.mes:
                raise ValueError("Selecciona un mes.")
            return periodo_mes(self.mes)
        if self.modo == "anio":
            if self.anio is None:
                raise ValueError("Selecciona un anio.")
            return periodo_anio(self.anio)
        if self.fecha_inicio is None or self.fecha_fin is None:
            raise ValueError("Selecciona fecha inicial y fecha final.")
        return periodo_rango(self.fecha_inicio, self.fecha_fin)


@asynccontextmanager
async def lifespan(_: FastAPI):
    bootstrap()
    yield


app = FastAPI(
    title="SAEF",
    version="0.1.0",
    description="Sistema web para extraer y validar facturas de SaaS por periodo.",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index(request: Request):
    if not authenticated_username(request):
        return RedirectResponse("/login?next=/", status_code=303)
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/login", include_in_schema=False)
def login(request: Request, next: str = "/"):
    next_url = safe_next_url(next)
    if authenticated_username(request):
        return RedirectResponse(next_url, status_code=303)

    login_html = (STATIC_DIR / "login.html").read_text(encoding="utf-8")
    has_error = request.query_params.get("error") == "1"
    login_html = login_html.replace("__NEXT__", html.escape(next_url, quote=True))
    login_html = login_html.replace("__ERROR_HIDDEN__", "" if has_error else "hidden")
    return HTMLResponse(login_html)


@app.post("/auth/login", include_in_schema=False)
async def auth_login(request: Request) -> RedirectResponse:
    form = await request.form()
    username = str(form.get("username") or "")
    password = str(form.get("password") or "")
    next_url = safe_next_url(str(form.get("next") or "/"))

    if verify_credentials(username, password):
        response = RedirectResponse(next_url, status_code=303)
        set_session_cookie(response, create_session_token(username))
        return response

    encoded_next = quote(next_url, safe="/")
    return RedirectResponse(f"/login?error=1&next={encoded_next}", status_code=303)


@app.post("/logout", include_in_schema=False)
def logout() -> RedirectResponse:
    response = RedirectResponse("/login", status_code=303)
    clear_session_cookie(response)
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/proveedores")
def proveedores(_: str = Depends(require_authenticated_user)) -> dict[str, Any]:
    bootstrap()
    active = database.list_active_providers()
    return {"count": len(active), "proveedores": [item.model_dump() for item in active]}


@app.get("/resultados")
def resultados(
    periodo: str | None = None,
    mes: str | None = None,
    _: str = Depends(require_authenticated_user),
) -> dict[str, Any]:
    bootstrap()
    period_key = periodo or mes
    if not period_key:
        raise HTTPException(status_code=422, detail="Indica periodo o mes.")
    invoices = database.list_invoices(period_key)
    return {
        "periodo": period_key,
        "mes": period_key,
        "count": len(invoices),
        "resultados": invoice_payloads(invoices),
    }


@app.get("/facturas/{factura_id}/pdf")
def descargar_factura(
    factura_id: int,
    _: str = Depends(require_authenticated_user),
) -> FileResponse:
    bootstrap()
    invoice = database.get_invoice(factura_id)
    if not invoice or not invoice.ruta_pdf:
        raise HTTPException(status_code=404, detail="Factura no encontrada.")

    pdf_path = resolve_storage_path(invoice.ruta_pdf)
    if not pdf_path.exists() or not pdf_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"El PDF no existe en la ruta guardada: {invoice.ruta_pdf}",
        )

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=pdf_path.name,
    )


@app.post("/ejecutar")
def ejecutar(
    payload: EjecutarRequest,
    _: str = Depends(require_authenticated_user),
) -> dict[str, Any]:
    bootstrap()
    periodo = payload.to_periodo()
    database.upsert_period(periodo.clave, "en_proceso")
    database.delete_invoices(periodo.clave)

    providers = database.list_active_providers()
    extractors = build_extractors(providers, settings)
    errors: list[dict[str, str]] = []
    extracted_count = 0

    if not extractors:
        database.upsert_period(periodo.clave, "sin_extractores")
        return {
            **periodo_payload(periodo),
            "mes": periodo.clave,
            "estado": "sin_extractores",
            "extractores": [],
            "count": 0,
            "resultados": [],
            "errores": [],
        }

    for extractor in extractors:
        try:
            invoices = extractor.extraer(periodo)
            database.save_invoices(invoices)
            extracted_count += len(invoices)
        except Exception as exc:
            errors.append({"extractor": extractor.name, "error": str(exc)})

    final_status = "completado" if not errors else "con_errores"
    database.upsert_period(periodo.clave, final_status)
    stored = database.list_invoices(periodo.clave)

    return {
        **periodo_payload(periodo),
        "mes": periodo.clave,
        "estado": final_status,
        "extractores": [extractor.name for extractor in extractors],
        "count": extracted_count,
        "resultados": invoice_payloads(stored),
        "errores": errors,
    }


def bootstrap() -> None:
    settings.ensure_directories()
    database.ensure_schema()
    database.sync_gmail_provider_from_env(
        nombre=settings.gmail_provider_name,
        activo=settings.gmail_active,
        remitente=settings.gmail_sender,
        asunto=settings.gmail_subject,
    )


def invoice_payloads(invoices: list[FacturaExtraida]) -> list[dict[str, Any]]:
    return [invoice.model_dump(mode="json") for invoice in invoices]


def safe_next_url(next_url: str) -> str:
    if not next_url.startswith("/") or next_url.startswith("//"):
        return "/"
    if next_url.startswith("/auth/") or next_url.startswith("/static/"):
        return "/"
    return next_url


def resolve_storage_path(path: Path) -> Path:
    base_dir = Path.cwd()
    storage_root = settings.storage_dir
    if not storage_root.is_absolute():
        storage_root = base_dir / storage_root

    candidate = path
    if not candidate.is_absolute():
        candidate = base_dir / candidate

    resolved_storage = storage_root.resolve()
    resolved_candidate = candidate.resolve()
    try:
        resolved_candidate.relative_to(resolved_storage)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Ruta de PDF no permitida.") from exc

    return resolved_candidate


def periodo_mes(mes: str) -> PeriodoConsulta:
    year_text, month_text = mes.split("-", maxsplit=1)
    year = int(year_text)
    month = int(month_text)
    inicio = date(year, month, 1)
    if month == 12:
        fin_exclusivo = date(year + 1, 1, 1)
    else:
        fin_exclusivo = date(year, month + 1, 1)
    return PeriodoConsulta(
        modo="mes",
        clave=mes,
        inicio=inicio,
        fin_exclusivo=fin_exclusivo,
    )


def periodo_anio(anio: int) -> PeriodoConsulta:
    inicio = date(anio, 1, 1)
    return PeriodoConsulta(
        modo="anio",
        clave=str(anio),
        inicio=inicio,
        fin_exclusivo=date(anio + 1, 1, 1),
    )


def periodo_rango(fecha_inicio: date, fecha_fin: date) -> PeriodoConsulta:
    if fecha_inicio > fecha_fin:
        raise ValueError("La fecha inicial no puede ser posterior a la fecha final.")
    return PeriodoConsulta(
        modo="rango",
        clave=f"{fecha_inicio.isoformat()}_{fecha_fin.isoformat()}",
        inicio=fecha_inicio,
        fin_exclusivo=date.fromordinal(fecha_fin.toordinal() + 1),
    )


def periodo_payload(periodo: PeriodoConsulta) -> dict[str, str]:
    return {
        "modo": periodo.modo,
        "periodo": periodo.clave,
        "fecha_inicio": periodo.inicio.isoformat(),
        "fecha_fin": periodo.fin_inclusivo.isoformat(),
    }

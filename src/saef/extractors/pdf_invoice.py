from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from saef.core.comparator import validar_factura
from saef.models import FacturaExtraida


def factura_from_pdf(
    *,
    path: Path,
    proveedor: str,
    periodo: str,
    extractor_name: str,
) -> FacturaExtraida:
    if extractor_name == "zoom_web" or proveedor.casefold() == "zoom":
        invoice = zoom_factura_from_pdf(path=path, proveedor=proveedor, periodo=periodo)
        if invoice:
            invoice.estado = validar_factura(invoice)
            return invoice

    try:
        from invoice_automation.extractor import extract_invoice_from_pdf

        extracted = extract_invoice_from_pdf(path, platform=extractor_name)
        invoice = FacturaExtraida(
            proveedor=proveedor,
            numero=extracted.invoice_number or path.stem,
            fecha=extracted.issue_date,
            nit_tercero=extracted.issuer_tax_id,
            nombre_tercero=extracted.issuer_name or proveedor,
            descripcion=extracted.description,
            valor_bruto=extracted.gross_value
            if extracted.gross_value is not None
            else extracted.subtotal,
            iva_19=extracted.vat_19,
            iva_5=extracted.vat_5,
            impo_8=extracted.consumption_tax_8,
            total_neto=extracted.net_total if extracted.net_total is not None else extracted.total,
            valor=extracted.net_total if extracted.net_total is not None else extracted.total,
            moneda=extracted.currency,
            ruta_pdf=path,
            periodo=periodo,
        )
    except Exception:
        invoice = FacturaExtraida(
            proveedor=proveedor,
            numero=path.stem,
            ruta_pdf=path,
            periodo=periodo,
        )

    invoice.estado = validar_factura(invoice)
    return invoice


def zoom_factura_from_pdf(
    *,
    path: Path,
    proveedor: str,
    periodo: str,
) -> FacturaExtraida | None:
    try:
        from invoice_automation.extractor import (
            clean_extracted_text,
            extract_text,
            money_values,
        )
    except Exception:
        return None

    try:
        text = clean_extracted_text(extract_text(path))
    except Exception:
        return None

    invoice_number = find_zoom_invoice_number(text) or path.stem
    issue_date = find_zoom_invoice_date(text)
    description = find_zoom_description(text)
    subtotal = find_zoom_money_after_label(
        text,
        (
            "subtotal",
            "subtotal antes de impuestos",
        ),
        money_values,
    )
    total = find_zoom_money_after_label(
        text,
        (
            "total de la factura",
            "total (incluidos impuestos, tasas y recargos)",
            "invoice total",
        ),
        money_values,
    )
    currency = find_zoom_currency(text)
    issuer_name = find_zoom_issuer_name(text) or proveedor

    return FacturaExtraida(
        proveedor=proveedor,
        numero=invoice_number,
        fecha=issue_date,
        nombre_tercero=issuer_name,
        descripcion=description,
        valor_bruto=subtotal if subtotal is not None else total,
        iva_19=None,
        iva_5=None,
        impo_8=None,
        total_neto=total,
        valor=total,
        moneda=currency,
        ruta_pdf=path,
        periodo=periodo,
    )


def find_zoom_invoice_number(text: str) -> str | None:
    match = re.search(r"\bINV[A-Z0-9-]+\b", text, re.IGNORECASE)
    return match.group(0).upper() if match else None


def find_zoom_invoice_date(text: str) -> date | None:
    for line in text.splitlines():
        folded = fold_text_local(line)
        if "fecha de la factura" not in folded and "invoice date" not in folded:
            continue
        parsed = first_numeric_date(line)
        if parsed:
            return parsed
    return first_numeric_date(text)


def first_numeric_date(text: str) -> date | None:
    match = re.search(r"\b(?P<day>\d{1,2})/(?P<month>\d{1,2})/(?P<year>\d{4})\b", text)
    if not match:
        match = re.search(
            r"\b(?P<month>\d{1,2})/(?P<day>\d{1,2})/(?P<year>\d{4})\b",
            text,
        )
    if not match:
        return None
    try:
        return date(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )
    except ValueError:
        return None


def find_zoom_description(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        folded = fold_text_local(line)
        if "nombre del cargo" not in folded and "charge name" not in folded:
            continue

        parts: list[str] = []
        after_label = re.sub(r"(?i)^.*?(?:nombre del cargo|charge name)\s*:\s*", "", line)
        if after_label and after_label != line:
            parts.append(after_label)

        for next_line in lines[index + 1 : index + 5]:
            folded_next = fold_text_local(next_line)
            if (
                first_numeric_date(next_line)
                or folded_next.startswith("cantidad")
                or folded_next.startswith("precio unitario")
                or folded_next.startswith("subtotal")
                or folded_next.startswith("total")
            ):
                break
            parts.append(next_line)

        description = clean_zoom_description(" ".join(parts))
        if description:
            return description
    return None


def clean_zoom_description(value: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", value).strip(" :-")
    return cleaned or None


def find_zoom_money_after_label(
    text: str,
    labels: tuple[str, ...],
    money_values,
) -> Decimal | None:
    folded_labels = tuple(fold_text_local(label) for label in labels)
    for line in text.splitlines():
        folded = fold_text_local(line)
        if not any(label in folded for label in folded_labels):
            continue
        values = money_values(line)
        if values:
            return values[-1]
    return None


def find_zoom_currency(text: str) -> str | None:
    match = re.search(r"(?im)^\s*Moneda\s*:\s*([A-Z]{3})\s*$", text)
    if match:
        return match.group(1).upper()
    match = re.search(r"\b(USD|COP|EUR)\b", text, re.IGNORECASE)
    return match.group(1).upper() if match else None


def find_zoom_issuer_name(text: str) -> str | None:
    for line in text.splitlines()[:8]:
        candidate = line.strip()
        if "Zoom Communications" in candidate:
            return candidate
    return None


def fold_text_local(value: str) -> str:
    try:
        from invoice_automation.extractor import fold_text

        return fold_text(value)
    except Exception:
        return value.casefold()

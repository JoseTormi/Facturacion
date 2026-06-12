from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber

from invoice_automation.models import Invoice


DATE_PATTERNS = [
    re.compile(r"(?P<day>\d{1,2})[/-](?P<month>\d{1,2})[/-](?P<year>\d{4})"),
    re.compile(r"(?P<year>\d{4})[/-](?P<month>\d{1,2})[/-](?P<day>\d{1,2})"),
]
TEXT_DATE_PATTERNS = [
    re.compile(
        r"(?P<day>\d{1,2})\s+de\s+(?P<month_name>[a-zA-ZáéíóúÁÉÍÓÚñÑ]+)\s+de\s+(?P<year>\d{4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<day>\d{1,2})\s+(?P<month_name>[a-zA-ZáéíóúÁÉÍÓÚñÑ]{3,})\s+(?P<year>\d{4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<month_name>[a-zA-ZáéíóúÁÉÍÓÚñÑ]{3,})\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})",
        re.IGNORECASE,
    ),
]

MONTH_NAMES = {
    "ene": 1,
    "enero": 1,
    "jan": 1,
    "january": 1,
    "feb": 2,
    "febrero": 2,
    "february": 2,
    "mar": 3,
    "marzo": 3,
    "march": 3,
    "abr": 4,
    "abril": 4,
    "apr": 4,
    "april": 4,
    "may": 5,
    "mayo": 5,
    "jun": 6,
    "junio": 6,
    "june": 6,
    "jul": 7,
    "julio": 7,
    "july": 7,
    "ago": 8,
    "agosto": 8,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "septiembre": 9,
    "setiembre": 9,
    "september": 9,
    "oct": 10,
    "octubre": 10,
    "october": 10,
    "nov": 11,
    "noviembre": 11,
    "november": 11,
    "dic": 12,
    "diciembre": 12,
    "dec": 12,
    "december": 12,
}


def extract_invoice_from_pdf(path: Path, platform: str = "") -> Invoice:
    text = extract_text(path)
    return Invoice(
        platform=platform,
        invoice_number=find_invoice_number(text),
        issue_date=find_date(text),
        issuer_tax_id=find_tax_id(text, ["nit", "n.i.t", "identificacion tributaria"]),
        customer_tax_id=find_tax_id(text, ["cliente", "adquirente", "receptor"]),
        subtotal=find_money_after_label(text, ["subtotal", "sub total"]),
        tax=find_money_after_label(text, ["iva", "impuesto", "impuestos"]),
        total=find_money_after_label(text, ["total a pagar", "total"]),
        currency=find_currency(text),
        source_file=path,
        raw_text=text,
    )


def extract_text(path: Path) -> str:
    chunks: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            chunks.append(page_text)
    text = "\n".join(chunks)
    if len(text.strip()) >= 30:
        return text
    return extract_text_with_ocr(path) or text


def extract_text_with_ocr(path: Path) -> str | None:
    try:
        import pytesseract
        from pdf2image import convert_from_path
    except ImportError:
        return None

    chunks: list[str] = []
    for image in convert_from_path(path):
        chunks.append(pytesseract.image_to_string(image, lang="spa+eng"))
    return "\n".join(chunks)


def find_invoice_number(text: str) -> str | None:
    patterns = [
        r"(?:factura(?:\s+electronica)?|invoice)\s*(?:no\.?|numero|#|nro\.?)?\s*[:\-]?\s*([A-Z0-9\-]{4,})",
        r"\b(?:prefijo|consecutivo)\s*[:\-]?\s*([A-Z0-9\-]{4,})",
    ]
    return first_match(text, patterns)


def find_date(text: str) -> date | None:
    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        try:
            return date(
                int(match.group("year")),
                int(match.group("month")),
                int(match.group("day")),
            )
        except ValueError:
            continue
    for pattern in TEXT_DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        month = month_number(match.group("month_name"))
        if not month:
            continue
        try:
            return date(
                int(match.group("year")),
                month,
                int(match.group("day")),
            )
        except ValueError:
            continue
    return None


def find_tax_id(text: str, nearby_labels: list[str]) -> str | None:
    for label in nearby_labels:
        pattern = rf"{re.escape(label)}[^\d]{{0,25}}([\d\.\-]{{6,20}})"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return normalize_tax_id(match.group(1))
    match = re.search(r"\b\d{6,12}-?\d?\b", text)
    return normalize_tax_id(match.group(0)) if match else None


def find_money_after_label(text: str, labels: list[str]) -> Decimal | None:
    for label in labels:
        pattern = rf"{re.escape(label)}[^\d$]{{0,30}}(?:COP|USD|\$)?\s*([\d\.,]+)"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = parse_decimal(match.group(1))
            if value is not None:
                return value
    return None


def find_currency(text: str) -> str | None:
    upper = text.upper()
    if "US$" in upper:
        return "USD"
    for currency in ("COP", "USD", "EUR"):
        if currency in upper:
            return currency
    if "$" in text:
        return "COP"
    return None


def first_match(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def normalize_tax_id(value: str) -> str:
    return value.replace(".", "").strip()


def month_number(value: str) -> int | None:
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(character for character in normalized if not unicodedata.combining(character))
    return MONTH_NAMES.get(normalized.lower().rstrip("."))


def parse_decimal(value: str) -> Decimal | None:
    cleaned = value.strip().replace(" ", "")
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif cleaned.count(".") > 1:
        cleaned = cleaned.replace(".", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None

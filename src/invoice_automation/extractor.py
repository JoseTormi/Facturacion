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
MONEY_PATTERN = re.compile(
    r"(?:COP|USD|EUR|US\$|\$)?\s*-?\d[\d.,]*(?:\s*(?:COP|USD|EUR|US\$))?",
    re.IGNORECASE,
)
LEGAL_SUFFIX_PATTERN = re.compile(
    r"\b(?:S\.?A\.?S?\.?|LTDA\.?|LLC|INC\.?|CORP\.?|CORPORATION)\b",
    re.IGNORECASE,
)


def extract_invoice_from_pdf(path: Path, platform: str = "") -> Invoice:
    raw_text = extract_text(path)
    text = clean_extracted_text(raw_text)
    gross_value = find_money_after_label(
        text,
        ["valor bruto", "bruto", "subtotal", "sub total", "base gravable"],
    )
    vat_19 = find_tax_by_rate(text, 19, ["iva"])
    vat_5 = find_tax_by_rate(text, 5, ["iva"])
    consumption_tax_8 = find_tax_by_rate(
        text,
        8,
        ["impo", "impoconsumo", "impuesto al consumo", "consumo"],
    )
    net_total = find_money_after_label(text, ["total neto", "total a pagar", "total"])
    generic_tax = find_money_after_label(text, ["iva", "impuesto", "impuestos"])
    known_tax = sum_decimals(vat_19, vat_5, consumption_tax_8)
    return Invoice(
        platform=platform,
        invoice_number=find_invoice_number(text),
        issue_date=find_date(text),
        issuer_name=find_issuer_name(text),
        issuer_tax_id=find_tax_id(text, ["nit", "n.i.t", "identificacion tributaria"]),
        customer_tax_id=find_tax_id(text, ["cliente", "adquirente", "receptor"]),
        description=find_description(text),
        gross_value=gross_value,
        subtotal=gross_value,
        vat_19=vat_19,
        vat_5=vat_5,
        consumption_tax_8=consumption_tax_8,
        tax=known_tax if known_tax is not None else generic_tax,
        net_total=net_total,
        total=net_total,
        currency=find_currency(text),
        source_file=path,
        raw_text=raw_text,
    )


def clean_extracted_text(text: str) -> str:
    text = text.replace("\x00", "-")
    text = re.sub(r"[\x01-\x08\x0b-\x1f\x7f]", " ", text)
    return "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines())


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


def find_issuer_name(text: str) -> str | None:
    lines = text_lines(text)
    billing_markers = (" facturar a", " bill to", " cliente", " adquirente")

    for line in lines:
        folded = fold_text(line)
        for marker in billing_markers:
            position = folded.find(marker)
            if position > 3:
                candidate = clean_party_name(line[:position])
                if candidate:
                    return candidate

    labels = ["razon social", "nombre tercero", "nombre emisor", "emisor", "proveedor"]
    for index, line in enumerate(lines):
        folded = fold_text(line)
        for label in labels:
            position = folded.find(label)
            if position == -1:
                continue
            after_label = clean_party_name(line[position + len(label) :])
            if after_label:
                return after_label
            if index + 1 < len(lines):
                next_line = clean_party_name(lines[index + 1])
                if next_line:
                    return next_line

    for line in lines[:12]:
        candidate = clean_party_name(line)
        if not candidate:
            continue
        folded = fold_text(candidate)
        if LEGAL_SUFFIX_PATTERN.search(candidate) and not any(
            token in folded for token in ("factura", "invoice", "fecha", "total")
        ):
            return candidate

    return None


def find_description(text: str) -> str | None:
    lines = text_lines(text)
    labels = ("descripcion", "detalle", "concepto", "producto", "servicio")

    for index, line in enumerate(lines):
        folded = fold_text(line)
        label = next((item for item in labels if item in folded), None)
        if not label:
            continue

        position = folded.find(label)
        after_label = line[position + len(label) :].strip(" :-")
        if after_label and not is_description_header(after_label):
            candidate = clean_description(after_label)
            if candidate:
                return candidate

        for candidate_line in lines[index + 1 : index + 6]:
            candidate = clean_description(candidate_line)
            if candidate:
                return candidate

    return None


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
    labels = [fold_text(label) for label in nearby_labels]
    for line in text_lines(text):
        folded = fold_text(line)
        if not any(find_label_position(folded, label) != -1 for label in labels):
            continue
        match = re.search(r"\d[\d\.\-\s]{5,22}\d", line)
        if match:
            return normalize_tax_id(match.group(0))
    return None


def find_money_after_label(text: str, labels: list[str]) -> Decimal | None:
    folded_labels = [fold_text(label) for label in labels]
    for line in text_lines(text):
        folded = fold_text(line)
        for label in folded_labels:
            position = find_label_position(folded, label)
            if position == -1:
                continue
            values = money_values(line[position + len(label) :])
            if values:
                return values[-1]
    return None


def find_tax_by_rate(text: str, rate: int, labels: list[str]) -> Decimal | None:
    folded_labels = [fold_text(label) for label in labels]
    rate_pattern = re.compile(rf"\b{rate}(?:[,.]0+)?\s*%")
    for line in text_lines(text):
        folded = fold_text(line)
        if not any(find_label_position(folded, label) != -1 for label in folded_labels):
            continue
        if not rate_pattern.search(folded):
            continue
        values = money_values(line)
        if values:
            return values[-1]
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
    return value.replace(".", "").replace(" ", "").strip()


def text_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def fold_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return normalized.casefold()


def find_label_position(text: str, label: str) -> int:
    match = re.search(rf"(?<![a-z0-9]){re.escape(label)}(?![a-z0-9])", text)
    return match.start() if match else -1


def clean_party_name(value: str) -> str | None:
    candidate = re.sub(r"\s+", " ", value).strip(" :-")
    folded = fold_text(candidate)
    if len(candidate) < 3:
        return None
    blocked_tokens = (
        "factura",
        "invoice",
        "numero",
        "fecha",
        "total",
        "subtotal",
        "pagina",
        "nit",
    )
    if any(token in folded for token in blocked_tokens):
        return None
    if MONEY_PATTERN.search(candidate):
        return None
    return candidate


def clean_description(value: str) -> str | None:
    if is_description_header(value):
        return None
    candidate = re.sub(
        r"(?:COP|USD|EUR|US\$|\$)\s*-?\d[\d.,]*|-?\d[\d.,]*\s*(?:COP|USD|EUR|US\$)",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(r"\s+", " ", candidate).strip()
    candidate = re.sub(r"\s+\d+(?:[.,]\d+)?(?:\s+\d+(?:[.,]\d+)?)*$", "", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip(" :-")
    folded = fold_text(candidate)
    if len(candidate) < 3:
        return None
    blocked_tokens = (
        "subtotal",
        "total",
        "importe adeudado",
        "fecha",
        "pagina",
        "facturar a",
    )
    if any(token in folded for token in blocked_tokens):
        return None
    if MONEY_PATTERN.fullmatch(candidate):
        return None
    return candidate


def is_description_header(value: str) -> bool:
    folded = fold_text(value)
    return any(token in folded for token in ("cant", "cantidad", "precio", "importe", "valor"))


def money_values(value: str) -> list[Decimal]:
    values: list[Decimal] = []
    for match in MONEY_PATTERN.finditer(value):
        after = value[match.end() : match.end() + 3].lstrip()
        if after.startswith("%"):
            continue
        parsed = parse_decimal(match.group(0))
        if parsed is not None:
            values.append(parsed)
    return values


def sum_decimals(*values: Decimal | None) -> Decimal | None:
    present_values = [value for value in values if value is not None]
    if not present_values:
        return None
    return sum(present_values, Decimal("0"))


def month_number(value: str) -> int | None:
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return MONTH_NAMES.get(normalized.lower().rstrip("."))


def parse_decimal(value: str) -> Decimal | None:
    cleaned = re.sub(r"(?i)\b(?:COP|USD|EUR|US\$)\b|\$", "", value)
    cleaned = re.sub(r"[^\d,.\-]", "", cleaned)
    if not cleaned or cleaned in {"-", ",", "."}:
        return None

    if "," in cleaned and "." in cleaned:
        decimal_separator = "," if cleaned.rfind(",") > cleaned.rfind(".") else "."
        thousands_separator = "." if decimal_separator == "," else ","
        cleaned = cleaned.replace(thousands_separator, "").replace(decimal_separator, ".")
    elif "," in cleaned:
        parts = cleaned.split(",")
        if len(parts[-1]) in (1, 2):
            cleaned = "".join(parts[:-1]) + "." + parts[-1]
        else:
            cleaned = "".join(parts)
    elif "." in cleaned:
        parts = cleaned.split(".")
        if len(parts) > 2 and len(parts[-1]) != 2:
            cleaned = "".join(parts)
        elif len(parts) > 2:
            cleaned = "".join(parts[:-1]) + "." + parts[-1]
        elif len(parts[-1]) == 3 and len(parts[0]) <= 3:
            cleaned = "".join(parts)
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None

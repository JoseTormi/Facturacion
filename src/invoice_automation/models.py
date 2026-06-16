from datetime import date
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, Field


class Invoice(BaseModel):
    platform: str = ""
    invoice_number: str | None = None
    issue_date: date | None = None
    issuer_name: str | None = None
    issuer_tax_id: str | None = None
    customer_name: str | None = None
    customer_tax_id: str | None = None
    description: str | None = None
    gross_value: Decimal | None = None
    subtotal: Decimal | None = None
    vat_19: Decimal | None = None
    vat_5: Decimal | None = None
    consumption_tax_8: Decimal | None = None
    tax: Decimal | None = None
    net_total: Decimal | None = None
    total: Decimal | None = None
    currency: str | None = None
    source_file: Path
    raw_text: str = Field(default="", repr=False)

    def to_excel_row(self) -> dict[str, object]:
        return {
            "FECHA": self.issue_date.isoformat() if self.issue_date else None,
            "NIT TERCERO": self.issuer_tax_id,
            "NOMBRE TERCERO": self.issuer_name,
            "NRO FACT": self.invoice_number,
            "DESCRIPCION": self.description,
            "VALOR BRUTO": decimal_to_float(
                self.gross_value if self.gross_value is not None else self.subtotal
            ),
            "IVA 19%": float(self.vat_19) if self.vat_19 is not None else None,
            "IVA 5%": float(self.vat_5) if self.vat_5 is not None else None,
            "IMPO 8%": float(self.consumption_tax_8)
            if self.consumption_tax_8 is not None
            else None,
            "TOTAL NETO": decimal_to_float(
                self.net_total if self.net_total is not None else self.total
            ),
        }


def decimal_to_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None

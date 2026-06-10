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
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None
    currency: str | None = None
    source_file: Path
    raw_text: str = Field(default="", repr=False)

    def to_excel_row(self) -> dict[str, object]:
        return {
            "Plataforma": self.platform,
            "Numero factura": self.invoice_number,
            "Fecha emision": self.issue_date.isoformat() if self.issue_date else None,
            "Emisor": self.issuer_name,
            "NIT emisor": self.issuer_tax_id,
            "Cliente": self.customer_name,
            "NIT cliente": self.customer_tax_id,
            "Subtotal": float(self.subtotal) if self.subtotal is not None else None,
            "IVA/Impuestos": float(self.tax) if self.tax is not None else None,
            "Total": float(self.total) if self.total is not None else None,
            "Moneda": self.currency,
            "Archivo origen": str(self.source_file),
        }

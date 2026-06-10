from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel


class Proveedor(BaseModel):
    id: int | None = None
    nombre: str
    tipo: str
    activo: bool = True
    remitente: str | None = None
    asunto: str | None = None


class FacturaExtraida(BaseModel):
    proveedor: str
    numero: str | None = None
    fecha: date | None = None
    valor: Decimal | None = None
    moneda: str | None = None
    estado: str = "pendiente_validacion"
    ruta_pdf: Path | None = None
    periodo: str


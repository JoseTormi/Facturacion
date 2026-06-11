from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel


@dataclass(frozen=True)
class PeriodoConsulta:
    modo: str
    clave: str
    inicio: date
    fin_exclusivo: date

    @property
    def fin_inclusivo(self) -> date:
        return date.fromordinal(self.fin_exclusivo.toordinal() - 1)


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

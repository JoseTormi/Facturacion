from abc import ABC, abstractmethod

from saef.models import FacturaExtraida, PeriodoConsulta, Proveedor


class Extractor(ABC):
    name: str

    def __init__(self, proveedor: Proveedor) -> None:
        self.proveedor = proveedor

    @abstractmethod
    def extraer(self, periodo: PeriodoConsulta) -> list[FacturaExtraida]:
        """Extrae facturas para el rango de fechas indicado."""

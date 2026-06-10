from abc import ABC, abstractmethod

from saef.models import FacturaExtraida, Proveedor


class Extractor(ABC):
    name: str

    def __init__(self, proveedor: Proveedor) -> None:
        self.proveedor = proveedor

    @abstractmethod
    def extraer(self, periodo: str) -> list[FacturaExtraida]:
        """Extrae facturas para un periodo YYYY-MM."""


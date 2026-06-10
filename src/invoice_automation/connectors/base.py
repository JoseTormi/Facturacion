from abc import ABC, abstractmethod
from pathlib import Path


class BaseConnector(ABC):
    name: str

    def __init__(self, download_dir: Path) -> None:
        self.download_dir = download_dir

    @abstractmethod
    def download_invoices(self) -> list[Path]:
        """Download invoices and return the PDF paths."""

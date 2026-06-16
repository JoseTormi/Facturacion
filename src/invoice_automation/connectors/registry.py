from pathlib import Path

from invoice_automation.connectors.base import BaseConnector
from invoice_automation.connectors.example_portal import ExamplePortalConnector

CONNECTORS: dict[str, type[BaseConnector]] = {
    ExamplePortalConnector.name: ExamplePortalConnector,
}


def get_connector(name: str, download_dir: Path) -> BaseConnector:
    connector_class = CONNECTORS.get(name)
    if connector_class is None:
        available = ", ".join(sorted(CONNECTORS))
        raise ValueError(f"Plataforma no registrada: {name}. Disponibles: {available}")
    return connector_class(download_dir)

from saef.config import Settings
from saef.extractors.base import Extractor
from saef.extractors.gmail_extractor import GmailExtractor
from saef.extractors.zoom_web_extractor import ZoomWebExtractor
from saef.models import Proveedor


def build_extractors(proveedores: list[Proveedor], settings: Settings) -> list[Extractor]:
    extractors: list[Extractor] = []
    for proveedor in proveedores:
        if proveedor.tipo == "gmail":
            extractors.append(GmailExtractor(proveedor, settings))
        elif proveedor.tipo == "zoom_web":
            extractors.append(ZoomWebExtractor(proveedor, settings))
    return extractors

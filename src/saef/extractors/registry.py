from saef.config import Settings
from saef.extractors.base import Extractor
from saef.extractors.gmail_extractor import GmailExtractor
from saef.models import Proveedor


def build_extractors(proveedores: list[Proveedor], settings: Settings) -> list[Extractor]:
    extractors: list[Extractor] = []
    for proveedor in proveedores:
        if proveedor.tipo == "gmail":
            extractors.append(GmailExtractor(proveedor, settings))
    return extractors


from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from saef.config import settings
from saef.core.database import Database
from saef.extractors.registry import build_extractors
from saef.models import FacturaExtraida


STATIC_DIR = Path(__file__).parent / "static"
database = Database(settings.database_path)


class EjecutarRequest(BaseModel):
    mes: str = Field(..., pattern=r"^\d{4}-\d{2}$")

    @field_validator("mes")
    @classmethod
    def validate_month(cls, value: str) -> str:
        year_text, month_text = value.split("-", maxsplit=1)
        date(int(year_text), int(month_text), 1)
        return value


@asynccontextmanager
async def lifespan(_: FastAPI):
    bootstrap()
    yield


app = FastAPI(
    title="SAEF",
    version="0.1.0",
    description="Sistema web para extraer y validar facturas mensuales de SaaS.",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/proveedores")
def proveedores() -> dict[str, Any]:
    bootstrap()
    active = database.list_active_providers()
    return {"count": len(active), "proveedores": [item.model_dump() for item in active]}


@app.get("/resultados")
def resultados(mes: str) -> dict[str, Any]:
    bootstrap()
    invoices = database.list_invoices(mes)
    return {"mes": mes, "count": len(invoices), "resultados": invoice_payloads(invoices)}


@app.post("/ejecutar")
def ejecutar(payload: EjecutarRequest) -> dict[str, Any]:
    bootstrap()
    database.upsert_period(payload.mes, "en_proceso")

    providers = database.list_active_providers()
    extractors = build_extractors(providers, settings)
    errors: list[dict[str, str]] = []
    extracted_count = 0

    if not extractors:
        database.upsert_period(payload.mes, "sin_extractores")
        return {
            "mes": payload.mes,
            "estado": "sin_extractores",
            "extractores": [],
            "count": 0,
            "resultados": [],
            "errores": [],
        }

    for extractor in extractors:
        try:
            invoices = extractor.extraer(payload.mes)
            database.save_invoices(invoices)
            extracted_count += len(invoices)
        except Exception as exc:
            errors.append({"extractor": extractor.name, "error": str(exc)})

    final_status = "completado" if not errors else "con_errores"
    database.upsert_period(payload.mes, final_status)
    stored = database.list_invoices(payload.mes)

    return {
        "mes": payload.mes,
        "estado": final_status,
        "extractores": [extractor.name for extractor in extractors],
        "count": extracted_count,
        "resultados": invoice_payloads(stored),
        "errores": errors,
    }


def bootstrap() -> None:
    settings.ensure_directories()
    database.ensure_schema()
    database.sync_gmail_provider_from_env(
        nombre=settings.gmail_provider_name,
        activo=settings.gmail_active,
        remitente=settings.gmail_sender,
        asunto=settings.gmail_subject,
    )


def invoice_payloads(invoices: list[FacturaExtraida]) -> list[dict[str, Any]]:
    return [invoice.model_dump(mode="json") for invoice in invoices]


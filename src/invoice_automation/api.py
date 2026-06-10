from __future__ import annotations

import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile, mkdtemp
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from invoice_automation.connectors.registry import CONNECTORS
from invoice_automation.exporter import export_invoices_to_excel
from invoice_automation.extractor import extract_invoice_from_pdf
from invoice_automation.models import Invoice


app = FastAPI(
    title="Facturacion API",
    version="0.1.0",
    description="API para extraer datos de facturas PDF y generar Excel.",
)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": "Facturacion API",
        "health": "/health",
        "docs": "/docs",
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/platforms")
def list_platforms() -> dict[str, list[str]]:
    return {"platforms": sorted(CONNECTORS)}


@app.post("/extract")
async def extract_invoices(
    files: list[UploadFile] = File(...),
    platform: str = Form(""),
) -> dict[str, object]:
    workdir = Path(mkdtemp(prefix="facturas_api_"))
    try:
        invoices = await _extract_uploads(files, platform, workdir)
        return {
            "count": len(invoices),
            "invoices": [_invoice_payload(invoice) for invoice in invoices],
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


@app.post("/extract/excel")
async def extract_excel(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    platform: str = Form(""),
) -> FileResponse:
    workdir = Path(mkdtemp(prefix="facturas_api_"))
    output_file = NamedTemporaryFile(delete=False, suffix=".xlsx")
    output_path = Path(output_file.name)
    output_file.close()

    try:
        invoices = await _extract_uploads(files, platform, workdir)
        export_invoices_to_excel(invoices, output_path)
    except Exception:
        shutil.rmtree(workdir, ignore_errors=True)
        output_path.unlink(missing_ok=True)
        raise

    background_tasks.add_task(shutil.rmtree, workdir, ignore_errors=True)
    background_tasks.add_task(output_path.unlink, missing_ok=True)
    return FileResponse(
        output_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="facturas.xlsx",
        background=background_tasks,
    )


async def _extract_uploads(
    files: list[UploadFile],
    platform: str,
    workdir: Path,
) -> list[Invoice]:
    if not files:
        raise HTTPException(status_code=400, detail="Sube al menos un archivo PDF.")

    invoices: list[Invoice] = []
    for upload in files:
        filename = _safe_pdf_filename(upload.filename)
        target = workdir / f"{uuid4().hex}_{filename}"
        await _save_upload(upload, target)

        try:
            invoice = extract_invoice_from_pdf(target, platform=platform)
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail=f"No se pudo procesar {filename}: {exc}",
            ) from exc

        invoice.source_file = Path(filename)
        invoices.append(invoice)

    return invoices


async def _save_upload(upload: UploadFile, target: Path) -> None:
    try:
        with target.open("wb") as buffer:
            while chunk := await upload.read(1024 * 1024):
                buffer.write(chunk)
    finally:
        await upload.close()


def _safe_pdf_filename(filename: str | None) -> str:
    value = (filename or "factura.pdf").replace("\\", "/").split("/")[-1].strip()
    value = value or "factura.pdf"
    if not value.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail=f"Solo se aceptan PDFs: {value}")
    return value


def _invoice_payload(invoice: Invoice) -> dict[str, object]:
    return invoice.model_dump(mode="json", exclude={"raw_text"})

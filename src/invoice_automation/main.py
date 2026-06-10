from pathlib import Path
from typing import Annotated

import typer

from invoice_automation.config import settings
from invoice_automation.connectors.registry import get_connector
from invoice_automation.exporter import export_invoices_to_excel
from invoice_automation.extractor import extract_invoice_from_pdf

app = typer.Typer(help="Descarga facturas, extrae informacion y genera Excel.")


@app.command()
def extract_local(
    input_dir: Annotated[
        Path | None,
        typer.Option(help="Carpeta con PDFs ya descargados."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(help="Archivo Excel de salida."),
    ] = None,
) -> None:
    settings.ensure_directories()
    source_dir = input_dir or settings.download_dir
    output_path = output or settings.output_dir / "facturas.xlsx"

    pdfs = sorted(source_dir.glob("*.pdf"))
    if not pdfs:
        typer.echo(f"No se encontraron PDFs en {source_dir}")
        raise typer.Exit(code=1)

    invoices = [extract_invoice_from_pdf(path) for path in pdfs]
    export_invoices_to_excel(invoices, output_path)
    typer.echo(f"Excel generado: {output_path}")


@app.command()
def run_platform(
    platform: str = typer.Argument(..., help="Nombre de la plataforma registrada."),
    output: Annotated[
        Path | None,
        typer.Option(help="Archivo Excel de salida."),
    ] = None,
) -> None:
    settings.ensure_directories()
    connector = get_connector(platform, settings.download_dir / platform)
    downloaded_files = connector.download_invoices()
    output_path = output or settings.output_dir / f"facturas_{platform}.xlsx"

    invoices = [
        extract_invoice_from_pdf(path, platform=platform)
        for path in downloaded_files
        if path.suffix.lower() == ".pdf"
    ]
    export_invoices_to_excel(invoices, output_path)
    typer.echo(f"Descargadas: {len(downloaded_files)}")
    typer.echo(f"Excel generado: {output_path}")


@app.command()
def list_platforms() -> None:
    from invoice_automation.connectors.registry import CONNECTORS

    for name in sorted(CONNECTORS):
        typer.echo(name)


if __name__ == "__main__":
    app()

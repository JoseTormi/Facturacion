from pathlib import Path

from playwright.sync_api import sync_playwright

from invoice_automation.config import settings
from invoice_automation.connectors.base import BaseConnector


class ExamplePortalConnector(BaseConnector):
    name = "example"

    def download_invoices(self) -> list[Path]:
        if not settings.example_portal_user or not settings.example_portal_password:
            raise RuntimeError("Configura EXAMPLE_PORTAL_USER y EXAMPLE_PORTAL_PASSWORD en .env")

        self.download_dir.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False)
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()

            # Reemplaza esta URL y selectores por los del portal real.
            page.goto("https://example.com/login", wait_until="networkidle")
            page.fill("input[name='email']", settings.example_portal_user)
            page.fill("input[name='password']", settings.example_portal_password)
            page.click("button[type='submit']")
            page.wait_for_load_state("networkidle")

            # Ejemplo: descargar el primer PDF disponible.
            downloaded_files: list[Path] = []
            with page.expect_download() as download_info:
                page.click("text=Descargar factura")
            download = download_info.value
            target = self.download_dir / download.suggested_filename
            download.save_as(target)
            downloaded_files.append(target)

            context.close()
            browser.close()

        return downloaded_files

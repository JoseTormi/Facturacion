from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from saef.config import Settings
from saef.extractors.base import Extractor
from saef.extractors.pdf_invoice import factura_from_pdf
from saef.models import FacturaExtraida, PeriodoConsulta, Proveedor

SIGN_IN_PATTERN = re.compile(r"/(?:signin|login|sso)(?:[/?#]|$)", re.IGNORECASE)
PDF_LINK_SELECTOR = "a[href*='.pdf'], a[href*='.PDF']"
BILLING_URL_CANDIDATES = (
    "https://zoom.us/billing/report",
    "https://zoom.us/billing/payment",
    "https://zoom.us/billing/invoices",
    "https://zoom.us/billing/invoice",
    "https://zoom.us/billing",
    "https://zoom.us/account/billing",
    "https://us06web.zoom.us/billing/report",
    "https://us06web.zoom.us/billing/payment",
    "https://us06web.zoom.us/billing/invoices",
    "https://us06web.zoom.us/billing/invoice",
    "https://us06web.zoom.us/billing",
    "https://us06web.zoom.us/account/billing",
)
BILLING_PATTERN = re.compile(
    r"(billing|invoice|facturaci[oó]n|factura|recibo|payment|pagos?)",
    re.IGNORECASE,
)
DOWNLOAD_PATTERN = re.compile(
    r"(download|descargar|pdf|invoice|factura|receipt|recibo)",
    re.IGNORECASE,
)
DOWNLOAD_ACTION_SELECTORS = (
    "a:has-text('Download')",
    "button:has-text('Download')",
    "a:has-text('Descargar')",
    "button:has-text('Descargar')",
    "a:has-text('PDF')",
    "button:has-text('PDF')",
    "a[aria-label*='Download']",
    "button[aria-label*='Download']",
    "a[aria-label*='Descargar']",
    "button[aria-label*='Descargar']",
)
INVOICE_DATE_PATTERN = re.compile(
    r"\b("
    r"January|February|March|April|May|June|July|August|September|October|November|December"
    r")\s+(\d{1,2}),\s+(\d{4})\b",
    re.IGNORECASE,
)


class ZoomWebExtractor(Extractor):
    name = "zoom_web"

    def __init__(self, proveedor: Proveedor, settings: Settings) -> None:
        super().__init__(proveedor)
        self.settings = settings

    def extraer(self, periodo: PeriodoConsulta) -> list[FacturaExtraida]:
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Instala Playwright y Chromium con: pip install -r requirements.txt; "
                "playwright install chromium"
            ) from exc

        target_dir = self._target_dir(periodo.clave)
        downloaded_files: list[Path] = []
        seen_sources: set[str] = set()
        download_errors: list[str] = []
        last_download_at = [time.monotonic()]
        attached_pages: set[int] = set()

        def register_page(page: Any) -> None:
            page_key = id(page)
            if page_key in attached_pages:
                return
            attached_pages.add(page_key)
            page.on(
                "download",
                lambda download: self._save_download(
                    download,
                    target_dir,
                    downloaded_files,
                    seen_sources,
                    last_download_at,
                    download_errors,
                ),
            )
            page.on(
                "response",
                lambda response: self._save_pdf_response(
                    response,
                    target_dir,
                    downloaded_files,
                    seen_sources,
                    last_download_at,
                    download_errors,
                ),
            )

        try:
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.settings.zoom_profile_dir),
                    headless=self.settings.zoom_headless,
                    accept_downloads=True,
                    args=["--start-maximized"],
                    no_viewport=True,
                )
                context.on("page", register_page)
                for existing_page in context.pages:
                    register_page(existing_page)

                page = context.pages[0] if context.pages else context.new_page()
                register_page(page)

                page.goto(
                    self.settings.zoom_start_url,
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                self._bring_to_front(page)
                page = self._wait_for_login_if_needed(context, page)
                found_billing_page = False
                if not page.is_closed():
                    found_billing_page = self._navigate_to_billing(page, context)
                self._show_helper_banner(page, periodo)
                if found_billing_page:
                    self._download_available_invoices(context, periodo)
                self._wait_for_downloads(context, downloaded_files, last_download_at)
                context.close()
        except PlaywrightError as exc:
            raise RuntimeError(
                "No se pudo abrir Chromium para Zoom. Verifica que ejecutaste "
                "'playwright install chromium' y que esta maquina puede abrir navegador."
            ) from exc

        if not downloaded_files:
            detail = f" Detalle: {download_errors[0]}" if download_errors else ""
            raise RuntimeError(
                "No se descargaron PDFs desde Zoom. SAEF entra automaticamente a "
                "https://zoom.us/billing/report y filtra por el periodo elegido. "
                "Si la sesion expiro, inicia sesion una vez con "
                f"SAEF_ZOOM_HEADLESS=false.{detail}"
            )

        return [
            factura_from_pdf(
                path=path,
                proveedor=self.proveedor.nombre,
                periodo=periodo.clave,
                extractor_name=self.name,
            )
            for path in downloaded_files
        ]

    def _target_dir(self, periodo: str) -> Path:
        target_dir = self.settings.storage_dir / periodo / slugify(self.proveedor.nombre)
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir

    def _wait_for_login_if_needed(self, context: Any, page: Any) -> Any:
        if not self._is_sign_in_page(page):
            return page

        if self.settings.zoom_headless:
            raise RuntimeError(
                "La sesion guardada de Zoom no esta activa. Cambia temporalmente "
                "SAEF_ZOOM_HEADLESS=false, ejecuta SAEF una vez para iniciar sesion "
                "en Zoom y luego vuelve a dejar SAEF_ZOOM_HEADLESS=true."
            )

        self._show_message(
            page,
            "SAEF Zoom: inicia sesion en Zoom. Cuando termines, SAEF seguira capturando PDFs.",
        )
        deadline = time.monotonic() + max(30, self.settings.zoom_download_wait_seconds)
        while time.monotonic() < deadline:
            logged_page = self._logged_zoom_page(context)
            if logged_page is not None:
                self._bring_to_front(logged_page)
                return logged_page
            if page.is_closed():
                replacement = self._first_open_page(context)
                if replacement is None:
                    return page
                page = replacement
            page.wait_for_timeout(1_000)
        return page

    def _show_helper_banner(self, page: Any, periodo: PeriodoConsulta) -> None:
        self._show_message(
            page,
            "SAEF Zoom: abre Billing/Invoices o Facturacion, descarga los PDF del "
            f"periodo {periodo.clave} ({periodo.inicio} a {periodo.fin_inclusivo}). "
            "Cierra esta pestana al terminar.",
        )

    def _show_message(self, page: Any, message: str) -> None:
        try:
            page.evaluate(
                """
                (message) => {
                  const old = document.getElementById("saef-download-helper");
                  if (old) old.remove();

                  const helper = document.createElement("div");
                  helper.id = "saef-download-helper";
                  helper.textContent = message;
                  Object.assign(helper.style, {
                    position: "fixed",
                    zIndex: "2147483647",
                    top: "12px",
                    right: "12px",
                    maxWidth: "430px",
                    padding: "12px 14px",
                    borderRadius: "8px",
                    background: "#0b1930",
                    color: "#ffffff",
                    font: "600 13px/1.45 system-ui, -apple-system, BlinkMacSystemFont, sans-serif",
                    boxShadow: "0 16px 36px rgba(0, 0, 0, 0.28)",
                  });
                  document.documentElement.appendChild(helper);
                }
                """,
                message,
            )
        except Exception:
            return

    def _bring_to_front(self, page: Any) -> None:
        try:
            page.bring_to_front()
        except Exception:
            return

    def _is_sign_in_page(self, page: Any) -> bool:
        try:
            if SIGN_IN_PATTERN.search(page.url):
                return True
            title = page.title().lower()
            if "sign in" in title or "iniciar sesi" in title:
                return True
            text = page.locator("body").inner_text(timeout=1_000).lower()
            return "sign in" in text[:1500] or "iniciar sesi" in text[:1500]
        except Exception:
            return False

    def _first_open_page(self, context: Any) -> Any | None:
        try:
            for page in context.pages:
                if not page.is_closed():
                    return page
        except Exception:
            return None
        return None

    def _logged_zoom_page(self, context: Any) -> Any | None:
        try:
            pages = [page for page in context.pages if not page.is_closed()]
        except Exception:
            return None

        for page in reversed(pages):
            try:
                parsed = urlparse(page.url)
            except Exception:
                continue
            if "zoom.us" not in parsed.netloc.lower():
                continue
            if not self._is_sign_in_page(page):
                return page
        return None

    def _navigate_to_billing(self, page: Any, context: Any) -> bool:
        if self._page_looks_like_billing(page):
            return True

        if self._click_billing_link(page):
            candidate = self._logged_zoom_page(context) or page
            if self._page_looks_like_billing(candidate):
                return True
            page = candidate

        current_url = page.url
        for url in self._billing_candidates_for(current_url):
            if self._goto_if_available(page, url) and self._page_looks_like_billing(page):
                return True
        return False

    def _billing_candidates_for(self, current_url: str) -> list[str]:
        candidates = list(BILLING_URL_CANDIDATES)
        parsed = urlparse(current_url or "")
        if parsed.scheme and parsed.netloc and "zoom.us" in parsed.netloc.lower():
            host_base = f"{parsed.scheme}://{parsed.netloc}"
            candidates = [
                f"{host_base}/billing/report",
                f"{host_base}/billing/payment",
                f"{host_base}/billing/invoices",
                f"{host_base}/billing/invoice",
                f"{host_base}/billing",
                f"{host_base}/account/billing",
                *candidates,
            ]

        ordered: list[str] = []
        for candidate in candidates:
            if candidate not in ordered:
                ordered.append(candidate)
        return ordered

    def _goto_if_available(self, page: Any, url: str) -> bool:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            self._bring_to_front(page)
            return not self._is_sign_in_page(page)
        except Exception:
            return False

    def _click_billing_link(self, page: Any) -> bool:
        links = self._matching_links(page, BILLING_PATTERN, limit=30)
        links.sort(
            key=lambda link: billing_link_priority(
                link.get("text") or "",
                link.get("href") or "",
            ),
        )
        for link in links:
            href = link.get("href") or ""
            if not href or self._skip_url(href):
                continue
            if self._goto_if_available(page, href):
                return True
        return False

    def _page_looks_like_billing(self, page: Any) -> bool:
        try:
            parsed = urlparse(page.url)
            path = parsed.path.lower()
            if path.startswith("/billing") and not path.startswith("/billing/pbx"):
                return True
        except Exception:
            pass

        try:
            title = page.title().lower()
            if any(
                token in title
                for token in ("payment history", "billing management", "plan management")
            ):
                return True
        except Exception:
            pass

        try:
            text = page.locator("body").inner_text(timeout=3_000)
        except Exception:
            text = ""
        return "Invoice Number" in text and "Invoice Date" in text

    def _download_available_invoices(self, context: Any, periodo: PeriodoConsulta) -> None:
        visited: set[str] = set()

        for _ in range(3):
            pages = [page for page in context.pages if not page.is_closed()]
            for page in pages:
                if page.url in visited:
                    continue
                visited.add(page.url)
                if not self._page_looks_like_billing(page):
                    continue
                self._bring_to_front(page)
                if self._download_payment_history_invoices(page, periodo):
                    continue
                self._click_visible_pdf_links(page)
                self._click_download_actions(page)
                self._visit_download_links(page)

    def _download_payment_history_invoices(
        self,
        page: Any,
        periodo: PeriodoConsulta,
    ) -> bool:
        if not self._wait_for_payment_history_rows(page):
            return False

        try:
            rows = page.locator("button.ph-invoice-number").evaluate_all(
                """
                (buttons) => buttons.map((button) => {
                  const row = button.closest('tr[role="row"], tr.zoom-virtual-table__row');
                  const text = row
                    ? (row.innerText || row.textContent || "")
                    : (button.innerText || button.textContent || "");
                  return {
                    invoice: (button.innerText || button.textContent || "").trim(),
                    text,
                  };
                })
                """,
            )
        except Exception:
            return False

        handled_payment_history = bool(rows)
        for row in rows:
            invoice_number = str(row.get("invoice") or "").strip()
            row_text = str(row.get("text") or "")
            if not invoice_number or not self._row_matches_period(row_text, periodo):
                continue

            try:
                button = page.locator("button.ph-invoice-number").filter(
                    has_text=invoice_number,
                )
                button.first.click(timeout=5_000)
                page.wait_for_timeout(800)
            except Exception:
                continue
        return handled_payment_history

    def _click_visible_pdf_links(self, page: Any) -> None:
        try:
            links = page.locator(PDF_LINK_SELECTOR)
            count = min(links.count(), 20)
        except Exception:
            return

        for index in range(count):
            link = links.nth(index)
            try:
                if not link.is_visible(timeout=1_000):
                    continue
                with page.expect_download(timeout=3_000):
                    link.click(timeout=3_000)
            except Exception:
                continue

    def _click_download_actions(self, page: Any) -> None:
        for selector in DOWNLOAD_ACTION_SELECTORS:
            try:
                actions = page.locator(selector)
                count = min(actions.count(), 30)
            except Exception:
                continue

            for index in range(count):
                action = actions.nth(index)
                try:
                    if not action.is_visible(timeout=700):
                        continue
                    href = action.get_attribute("href", timeout=700)
                    if href and self._skip_url(href):
                        continue
                    action.scroll_into_view_if_needed(timeout=1_000)
                    with page.expect_download(timeout=5_000):
                        action.click(timeout=5_000)
                except Exception:
                    try:
                        action.click(timeout=2_000)
                    except Exception:
                        continue

    def _visit_download_links(self, page: Any) -> None:
        for link in self._matching_links(page, DOWNLOAD_PATTERN, limit=40):
            href = link.get("href") or ""
            if not href or self._skip_url(href):
                continue
            self._open_link_for_capture(page, href)

    def _matching_links(
        self,
        page: Any,
        pattern: re.Pattern[str],
        *,
        limit: int,
    ) -> list[dict[str, str]]:
        try:
            links = page.locator("a[href]").evaluate_all(
                """
                (elements) => elements.map((link) => ({
                  text: (link.innerText || link.textContent || "").trim(),
                  href: link.href || ""
                }))
                """,
            )
        except Exception:
            return []

        matches: list[dict[str, str]] = []
        for link in links:
            text = str(link.get("text") or "")
            href = str(link.get("href") or "")
            if pattern.search(f"{text} {href}"):
                matches.append({"text": text, "href": href})
            if len(matches) >= limit:
                break
        return matches

    def _open_link_for_capture(self, page: Any, href: str) -> None:
        try:
            with page.expect_download(timeout=5_000):
                page.goto(href, wait_until="domcontentloaded", timeout=30_000)
        except Exception:
            try:
                page.goto(href, wait_until="domcontentloaded", timeout=30_000)
            except Exception:
                return

    def _skip_url(self, href: str) -> bool:
        parsed = urlparse(href)
        lowered = href.lower()
        if parsed.scheme not in {"http", "https"}:
            return True
        if "zoom.us" not in parsed.netloc.lower():
            return True
        return any(
            token in lowered
            for token in (
                "logout",
                "signout",
                "signup",
                "/billing/pbx",
                "/client/",
                "/download",
                "support.zoom.us",
                "marketplace.zoom.us",
            )
        )

    def _wait_for_payment_history_rows(self, page: Any) -> bool:
        try:
            page.locator("button.ph-invoice-number").first.wait_for(timeout=15_000)
            page.wait_for_function(
                """
                () => Array.from(document.querySelectorAll('button.ph-invoice-number'))
                  .some((button) => {
                    const row = button.closest('tr[role="row"], tr.zoom-virtual-table__row');
                    const text = row ? (row.innerText || row.textContent || "") : "";
                    const datePattern = new RegExp([
                      "\\\\b(January|February|March|April|May|June|July|",
                      "August|September|October|November|December)",
                      "\\\\s+\\\\d{1,2},\\\\s+\\\\d{4}\\\\b",
                    ].join(""), "i");
                    return datePattern.test(text);
                  })
                """,
                timeout=15_000,
            )
            return True
        except Exception:
            return False

    def _row_matches_period(self, text: str, periodo: PeriodoConsulta) -> bool:
        dates = []
        for match in INVOICE_DATE_PATTERN.finditer(text):
            try:
                parsed = datetime.strptime(match.group(0), "%B %d, %Y").date()
            except ValueError:
                continue
            dates.append(parsed)

        if not dates:
            return False
        return any(periodo.inicio <= parsed < periodo.fin_exclusivo for parsed in dates)

    def _wait_for_downloads(
        self,
        context: Any,
        downloaded_files: list[Path],
        last_download_at: list[float],
    ) -> None:
        started_at = time.monotonic()
        max_wait = max(15, self.settings.zoom_download_wait_seconds)
        idle_wait = max(3, self.settings.zoom_download_idle_seconds)

        while True:
            now = time.monotonic()
            if downloaded_files and now - last_download_at[0] >= idle_wait:
                return
            if now - started_at >= max_wait:
                return
            if not self._has_open_pages(context):
                return

            pages = [page for page in context.pages if not page.is_closed()]
            if pages:
                try:
                    pages[0].wait_for_timeout(1_000)
                except Exception:
                    return
            else:
                time.sleep(1)

    def _has_open_pages(self, context: Any) -> bool:
        try:
            return any(not page.is_closed() for page in context.pages)
        except Exception:
            return False

    def _save_download(
        self,
        download: Any,
        target_dir: Path,
        downloaded_files: list[Path],
        seen_sources: set[str],
        last_download_at: list[float],
        download_errors: list[str],
    ) -> None:
        source_key = download.url or download.suggested_filename
        if source_key in seen_sources:
            return

        try:
            filename = safe_filename(download.suggested_filename or filename_from_url(download.url))
            target = reusable_download_path(target_dir / filename, downloaded_files)
            download.save_as(target)
            if not is_pdf_file(target):
                target.unlink(missing_ok=True)
                return
            if target.suffix.lower() != ".pdf":
                pdf_target = unique_path(target.with_suffix(".pdf"))
                target.replace(pdf_target)
                target = pdf_target
            seen_sources.add(source_key)
            self._record_pdf(target, downloaded_files, last_download_at)
        except Exception as exc:
            download_errors.append(str(exc))

    def _save_pdf_response(
        self,
        response: Any,
        target_dir: Path,
        downloaded_files: list[Path],
        seen_sources: set[str],
        last_download_at: list[float],
        download_errors: list[str],
    ) -> None:
        try:
            headers = response.headers
            content_type = headers.get("content-type", "")
            content_disposition = headers.get("content-disposition", "")
            is_pdf = (
                "application/pdf" in content_type.lower()
                or ".pdf" in response.url.lower()
                or ".pdf" in content_disposition.lower()
            )
            if not is_pdf or response.url in seen_sources:
                return

            filename = safe_filename(
                filename_from_content_disposition(content_disposition)
                or filename_from_url(response.url)
            )
            if not filename.lower().endswith(".pdf"):
                filename = f"{Path(filename).stem or 'factura_zoom'}.pdf"

            body = response.body()
            if not body.startswith(b"%PDF-"):
                return

            target = reusable_download_path(target_dir / filename, downloaded_files)
            target.write_bytes(body)
            seen_sources.add(response.url)
            self._record_pdf(target, downloaded_files, last_download_at)
        except Exception as exc:
            download_errors.append(str(exc))

    def _record_pdf(
        self,
        target: Path,
        downloaded_files: list[Path],
        last_download_at: list[float],
    ) -> None:
        if target.suffix.lower() != ".pdf":
            return
        downloaded_files.append(target)
        last_download_at[0] = time.monotonic()


def filename_from_content_disposition(value: str) -> str:
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', value, re.IGNORECASE)
    if not match:
        return ""
    return unquote(match.group(1).strip())


def filename_from_url(value: str) -> str:
    parsed = urlparse(value or "")
    name = Path(unquote(parsed.path)).name
    return name or "factura_zoom.pdf"


def safe_filename(filename: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename).strip()
    return cleaned or "factura_zoom.pdf"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    for index in range(2, 10_000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate

    raise RuntimeError(f"No se pudo generar un nombre unico para {path}")


def reusable_download_path(path: Path, downloaded_files: list[Path]) -> Path:
    if any(existing.name == path.name for existing in downloaded_files):
        return unique_path(path)
    path.unlink(missing_ok=True)
    return path


def is_pdf_file(path: Path) -> bool:
    try:
        with path.open("rb") as file:
            return file.read(5) == b"%PDF-"
    except OSError:
        return False


def billing_link_priority(text: str, href: str) -> int:
    haystack = f"{text} {href}".lower()
    if "payment history" in haystack or "/billing/report" in haystack:
        return 0
    if "billing management" in haystack or "/billing/payment" in haystack:
        return 1
    if "plan management" in haystack or href.rstrip("/").endswith("/billing"):
        return 2
    if "invoice" in haystack or "factura" in haystack:
        return 3
    return 10


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower())
    return cleaned.strip("-") or "proveedor"

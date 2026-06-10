from __future__ import annotations

import argparse
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from saef.config import settings
from saef.extractors.gmail_extractor import SCOPES


def main() -> None:
    parser = argparse.ArgumentParser(description="Autoriza Gmail para SAEF.")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="No abre navegador automaticamente; imprime la URL de autorizacion.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Puerto local para recibir el callback OAuth.",
    )
    args = parser.parse_args()

    settings.ensure_directories()
    authorize_gmail(
        credentials_path=settings.gmail_credentials_path,
        token_path=settings.gmail_token_path,
        open_browser=not args.no_browser,
        port=args.port,
    )
    print(f"Token guardado en {settings.gmail_token_path}")


def authorize_gmail(
    *,
    credentials_path: Path,
    token_path: Path,
    open_browser: bool,
    port: int,
) -> None:
    credentials = None

    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())

    if not credentials or not credentials.valid:
        if not credentials_path.exists():
            raise SystemExit(f"No existe el archivo OAuth: {credentials_path}")

        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
        credentials = flow.run_local_server(
            port=port,
            open_browser=open_browser,
            prompt="consent",
        )

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credentials.to_json(), encoding="utf-8")


if __name__ == "__main__":
    main()


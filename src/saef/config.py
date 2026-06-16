from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    storage_dir: Path = Path("storage")
    database_path: Path = Path("storage/saef.sqlite3")
    gmail_credentials_path: Path = Path("credentials/gmail_oauth_client.json")
    gmail_token_path: Path = Path("credentials/gmail_token.json")

    gmail_provider_name: str = "Gmail"
    gmail_sender: str = ""
    gmail_subject: str = ""
    gmail_active: bool = False

    zoom_active: bool = False
    zoom_provider_name: str = "Zoom"
    zoom_start_url: str = "https://zoom.us/billing/report"
    zoom_profile_dir: Path = Path("credentials/playwright/zoom")
    zoom_download_wait_seconds: int = 240
    zoom_download_idle_seconds: int = 12
    zoom_headless: bool = True

    admin_username: str = "admin"
    admin_password: str = "admin"
    auth_secret_key: str = "cambia-esta-clave-en-produccion"
    auth_session_minutes: int = 480
    auth_cookie_secure: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="SAEF_",
        extra="ignore",
    )

    def ensure_directories(self) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.gmail_credentials_path.parent.mkdir(parents=True, exist_ok=True)
        self.gmail_token_path.parent.mkdir(parents=True, exist_ok=True)
        self.zoom_profile_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()

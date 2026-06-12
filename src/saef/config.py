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


settings = Settings()

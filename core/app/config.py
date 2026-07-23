"""Application configuration."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for EnPu core (env prefix ENPU_)."""

    model_config = SettingsConfigDict(
        env_prefix="ENPU_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "EnPu Core"
    app_version: str = "0.0.1"
    host: str = "127.0.0.1"
    port: int = 8765
    # Comma-separated origins; "*" allows all (dev-friendly for Tauri/WebView).
    cors_origins: str = "*"
    max_upload_bytes: int = 20 * 1024 * 1024  # 20 MiB
    # mock | paddleocr (paddleocr wired in issue #3)
    recognize_engine: str = "mock"

    @property
    def cors_origin_list(self) -> list[str]:
        raw = self.cors_origins.strip()
        if raw == "*":
            return ["*"]
        return [part.strip() for part in raw.split(",") if part.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

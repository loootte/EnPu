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
    app_version: str = "0.0.2"
    host: str = "127.0.0.1"
    port: int = 8765
    # Comma-separated origins; "*" allows all (dev-friendly for Tauri/WebView).
    cors_origins: str = "*"
    max_upload_bytes: int = 20 * 1024 * 1024  # 20 MiB
    # mock | paddleocr
    recognize_engine: str = "paddleocr"

    # OCR / preprocess
    ocr_lang: str = "ch"
    ocr_use_angle_cls: bool = True
    ocr_use_gpu: bool = False
    ocr_max_side: int = 2000
    ocr_denoise: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        raw = self.cors_origins.strip()
        if raw == "*":
            return ["*"]
        return [part.strip() for part in raw.split(",") if part.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    """Drop cached settings (tests)."""
    get_settings.cache_clear()

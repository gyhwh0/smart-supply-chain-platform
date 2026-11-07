from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./procurement.db"
    JWT_SECRET_KEY: str = "development-only-change-me-at-least-32-bytes"
    JWT_EXPIRE_HOURS: int = 24
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "agnes-3.0-flash"
    LLM_BASE_URL: str = "https://apihub.agnes-ai.com/v1"
    INVENTORY_LLM_API_KEY: str = ""
    INVENTORY_LLM_MODEL: str = "deepseek-chat"
    INVENTORY_LLM_BASE_URL: str = "https://api.deepseek.com"
    WECOM_CORP_ID: str = ""
    WECOM_KF_SECRET: str = ""
    WECOM_CALLBACK_TOKEN: str = ""
    WECOM_ENCODING_AES_KEY: str = ""
    VOICE_API_KEY: str = ""
    VOICE_MODEL: str = "whisper-1"
    VOICE_BASE_URL: str = "https://api.openai.com/v1"
    MINI_PROGRAM_APP_ID: str = ""
    MINI_PROGRAM_APP_SECRET: str = ""
    SKIP_LOGIN: bool = True

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()

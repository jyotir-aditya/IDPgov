"""Configuration loaded from .env via pydantic-settings."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    GEMINI_API_KEY: str = ""
    DRIVE_FOLDER_ID: str = ""
    SHEET_ID: str = ""
    API_TOKEN: str = ""
    GOOGLE_SERVICE_ACCOUNT_FILE: str = "service_account.json"
    AI_PROVIDER: str = "gemini"

    # Register sheet columns (in order). SL No. is auto-generated.
    SL_NO_PREFIX: str = "BEP/UP"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
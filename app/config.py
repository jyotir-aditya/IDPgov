"""Configuration loaded from .env via pydantic-settings."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    GEMINI_API_KEY: str = ""
    SHEET_ID: str = ""
    API_TOKEN: str = ""
    GOOGLE_SERVICE_ACCOUNT_FILE: str = "service_account.json"
    AI_PROVIDER: str = "gemini"

    # Cloudflare R2 (S3-compatible) — PDF storage. Bucket must have public
    # read access enabled; R2_PUBLIC_BASE_URL is the pub-*.r2.dev URL or
    # custom domain shown in the bucket's "Public access" settings.
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = ""
    R2_PUBLIC_BASE_URL: str = ""

    # Register sheet columns (in order). SL No. is auto-generated.
    SL_NO_PREFIX: str = "BEP/UP"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
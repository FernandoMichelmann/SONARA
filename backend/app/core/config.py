from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    app_name: str = "SONARA API"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./sonara.db"
    jwt_secret_key: str = "CHANGE_THIS_SECRET_BEFORE_DEPLOYMENT_32_CHARS_MIN"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    cors_origins: str = "http://127.0.0.1:5500,http://localhost:5500"
    developer_email: str | None = None
    developer_password: str | None = None
    developer_name: str = "SONARA Owner"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_from_name: str = "SONARA"
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    frontend_base_url: str = "http://127.0.0.1:5500"

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = (
        "postgresql+psycopg2://merchant_user:merchant_pass@postgres:5432/merchant_portal"
    )
    jwt_access_secret: str = "dev-access-secret-change-in-production"
    jwt_refresh_secret: str = "dev-refresh-secret-change-in-production"
    jwt_access_expires_minutes: int = 15
    jwt_refresh_expires_days: int = 7
    cors_origins: str = "http://localhost:4200"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8-sig",
        extra="ignore",
    )


settings = Settings()
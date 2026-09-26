from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Later files win: repo-root .env (shared creds), then apps/api/.env.
    model_config = SettingsConfigDict(env_file=("../../.env", ".env"), extra="ignore")

    database_url: str = "postgresql+psycopg://app:app@localhost:5432/app"
    cors_origins: list[str] = ["http://localhost:3000"]

    # ERCOT Public API (https://developer.ercot.com). Keys alone are not enough:
    # the API also needs an id_token obtained with the account username/password.
    ercot_username: str | None = None
    ercot_password: str | None = None
    ercot_primary_key: str | None = None
    ercot_secondary_key: str | None = None


settings = Settings()

from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./wall.db"
    secret_key: str = "development-only-change-before-deployment-0123456789"
    admin_token: str = ""
    environment: str = "development"
    render: bool = False
    # Vercel sets VERCEL=1 automatically, so this needs no configuration.
    vercel: bool = False
    trust_proxy: bool = False
    # Cold-start schema initialization; disabled automatically on Vercel,
    # where scripts/init_db.py performs the one-time controlled setup.
    db_init_on_startup: bool = True
    report_threshold: int = Field(default=3, ge=1, le=100)
    categories: list[str] = ["General", "Study", "Campus", "Technology"]
    optional_google_font: bool = False
    secure_cookies: bool = False

    @model_validator(mode="after")
    def validate_settings(self):
        url = self.database_url
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                url = "postgresql+psycopg://" + url[len(prefix):]
                break
        if url.startswith("postgresql+psycopg://"):
            parts = urlsplit(url)
            query = dict(parse_qsl(parts.query, keep_blank_values=True))
            query["sslmode"] = "require"
            url = urlunsplit(parts._replace(query=urlencode(query)))
        self.database_url = url
        production = self.render or self.vercel or self.environment == "production"
        if not self.categories or any(not c.strip() or len(c) > 80 for c in self.categories):
            raise ValueError("CATEGORIES must contain category names of 1 to 80 characters")
        if production:
            if not url.startswith("postgresql+psycopg://"):
                raise ValueError("Production requires PostgreSQL, never SQLite")
            if len(self.secret_key) < 32 or self.secret_key.startswith("development-"):
                raise ValueError("Production requires a random SECRET_KEY of 32+ characters")
            if len(self.admin_token) < 32:
                raise ValueError("Production requires a random ADMIN_TOKEN of 32+ characters")
            self.secure_cookies = True
        return self


@lru_cache
def get_settings():
    return Settings()


settings = get_settings()

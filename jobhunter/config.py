"""Configuration from environment (.env). Read once at startup by the interfaces."""
import json
import os
from dataclasses import dataclass, field

from .domain.pricing import DEFAULT_PRICES


def _bool(name, default):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Config:
    database_url: str
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""
    storage_bucket: str = "applications"
    allowed_user_email: str = ""
    openai_api_key: str = ""
    openai_fast_model: str = "gpt-5-mini"
    openai_strong_model: str = "gpt-5"
    openai_embed_model: str = "text-embedding-3-small"
    prices: dict = field(default_factory=lambda: dict(DEFAULT_PRICES))
    hunter_api_key: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/gmail/callback"
    web_origins: tuple = ("http://localhost:3000",)
    scheduler_enabled: bool = True
    desktop_notifications: bool = True

    @property
    def web_origin(self):
        return self.web_origins[0].rstrip("/")

    @classmethod
    def from_env(cls):
        from dotenv import load_dotenv
        load_dotenv()
        if not os.getenv("DATABASE_URL"):
            raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
        prices = dict(DEFAULT_PRICES)
        if os.getenv("OPENAI_PRICES"):
            prices.update({k: tuple(v) for k, v in json.loads(os.environ["OPENAI_PRICES"]).items()})
        env = os.getenv
        return cls(
            database_url=env("DATABASE_URL"),
            supabase_url=env("SUPABASE_URL", ""),
            supabase_service_role_key=env("SUPABASE_SERVICE_ROLE_KEY", ""),
            supabase_jwt_secret=env("SUPABASE_JWT_SECRET", ""),
            storage_bucket=env("STORAGE_BUCKET", "applications"),
            allowed_user_email=env("ALLOWED_USER_EMAIL", "").strip().lower(),
            openai_api_key=env("OPENAI_API_KEY", ""),
            openai_fast_model=env("OPENAI_FAST_MODEL", "gpt-5-mini"),
            openai_strong_model=env("OPENAI_STRONG_MODEL", "gpt-5"),
            openai_embed_model=env("OPENAI_EMBED_MODEL", "text-embedding-3-small"),
            prices=prices,
            hunter_api_key=env("HUNTER_API_KEY", ""),
            google_client_id=env("GOOGLE_CLIENT_ID", ""),
            google_client_secret=env("GOOGLE_CLIENT_SECRET", ""),
            google_redirect_uri=env("GOOGLE_REDIRECT_URI", "http://localhost:8000/gmail/callback"),
            web_origins=tuple(o.strip() for o in env("WEB_ORIGIN", "http://localhost:3000").split(",") if o.strip()),
            scheduler_enabled=_bool("SCHEDULER_ENABLED", True),
            desktop_notifications=_bool("DESKTOP_NOTIFICATIONS", True),
        )

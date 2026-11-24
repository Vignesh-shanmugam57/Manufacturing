from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent
DATA_DIR = BACKEND_DIR / "data"
FRONTEND_DIST = PROJECT_DIR / "frontend" / "dist"


def postgres_driver() -> str:
    """psycopg (native libpq) when it loads; otherwise pure-Python pg8000.

    On Windows with Smart App Control, psycopg's unsigned libpq DLL can be blocked
    ("An Application Control policy has blocked this file"); pg8000 has no native code.
    """
    try:
        import psycopg  # noqa: F401
        return "psycopg"
    except ImportError:
        return "pg8000"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Utilities Management Agent"

    # Domo AI Services
    domo_base_url: str = "https://gwcteq-partner.domo.com"
    domo_developer_token: str = ""
    model_name: str | None = None
    domo_structured_output: bool = True

    # LLM behaviour
    llm_temperature: float = 0.0
    llm_max_tokens: int = 2000
    llm_timeout_seconds: float = 120.0

    # Database. Production: Neon PostgreSQL, e.g.
    #   postgresql://user:pass@ep-xxx-pooler.region.aws.neon.tech/utilities?sslmode=require
    # Without DATABASE_URL a local SQLite file is used (development only).
    database_url: str = f"sqlite:///{(DATA_DIR / 'utilities.db').as_posix()}"
    readonly_database_url: str | None = None   # optional read-only role for the run_sql tool

    # Agent / app
    site_name: str = "Plant 01"
    agent_max_steps: int = 6
    cors_origins: str = "http://localhost:5173"
    max_upload_mb: int = 100        # largest CSV accepted by the upload endpoint
    serve_frontend: bool = True     # serve frontend/dist at / when it has been built
    twin_autostart: bool = True     # run the digital-twin telemetry engine with the server (tests switch it off)
    connectors_autorun: bool = True            # pull from connected systems on their schedule (tests switch it off)
    connector_secret_key: str = ""             # Fernet key that encrypts connector passwords; generated into data/connector.key if empty
    connector_allowed_hosts: str = ""          # optional comma separated allow-list of hosts REST and CSV connectors may call

    @field_validator("database_url", "readonly_database_url")
    @classmethod
    def _pick_driver(cls, v: str | None) -> str | None:
        """Accept Neon's postgres:// / postgresql:// strings and pick a driver.
        An explicit postgresql+psycopg:// or postgresql+pg8000:// URL is used as given."""
        if v and v.startswith(("postgres://", "postgresql://")):
            return f"postgresql+{postgres_driver()}://" + v.split("://", 1)[1]
        return v

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")


settings = Settings()

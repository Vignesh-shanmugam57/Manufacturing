import ssl

from app.core.config import Settings
from app.db.session import pg_connect_options

NEON = ("postgresql://neondb_owner:secret@ep-cool-name-a1b2c3-pooler.eu-central-1.aws.neon.tech/utilities"
        "?sslmode=require&channel_binding=require")


def test_neon_url_gets_a_driver():
    url = Settings(database_url=NEON, _env_file=None).database_url
    assert url.startswith(("postgresql+psycopg://", "postgresql+pg8000://"))
    assert Settings(database_url="postgres://u:p@h/db", _env_file=None).database_url.startswith("postgresql+")


def test_pg8000_neon_options_verify_tls_and_drop_libpq_params():
    u, args = pg_connect_options(NEON.replace("postgresql://", "postgresql+pg8000://"))
    assert u.database == "utilities" and dict(u.query) == {}
    ctx = args["ssl_context"]
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname  # Neon: full verification


def test_pg8000_sslmode_require_elsewhere_encrypts_without_verifying():
    u, args = pg_connect_options("postgresql+pg8000://u:p@db.internal:5432/utilities?sslmode=require")
    assert args["ssl_context"].verify_mode == ssl.CERT_NONE
    assert pg_connect_options("postgresql+pg8000://u:p@localhost/utilities")[1] == {}


def test_psycopg_disables_server_side_prepares_for_pgbouncer():
    _, args = pg_connect_options(NEON.replace("postgresql://", "postgresql+psycopg://"))
    assert args == {"prepare_threshold": None}

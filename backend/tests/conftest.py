"""Test setup: isolated database, no Domo calls.

By default tests use a temporary SQLite file. To run them against PostgreSQL set TEST_DATABASE_URL to a
dedicated database whose name contains "test" (tables are dropped and recreated!), e.g.
  TEST_DATABASE_URL=postgresql://agent:agentpass@localhost:55432/utilities_test
Data comes from tests/factory.py: synthetic CSV files in the real format with known planted patterns.
"""
import os
import tempfile
from pathlib import Path

_test_url = os.environ.get("TEST_DATABASE_URL")
if _test_url and "test" not in _test_url.rsplit("/", 1)[-1].split("?")[0]:
    raise RuntimeError("TEST_DATABASE_URL must point to a database whose name contains 'test'.")
_tmp = Path(tempfile.mkdtemp(prefix="utilities_agent_test_"))
os.environ["DATABASE_URL"] = _test_url or f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ.pop("READONLY_DATABASE_URL", None)
os.environ["DOMO_DEVELOPER_TOKEN"] = ""      # never call the real API from tests
os.environ["SERVE_FRONTEND"] = "false"
os.environ["TWIN_AUTOSTART"] = "false"      # tests step the telemetry engine by hand
os.environ["CONNECTORS_AUTORUN"] = "false"  # tests pull by hand
from cryptography.fernet import Fernet  # noqa: E402
os.environ["CONNECTOR_SECRET_KEY"] = Fernet.generate_key().decode()

import pytest  # noqa: E402

from app.db.session import SessionLocal, engine  # noqa: E402
from app.models import Base  # noqa: E402
from app.services import ingest  # noqa: E402

from tests.factory import make_csvs  # noqa: E402


def load_all(mode: str = "replace") -> None:
    with SessionLocal() as s:
        for key, data in make_csvs().items():
            ingest.ingest_csv(s, data, ingest.DATASETS[key].file_name, mode=mode)


@pytest.fixture(scope="session", autouse=True)
def loaded_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    load_all()
    yield
    engine.dispose()


@pytest.fixture
def session():
    with SessionLocal() as s:
        yield s

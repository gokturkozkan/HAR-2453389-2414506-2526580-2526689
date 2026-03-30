from pathlib import Path
import sys

import pytest


TESTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TESTS_DIR.parent

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import database
from app import app
from routes import activity


@pytest.fixture(autouse=True)
def reset_activity_windows():
    activity.LATEST_WINDOWS_BY_NODE.clear()
    activity.LAST_NODE_ID = None
    yield
    activity.LATEST_WINDOWS_BY_NODE.clear()
    activity.LAST_NODE_ID = None


@pytest.fixture
def backend_db(tmp_path):
    original_db_path = database.db_path
    db_file = tmp_path / "test.db"

    database.close_database()
    database.db_path = str(db_file)
    database.init_database()

    try:
        yield db_file
    finally:
        database.close_database()
        database.db_path = original_db_path


@pytest.fixture
def client(backend_db):
    return app.test_client()

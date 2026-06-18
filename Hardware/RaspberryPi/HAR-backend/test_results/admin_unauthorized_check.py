import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import database
from app import app


def main():
    old_db_path = database.db_path
    db_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    db_file.close()

    try:
        database.close_database()
        database.db_path = db_file.name
        database.init_database()

        client = app.test_client()
        response = client.get("/admin/users.json")

        print("Request: GET /admin/users.json")
        print("ADMIN_TOKEN configured: yes")
        print("x-admin-token header: <missing>")
        print("Actual status:", response.status_code)
        print("Response body:", response.get_data(as_text=True) or "<empty>")

        return 0 if response.status_code == 401 else 1
    finally:
        database.close_database()
        database.db_path = old_db_path
        if os.path.exists(db_file.name):
            os.remove(db_file.name)


if __name__ == "__main__":
    raise SystemExit(main())

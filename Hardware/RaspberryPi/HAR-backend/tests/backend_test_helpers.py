import database
from routes import activity


def build_window(size=32, offset=0.0):
    return [
        {
            "ax": offset + 0.1 + i * 0.01,
            "ay": offset + 0.2 + i * 0.01,
            "az": 9.7 + offset,
            "gx": 0.01 + offset,
            "gy": 0.02 + offset,
            "gz": 0.03 + offset,
        }
        for i in range(size)
    ]


def seed_test_images(*names):
    fake_png = b"\x89PNG\r\n\x1a\nTEST"
    database.db_run(
        "CREATE TABLE IF NOT EXISTS unity_images (name TEXT PRIMARY KEY, data BLOB NOT NULL)"
    )
    for name in names:
        database.db_run(
            "INSERT OR REPLACE INTO unity_images (name, data) VALUES (?, ?)",
            [name, fake_png],
        )


def reset_activity_state():
    activity.LATEST_WINDOWS_BY_NODE.clear()
    activity.LAST_NODE_ID = None

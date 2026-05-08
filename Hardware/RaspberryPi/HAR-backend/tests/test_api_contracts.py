import os
import tempfile
import unittest
from uuid import uuid4

import database
from app import app


class ApiContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.tmp.close()
        database.close_database()
        database.db_path = self.tmp.name
        database.init_database()
        self.client = app.test_client()

    def tearDown(self):
        database.close_database()
        if os.path.exists(self.tmp.name):
            os.remove(self.tmp.name)

    def test_register_login_and_profile_update_flow(self):
        username = f"har-test-{uuid4().hex[:8]}@example.com"
        password = "StrongPass123"

        register_res = self.client.post(
            "/register",
            json={"credentials": {"username": username, "password": password}},
        )
        self.assertEqual(register_res.status_code, 201)
        user = register_res.get_json()["user"]
        self.assertEqual(user["username"], username)

        login_res = self.client.post(
            "/login",
            json={"credentials": {"username": username, "password": password}},
        )
        self.assertEqual(login_res.status_code, 200)
        self.assertEqual(login_res.get_json()["user"]["id"], user["id"])

        next_username = f"har-updated-{uuid4().hex[:8]}@example.com"
        update_res = self.client.post(
            "/user/update",
            json={
                "userId": user["id"],
                "credentials": {"username": next_username},
            },
        )
        self.assertEqual(update_res.status_code, 200)
        self.assertEqual(update_res.get_json()["user"]["username"], next_username)

    def test_register_rejects_duplicate_username(self):
        username = f"duplicate-{uuid4().hex[:8]}@example.com"
        payload = {"credentials": {"username": username, "password": "pass12345"}}

        first_res = self.client.post("/register", json=payload)
        second_res = self.client.post("/register", json=payload)

        self.assertEqual(first_res.status_code, 201)
        self.assertEqual(second_res.status_code, 409)
        self.assertEqual(second_res.get_json()["message"], "User already exists")

    def test_esp_init_update_and_status_flow(self):
        init_res = self.client.post("/esp-devices/init", json={"count": 3})
        self.assertEqual(init_res.status_code, 200)

        list_res = self.client.get("/esp")
        self.assertEqual(list_res.status_code, 200)
        self.assertEqual(list_res.get_json(), [{"id": 1}, {"id": 2}, {"id": 3}])

        update_res = self.client.post("/esp-status/2", json={"isConnected": True})
        self.assertEqual(update_res.status_code, 200)

        status_res = self.client.get("/esp-status?id=2")
        self.assertEqual(status_res.status_code, 200)
        self.assertEqual(status_res.get_json(), {"id": 2, "isConnected": True})

        invalid_res = self.client.get("/esp-status?id=abc")
        self.assertEqual(invalid_res.status_code, 400)


if __name__ == "__main__":
    unittest.main()

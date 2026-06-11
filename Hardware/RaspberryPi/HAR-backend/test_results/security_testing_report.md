# Security Testing Evidence

## 6.7 Security Testing

This section presents basic security-related checks completed for the HAR backend. These tests are
not penetration tests; they verify authentication, password storage, duplicate-account handling, and
admin-route protection.

### 6.7.1 Test Procedure

1. A temporary SQLite database was initialized.
2. User registration was tested with valid and invalid credentials.
3. Stored password values were inspected to confirm they were not plaintext.
4. Login was tested with correct and incorrect passwords.
5. Duplicate registration was tested.
6. Admin JSON route access was tested with and without an admin token.

Command used:

```bash
cd /home/serene/3005/HAR-2453389-2414506-2526580-2526689-server-fixing/Hardware/RaspberryPi/HAR-backend
.venv/bin/python -m pytest tests/test_backend_unit.py
```

### 6.7.2 Test Cases

| ID | Description | Steps | Test Data | Pre-condition | Expected Output | Passed/Failed |
|---|---|---|---|---|---|---|
| SCT-01 | Password is not stored as plaintext | Register user and inspect database password field | Username `alice`, password `secret123` | Temporary database initialized | Stored password differs from plaintext password | Passed |
| SCT-02 | Duplicate user prevention | Register same username twice | Username `alice` | First registration completed | Second registration returns conflict | Passed |
| SCT-03 | Wrong password rejection | Login with incorrect password | Username `alice`, wrong password `bad` | User exists | Login returns unauthorized | Passed |
| SCT-04 | Correct password acceptance | Login with correct password | Username `alice`, password `secret123` | User exists | Login succeeds | Passed |
| SCT-05 | Admin route protection | Configure `ADMIN_TOKEN`; call admin route with and without token | Header `x-admin-token` | Admin token configured | Missing token rejected; correct token accepted | Passed |

### 6.7.3 Test Results

| Security Area | Result | Remarks |
|---|---|---|
| Password storage | Passed | Stored password is hashed and not equal to plaintext input. |
| Duplicate account handling | Passed | Duplicate username registration is rejected. |
| Login validation | Passed | Incorrect password is rejected and correct password is accepted. |
| Admin route protection | Passed | Admin JSON route requires the configured token. |

### 6.7.4 Test Log

- Security-related backend tests were executed as part of the unit test suite.
- Password hashing behavior was verified through database inspection.
- Duplicate usernames were rejected.
- Wrong-password login attempts were rejected.
- Admin route access was blocked without the configured token.

### Figures / Screenshot Evidence to Add

| Figure | Screenshot | What it proves |
|---|---|---|
| Figure SCT-1 | Terminal after running `tests/test_backend_unit.py` | Shows auth/security unit tests passed. |
| Figure SCT-2 | IDE screenshot of auth tests in `tests/test_backend_unit.py` | Shows implemented security checks. |
| Figure SCT-3 | Optional admin route unauthorized response screenshot | Shows admin token protection. |


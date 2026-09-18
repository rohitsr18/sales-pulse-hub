import requests

from config.settings import EMPLOYEE_API_BASE_URL, EMPLOYEE_API_KEY

_HEADERS = {
    "X-API-Key": EMPLOYEE_API_KEY,
    "Content-Type": "application/json",
    "Accept": "application/json",
}

_FIELDS = ("employee_no", "name", "email_id", "phone_no")


def _to_employee(payload: dict) -> dict:
    return {field: payload.get(field, "") for field in _FIELDS}


def authenticate_employee(employee_id: str, password: str) -> dict | None:
    """Password verification happens server-side; credentials are never stored locally."""
    try:
        resp = requests.post(
            f"{EMPLOYEE_API_BASE_URL}/api/v1/employees/authenticate",
            json={"employee_no": employee_id, "password": password},
            headers=_HEADERS,
            timeout=10,
        )
    except requests.RequestException as exc:
        print(f"Employee API error: {exc}")
        return None

    if resp.status_code == 200:
        return _to_employee(resp.json())
    return None


def get_employee(employee_id: str) -> dict | None:
    try:
        resp = requests.get(
            f"{EMPLOYEE_API_BASE_URL}/api/v1/employees/{employee_id}",
            headers=_HEADERS,
            timeout=10,
        )
    except requests.RequestException as exc:
        print(f"Employee API error: {exc}")
        return None

    if resp.status_code == 200:
        return _to_employee(resp.json())
    return None

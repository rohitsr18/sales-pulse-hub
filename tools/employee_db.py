from database.db_client import get_employee


def fetch_employee_for_session(employee_id: str) -> dict | None:
    """Internal helper for the session layer. Deliberately not exposed as an agent tool."""
    return get_employee(employee_id)

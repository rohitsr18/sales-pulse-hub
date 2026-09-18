import getpass
import os
import time
from dataclasses import dataclass, field

from auth.pii_guard import PIIGuard
from config.settings import SESSION_TIMEOUT_MINUTES
from database.db_client import authenticate_employee

_SESSION_TIMEOUT = SESSION_TIMEOUT_MINUTES * 60

_BANNER = (
    "  ┌──────────────────────────────────────────────┐\n"
    "  │          HR Agent  ·  Secure Login           │\n"
    "  └──────────────────────────────────────────────┘"
)


@dataclass
class Session:
    employee_no: str
    pii: PIIGuard
    _last_active: float = field(default_factory=time.time)

    def is_expired(self) -> bool:
        return (time.time() - self._last_active) > _SESSION_TIMEOUT

    def refresh(self) -> None:
        self._last_active = time.time()


_current_session: Session | None = None


def _clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _prompt_credentials(error: str | None = None) -> tuple[str, str]:
    _clear()
    print(f"\n{_BANNER}\n")
    if error:
        print(f"  {error}\n")
    print("  Credentials are used only to verify your identity.")
    print("  They are never stored, logged, or sent to the AI model.\n")
    employee_id = input("    Employee ID : ").strip()
    password = getpass.getpass("    Password    : ")
    return employee_id, password


def login() -> Session:
    global _current_session

    error: str | None = None
    while True:
        employee_id, password = _prompt_credentials(error)
        try:
            employee = authenticate_employee(employee_id, password)
        finally:
            del password

        if employee:
            break
        error = "Invalid credentials. Please try again."

    guard = PIIGuard()
    for field_name in ("employee_no", "name", "email_id", "phone_no"):
        guard.store(field_name, employee[field_name])

    _current_session = Session(employee_no=employee["employee_no"], pii=guard)

    _clear()
    print(f"\n  Login successful. Session expires after "
          f"{SESSION_TIMEOUT_MINUTES} minutes of inactivity.\n")
    return _current_session


def get_session() -> Session | None:
    global _current_session
    if _current_session and not _current_session.is_expired():
        _current_session.refresh()
        return _current_session
    _current_session = None
    return None


def require_session() -> Session:
    session = get_session()
    if session:
        return session
    print("\n  Session expired.")
    return login()

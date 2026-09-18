import requests
from langchain_core.tools import tool

from config.settings import SN_INSTANCE, SN_PASS, SN_USER


@tool
def raise_servicenow_incident(issue_summary: str) -> str:
    """Raise a ServiceNow HR incident for the logged-in employee using their issue summary."""
    from auth.session_manager import require_session

    session = require_session()
    # Decrypted here only; these values never enter the LLM context.
    emp = session.pii.get_all_decrypted()

    print("\n── Ticket Preview ────────────────────────────────────")
    print(f"  Employee No : {emp['employee_no']}")
    print(f"  Name        : {emp['name']}")
    print(f"  Email       : {emp['email_id']}")
    print(f"  Phone       : {emp['phone_no']}")
    print(f"  Issue       : {issue_summary}")
    print("──────────────────────────────────────────────────────")

    if input("Submit this ticket? (yes/no): ").strip().lower() not in ("yes", "y"):
        return "Ticket submission cancelled by the employee."

    payload = {
        "short_description": f"HR Query - {issue_summary[:100]}",
        "description": (
            f"Employee No: {emp['employee_no']}\n"
            f"Name: {emp['name']}\n"
            f"Email: {emp['email_id']}\n"
            f"Phone: {emp['phone_no']}\n\n"
            f"Issue: {issue_summary}"
        ),
        "category": "HR",
        "urgency": "3",
        "impact": "3",
    }

    try:
        resp = requests.post(
            f"{SN_INSTANCE}/api/now/table/incident",
            json=payload,
            auth=(SN_USER, SN_PASS),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=15,
        )
    except requests.RequestException as exc:
        return f"Could not reach ServiceNow: {exc}"

    if resp.status_code == 201:
        return f"Ticket raised. Incident number: {resp.json()['result']['number']}"
    return f"Failed to raise ticket. ServiceNow returned HTTP {resp.status_code}."

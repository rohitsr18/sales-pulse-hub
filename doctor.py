"""
doctor.py — SalesPulse Hub self-check.

Reports Python version, required packages, free ports, LLM reachability,
and bundle version. Run before starting the system:

    python3 doctor.py
"""

from __future__ import annotations

import sys
import socket
import importlib
import urllib.request
import os
from pathlib import Path

_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_RESET = "\033[0m"
_BOLD = "\033[1m"

def ok(msg: str)   -> None: print(f"  {_GREEN}✓{_RESET}  {msg}")
def warn(msg: str) -> None: print(f"  {_YELLOW}⚠{_RESET}  {msg}")
def fail(msg: str) -> None: print(f"  {_RED}✗{_RESET}  {msg}")

def check_python() -> bool:
    v = sys.version_info
    if v >= (3, 11):
        ok(f"Python {v.major}.{v.minor}.{v.micro}")
        return True
    fail(f"Python {v.major}.{v.minor} — need ≥ 3.11")
    return False

def check_packages() -> bool:
    required = [
        "fastapi", "uvicorn", "sse_starlette",
        "httpx", "openai", "dotenv", "pydantic",
    ]
    all_ok = True
    for pkg in required:
        mod = "dotenv" if pkg == "dotenv" else pkg
        try:
            importlib.import_module(mod)
            ok(f"  {pkg}")
        except ImportError:
            fail(f"  {pkg} — not installed (run: pip3 install -e starter/[dev])")
            all_ok = False
    return all_ok

def check_ports() -> bool:
    ports = {
        7000: "Control Plane", 7001: "CRM", 7002: "Voice",
        7003: "Quotes",        7004: "Market", 7005: "Supply",
        3000: "Hub",
    }
    all_free = True
    for port, name in ports.items():
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        try:
            s.connect(("localhost", port))
            warn(f"  :{port} {name} — already in use (run: lsof -ti:{port} | xargs kill -9)")
            all_free = False
        except (ConnectionRefusedError, TimeoutError):
            ok(f"  :{port} {name} — free")
        finally:
            s.close()
    return all_free

def check_env() -> dict[str, str]:
    env_path = Path(__file__).parent / "starter" / ".env"
    if not env_path.exists():
        warn(".env not found — run: cp starter/.env.example starter/.env")
        return {}
    from dotenv import dotenv_values  # type: ignore[import]
    vals = dotenv_values(env_path)
    key = vals.get("LLM_API_KEY", "")
    url = vals.get("LLM_BASE_URL", "")
    model = vals.get("LLM_MODEL", "")
    ok(f"LLM_BASE_URL  = {url}")
    ok(f"LLM_MODEL     = {model}")
    if key and key not in ("sk-...", "gsk_..."):
        ok(f"LLM_API_KEY   = {key[:8]}... (set)")
    else:
        warn("LLM_API_KEY not set — will run in demo mode")
    return vals

def check_llm(vals: dict[str, str]) -> bool:
    key = vals.get("LLM_API_KEY", "")
    url = vals.get("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    if not key or key in ("sk-...", "gsk_..."):
        warn("Skipping LLM reachability — no API key configured")
        return False
    try:
        import httpx  # type: ignore[import]
        with httpx.Client(verify=False, timeout=8) as c:
            r = c.get(f"{url}/models", headers={"Authorization": f"Bearer {key}"})
        if r.status_code == 200:
            ok(f"LLM gateway reachable ({url}), HTTP 200")
            return True
        elif r.status_code in (401, 403):
            warn(f"LLM gateway responded HTTP {r.status_code} — check key / network proxy")
        else:
            warn(f"LLM gateway HTTP {r.status_code}")
    except Exception as e:
        warn(f"LLM gateway unreachable — {type(e).__name__}: {str(e)[:60]}")
        warn("  If on corporate network: Zscaler may be blocking api.groq.com")
        warn("  Workaround: use mobile hotspot or ask IT to whitelist api.groq.com")
    return False

def check_bundles() -> None:
    for toml in [Path("sim/pyproject.toml"), Path("starter/pyproject.toml")]:
        if toml.exists():
            for line in toml.read_text().splitlines():
                if line.strip().startswith("version"):
                    v = line.split("=")[1].strip().strip('"')
                    ok(f"{toml.parent.name} version = {v}")
                    break

def main() -> None:
    print(f"\n{_BOLD}SalesPulse Hub — System Doctor{_RESET}\n")

    print("Python:")
    py_ok = check_python()

    print("\nPackages:")
    pkg_ok = check_packages()

    print("\nPorts (must be free before starting):")
    ports_ok = check_ports()

    print("\nEnvironment (.env):")
    vals = check_env()

    print("\nLLM gateway:")
    check_llm(vals)

    print("\nBundle versions:")
    check_bundles()

    print()
    if py_ok and pkg_ok:
        print(f"{_GREEN}{_BOLD}Ready.{_RESET} Start with:")
        print("  cd sim   && python3 server.py --instant &")
        print("  cd starter && python3 server.py")
        print("  open http://localhost:3000")
    else:
        print(f"{_RED}{_BOLD}Issues found — fix the items above before starting.{_RESET}")
    print()

if __name__ == "__main__":
    main()

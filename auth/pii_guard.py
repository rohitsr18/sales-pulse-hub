from cryptography.fernet import Fernet


class PIIGuard:
    """Holds employee PII encrypted in memory with a per-session key."""

    def __init__(self):
        self._fernet = Fernet(Fernet.generate_key())
        self._store: dict[str, bytes] = {}

    def store(self, field: str, value: str) -> None:
        self._store[field] = self._fernet.encrypt(value.encode())

    def retrieve(self, field: str) -> str:
        return self._fernet.decrypt(self._store[field]).decode()

    def get_all_decrypted(self) -> dict[str, str]:
        """Call only inside tools that submit to external systems. Never pass to an LLM."""
        return {field: self.retrieve(field) for field in self._store}

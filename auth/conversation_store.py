import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any

from cryptography.fernet import Fernet
from langgraph.checkpoint.serde.base import SerializerProtocol
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver

from config.settings import CONVERSATION_DB_FILE, CONVERSATION_ENCRYPTION_KEY

_TITLE_MAX_CHARS = 60


class EncryptedSerializer(SerializerProtocol):
    """Encrypts every checkpoint payload with Fernet before it reaches disk."""

    def __init__(self, key: str | bytes):
        self._fernet = Fernet(key if isinstance(key, bytes) else key.encode())
        self._inner = JsonPlusSerializer()

    def dumps_typed(self, obj: Any) -> tuple[str, bytes]:
        type_name, payload = self._inner.dumps_typed(obj)
        return type_name, self._fernet.encrypt(payload)

    def loads_typed(self, data: tuple[str, bytes]) -> Any:
        type_name, payload = data
        return self._inner.loads_typed((type_name, self._fernet.decrypt(payload)))


def _require_key() -> str:
    if not CONVERSATION_ENCRYPTION_KEY:
        raise RuntimeError(
            "CONVERSATION_ENCRYPTION_KEY is not set. Generate one with:\n"
            "  python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"\n"
            "then add it to your .env file."
        )
    return CONVERSATION_ENCRYPTION_KEY


def connect_conversation_db() -> sqlite3.Connection:
    is_new = not os.path.exists(CONVERSATION_DB_FILE)
    conn = sqlite3.connect(CONVERSATION_DB_FILE, check_same_thread=False)
    if is_new:
        os.chmod(CONVERSATION_DB_FILE, 0o600)
    return conn


def build_checkpointer(conn: sqlite3.Connection | None = None) -> SqliteSaver:
    return SqliteSaver(
        conn or connect_conversation_db(),
        serde=EncryptedSerializer(_require_key()),
    )


@dataclass
class ChatRef:
    chat_id: str
    title: str
    updated_at: float


class ChatRegistry:
    """Tracks an employee's saved chats; titles are encrypted since they quote the user."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._fernet = Fernet(_require_key().encode())
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chats (
                chat_id     TEXT PRIMARY KEY,
                employee_no TEXT NOT NULL,
                title       BLOB,
                created_at  REAL NOT NULL,
                updated_at  REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chats_employee ON chats(employee_no, updated_at DESC)"
        )
        self._conn.commit()

    def create(self, employee_no: str) -> str:
        chat_id = f"{employee_no}:{uuid.uuid4()}"
        now = time.time()
        self._conn.execute(
            "INSERT INTO chats (chat_id, employee_no, title, created_at, updated_at)"
            " VALUES (?, ?, NULL, ?, ?)",
            (chat_id, employee_no, now, now),
        )
        self._conn.commit()
        return chat_id

    def touch(self, chat_id: str, first_message: str | None = None) -> None:
        if first_message:
            title = first_message.strip()[:_TITLE_MAX_CHARS]
            self._conn.execute(
                "UPDATE chats SET updated_at = ?, title = COALESCE(title, ?) WHERE chat_id = ?",
                (time.time(), self._fernet.encrypt(title.encode()), chat_id),
            )
        else:
            self._conn.execute(
                "UPDATE chats SET updated_at = ? WHERE chat_id = ?", (time.time(), chat_id)
            )
        self._conn.commit()

    def list(self, employee_no: str) -> list[ChatRef]:
        rows = self._conn.execute(
            "SELECT chat_id, title, updated_at FROM chats"
            " WHERE employee_no = ? ORDER BY updated_at DESC",
            (employee_no,),
        ).fetchall()
        return [
            ChatRef(
                chat_id=chat_id,
                title=self._fernet.decrypt(title).decode() if title else "(empty chat)",
                updated_at=updated_at,
            )
            for chat_id, title, updated_at in rows
        ]

    def delete(self, chat_id: str, employee_no: str, checkpointer: SqliteSaver) -> bool:
        owned = self._conn.execute(
            "SELECT 1 FROM chats WHERE chat_id = ? AND employee_no = ?",
            (chat_id, employee_no),
        ).fetchone()
        if not owned:
            return False

        checkpointer.delete_thread(chat_id)
        self._conn.execute("DELETE FROM chats WHERE chat_id = ?", (chat_id,))
        self._conn.commit()
        return True

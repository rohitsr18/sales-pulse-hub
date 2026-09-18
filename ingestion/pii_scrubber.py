import re

from langchain_core.documents import Document

# Masked (not encrypted) so the text stays semantically searchable.
_PII_PATTERNS: dict[str, str] = {
    "EMAIL": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "SSN": r"\b\d{3}-\d{2}-\d{4}\b",
    "AADHAAR": r"\b\d{4}\s\d{4}\s\d{4}\b",
    "PAN": r"\b[A-Z]{5}\d{4}[A-Z]\b",
    "EMPLOYEE_ID": r"\bEMP\d{3,8}\b",
}

# Broad candidate match; _mask_phone rejects digit runs outside real phone length.
_PHONE_CANDIDATE = re.compile(r"\(?\+?\d[\d\s().-]{7,18}\d")
_MIN_PHONE_DIGITS = 10
_MAX_PHONE_DIGITS = 15


def _mask_phone(match: re.Match) -> str:
    digits = sum(c.isdigit() for c in match.group())
    if _MIN_PHONE_DIGITS <= digits <= _MAX_PHONE_DIGITS:
        return "[PHONE]"
    return match.group()


def scrub_pii(text: str) -> str:
    for label, pattern in _PII_PATTERNS.items():
        text = re.sub(pattern, f"[{label}]", text)
    return _PHONE_CANDIDATE.sub(_mask_phone, text)


def scrub_documents(documents: list[Document]) -> list[Document]:
    scrubbed: list[Document] = []
    for doc in documents:
        clean = scrub_pii(doc.page_content)
        if clean != doc.page_content:
            print(f"  PII masked in: {doc.metadata.get('source')}")
        scrubbed.append(Document(page_content=clean, metadata=doc.metadata))
    return scrubbed

"""Async LLM wrapper for any OpenAI-compatible gateway (OpenAI, Groq, Azure). Configure via LLM_BASE_URL, LLM_API_KEY, LLM_MODEL."""

from __future__ import annotations

import os
import re
from typing import Any

from hub.lib import logger, quota
from hub.lib.retry import with_retry

_BASE_URL: str | None = os.environ.get("LLM_BASE_URL")
_API_KEY:  str | None = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
_MODEL:    str        = os.environ.get("LLM_MODEL", "gpt-4o")

# Models known NOT to support response_format=json_object.
# When json_mode=True we ask these models to produce JSON in the prompt instead.
_NO_JSON_MODE: frozenset[str] = frozenset({
    "gemma-7b-it",
    "gemma2-9b-it",
})

_client: Any = None


def _get_client() -> Any:
    global _client
    if _client is not None:
        return _client
    if not _API_KEY:
        return None
    from openai import AsyncOpenAI  # noqa: PLC0415
    kwargs: dict[str, Any] = {"api_key": _API_KEY}
    if _BASE_URL:
        kwargs["base_url"] = _BASE_URL
    _client = AsyncOpenAI(**kwargs)
    return _client


def _demo(context: str) -> str:
    stubs: dict[str, str] = {
        "parse-memo":   '{"accountId":null,"competitor":null,"sentiment":"neutral","contacts":[],"concerns":[],"nextAction":null,"confidence":0.5}',
        "parse-quote":  '{"accountId":null,"tier":"capital","products":[],"urgency":"normal","budgetConfirmed":false,"estimatedValue":null,"confidence":0.5}',
        "brief":        "Demo mode: set LLM_API_KEY for real briefings.",
        "correlate":    '{"scenarioType":null,"signals":[],"confidence":0}',
        "action":       '{"action":"review_manually","reasoning":"Demo mode","confidence":0.1,"timingHours":24}',
        "buyer-move":   '{"classification":"unknown","confidence":0.5,"recommendedOutreach":null}',
        "unstick":      '{"rootCause":"unknown","unstickAction":"manual_review","confidence":0.4}',
        "cross-sell":   '{"recommendations":[],"confidence":0.5}',
    }
    return stubs.get(context, '{"demo":true}')


def _extract_json(text: str) -> str:
    """
    Extract a JSON object from free-text when response_format was not used.
    Falls back to the raw text if no JSON block is found.
    """
    # Try fenced code block first (```json ... ```)
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return m.group(1)
    # Try bare JSON object
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return m.group(0)
    return text


async def chat(
    *,
    messages: list[dict[str, str]],
    max_tokens: int = 600,
    json_mode: bool = False,
    context: str = "",
    max_attempts: int = 3,
) -> str:
    """
    Call the LLM gateway and return the completion string.

    Works with OpenAI, Groq, Azure OpenAI, or any OpenAI-compatible endpoint.
    For Groq models that don't support response_format=json_object, the call
    falls back to prompt-based JSON extraction automatically.

    Raises:
        RuntimeError: TOKEN_QUOTA_EXHAUSTED
    """
    estimated = sum(len(m.get("content", "")) for m in messages) // 4 + max_tokens

    if not quota.has_quota(estimated):
        logger.warn("Quota exhausted — skipping LLM call", context=context, **quota.summary())
        raise RuntimeError("TOKEN_QUOTA_EXHAUSTED")

    client = _get_client()
    if client is None:
        logger.warn("No LLM_API_KEY — using demo stub", context=context)
        return _demo(context)

    # Some models (e.g. gemma on Groq) don't support json_object response_format.
    # For those, append a JSON instruction to the last user message instead.
    use_json_mode = json_mode and _MODEL not in _NO_JSON_MODE
    effective_messages = messages
    if json_mode and not use_json_mode:
        effective_messages = list(messages)
        last = effective_messages[-1]
        effective_messages[-1] = {
            **last,
            "content": last.get("content", "") + "\n\nRespond with a valid JSON object only, no other text.",
        }

    async def _call() -> str:
        kwargs: dict[str, Any] = {
            "model":      _MODEL,
            "messages":   effective_messages,
            "max_tokens": max_tokens,
        }
        if use_json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = await client.chat.completions.create(**kwargs)
        except Exception as exc:
            # If the model rejects response_format, retry once without it
            if "response_format" in str(exc).lower() or "json_object" in str(exc).lower():
                logger.warn("Model does not support json_object — retrying without it", model=_MODEL, context=context)
                kwargs.pop("response_format", None)
                response = await client.chat.completions.create(**kwargs)
            else:
                raise

        usage = response.usage
        total = (getattr(usage, "prompt_tokens", 0) or 0) + (getattr(usage, "completion_tokens", 0) or 0)
        quota.consume(total)
        logger.debug("LLM call", context=context, model=_MODEL, tokens=total, quota_remaining=quota.remaining())

        content = response.choices[0].message.content or ""
        # If we asked for JSON but didn't use the response_format param, extract it
        return _extract_json(content) if (json_mode and not use_json_mode) else content

    return await with_retry(_call, context=context, max_attempts=max_attempts)

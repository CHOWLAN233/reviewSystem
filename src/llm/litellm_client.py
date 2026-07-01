"""
LiteLLM client wrapper with retry logic and JSON-mode support.

Provides a unified interface to 100+ LLM providers so models can be
switched by changing a single string (e.g. "gemini/gemini-2.0-flash"
→ "claude-sonnet-4-20250514").
"""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


class LiteLLMError(Exception):
    """Wraps underlying LLM API errors with model context."""

    def __init__(self, message: str, model: str = "", status_code: Optional[int] = None) -> None:
        self.model = model
        self.status_code = status_code
        super().__init__(message)


class LiteLLMClient:
    """
    Thin wrapper around ``litellm.completion`` with:

    - Exponential-backoff retry on transient errors
    - Optional JSON-mode enforcement
    - Consistent error taxonomy
    """

    # HTTP status codes that warrant a retry
    RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

    def __init__(
        self,
        model: str,
        api_key: str,
        api_base: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        max_retries: int = 3,
        retry_base_delay: float = 2.0,
    ) -> None:
        """
        Parameters
        ----------
        model : str
            LiteLLM model identifier, e.g. ``"gemini/gemini-2.0-flash"``.
        api_key : str
            API key for the provider.
        api_base : str | None
            Custom API base URL (for proxies / self-hosted).
        temperature : float
            LLM sampling temperature.
        max_tokens : int
            Maximum tokens in the completion response.
        max_retries : int
            Number of retries on transient errors.
        retry_base_delay : float
            Base delay in seconds for exponential backoff.
        """
        self.model = model
        self.api_key = api_key
        self.api_base = api_base
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay

        # Set environment for providers that read from env vars
        import os

        if api_key:
            # LiteLLM reads from provider-specific vars; set a generic one
            os.environ.setdefault("OPENAI_API_KEY", api_key)
            os.environ.setdefault("ANTHROPIC_API_KEY", api_key)
            os.environ.setdefault("GEMINI_API_KEY", api_key)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def complete(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Send a completion request and return the text response.

        Retries on transient errors with exponential backoff.

        Raises
        ------
        LiteLLMError
            After all retries are exhausted or on non-retryable errors.
        """
        messages = self._build_messages(prompt, system_prompt)

        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return self._call(messages)
            except LiteLLMError:
                raise  # non-retryable – propagate immediately
            except Exception as exc:
                last_error = exc
                status = getattr(exc, "status_code", None)

                if status in self.RETRYABLE_STATUS_CODES or self._is_connection_error(exc):
                    if attempt < self.max_retries:
                        delay = self.retry_base_delay * (2 ** (attempt - 1)) + random.uniform(0, 1)
                        logger.warning(
                            f"[{self.model}] Attempt {attempt}/{self.max_retries} failed "
                            f"(status={status}). Retrying in {delay:.1f}s …"
                        )
                        time.sleep(delay)
                        continue
                else:
                    raise LiteLLMError(
                        f"Non-retryable error from {self.model}: {exc}",
                        model=self.model,
                        status_code=status,
                    ) from exc

        raise LiteLLMError(
            f"Exhausted {self.max_retries} retries for {self.model}. "
            f"Last error: {last_error}",
            model=self.model,
        )

    def complete_json(self, prompt: str, system_prompt: Optional[str] = None) -> dict[str, Any]:
        """
        Like :meth:`complete`, but parse the response as JSON.

        Appends a JSON-only instruction to *system_prompt* and attempts
        ``json.loads`` on the raw response.  Falls back to extracting the
        first JSON object via regex if the model included extra text.

        Raises
        ------
        LiteLLMError
            If the response cannot be parsed as JSON after fallback attempts.
        """
        json_instruction = "\n\nIMPORTANT: Respond with a valid JSON object ONLY. No markdown fences, no extra text."
        effective_system = (system_prompt or "") + json_instruction

        raw = self.complete(prompt, system_prompt=effective_system)
        return self._parse_json_response(raw)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_messages(self, prompt: str, system_prompt: Optional[str]) -> list[dict]:
        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _call(self, messages: list[dict]) -> str:
        """Raw LiteLLM call.  Import inside to avoid hard dependency at module level."""
        import litellm

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if self.api_key:
            kwargs["api_key"] = self.api_key

        response = litellm.completion(**kwargs)
        return response.choices[0].message.content

    def _parse_json_response(self, raw: str) -> dict[str, Any]:
        """Attempt to parse *raw* as JSON, with fallback extraction."""
        # Try direct parse
        try:
            return json.loads(raw.strip())
        except json.JSONDecodeError:
            pass

        # Try stripping markdown fences
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # Remove opening fence (```json or ```)
            if lines[0].startswith("```"):
                lines = lines[1:]
            # Remove closing fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass

        # Try regex extraction – find first {...} block
        import re

        match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        raise LiteLLMError(
            f"Failed to parse JSON from {self.model} response. "
            f"Raw (first 500 chars): {raw[:500]}",
            model=self.model,
        )

    @staticmethod
    def _is_connection_error(exc: Exception) -> bool:
        """Heuristic: is *exc* a network-level error?"""
        name = type(exc).__name__.lower()
        return any(
            keyword in name
            for keyword in ("connection", "timeout", "network", "socket", "httpx")
        )

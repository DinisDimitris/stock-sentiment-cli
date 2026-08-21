"""LLM client adapter for OpenAI and Anthropic."""

from __future__ import annotations

from types import SimpleNamespace

from config.settings import settings


def get_default_model() -> str:
    provider = get_provider()
    if provider == "openai":
        return settings.open_ai_default_model
    if provider == "anthropic":
        return settings.anthropic_default_model
    raise RuntimeError(f"Unsupported LLM provider '{provider}'")


def get_escalation_model() -> str:
    provider = get_provider()
    if provider == "openai":
        return settings.open_ai_escalation_model
    if provider == "anthropic":
        return settings.anthropic_escalation_model
    raise RuntimeError(f"Unsupported LLM provider '{provider}'")


def get_provider() -> str:
    provider = settings.llm_provider.strip().lower()
    if provider and provider != "auto":
        if provider in {"openai", "anthropic"}:
            return provider
        raise RuntimeError(
            "LLM_PROVIDER must be one of: auto, openai, anthropic."
        )

    if settings.open_ai_api_key:
        return "openai"
    if settings.anthropic_api_key:
        return "anthropic"
    raise RuntimeError(
        "No LLM credentials configured. Set OPENAI_API_KEY or ANTHROPIC_API_KEY."
    )


class _AnthropicResponses:
    def __init__(self, api_key: str, base_url: str, api_version: str):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._api_version = api_version

    async def create(
        self,
        *,
        model: str,
        messages: list[dict],
        response_format: dict | None = None,
        max_tokens: int,
        temperature: float,
    ):
        del response_format
        system_messages = [m["content"] for m in messages if m["role"] == "system"]
        conversational_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m["role"] != "system"
        ]
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": conversational_messages,
        }
        if system_messages:
            payload["system"] = "\n\n".join(system_messages)

        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": self._api_version,
            "content-type": "application/json",
        }
        try:
            import httpx
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Missing dependency 'httpx'. Install project dependencies with "
                "'pip install -r requirements.txt' before running Anthropic-backed analysis."
            ) from exc
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self._base_url}/v1/messages",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
        data = response.json()
        text_parts = [
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        ]
        content = "".join(text_parts).strip()
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


class _AnthropicClient:
    def __init__(self, api_key: str, base_url: str, api_version: str):
        self.chat = SimpleNamespace(
            completions=_AnthropicResponses(api_key, base_url, api_version)
        )


def get_client():
    provider = get_provider()

    if provider == "openai":
        try:
            from openai import AsyncOpenAI
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Missing dependency 'openai'. Install project dependencies with "
                "'pip install -r requirements.txt' before running analysis."
            ) from exc

        return AsyncOpenAI(
            api_key=settings.open_ai_api_key,
            base_url=settings.open_ai_endpoint,
        )

    if provider == "anthropic":
        return _AnthropicClient(
            api_key=settings.anthropic_api_key,
            base_url=settings.anthropic_api_base,
            api_version=settings.anthropic_api_version,
        )

    raise RuntimeError(f"Unsupported LLM provider '{provider}'")

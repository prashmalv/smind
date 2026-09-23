"""Azure OpenAI chat client with tool calling, plus a local fallback.

The fallback is not a toy: when no Azure credentials are present the copilot still routes
questions to the right modules and composes an answer from their real findings. It loses
the language fluency, not the reasoning. That keeps the whole product demonstrable before
a subscription exists.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)


class AzureOpenAIClient:
    def __init__(self) -> None:
        self.enabled = settings.openai_enabled
        self.endpoint = settings.azure_openai_endpoint.rstrip("/")
        self.deployment = settings.azure_openai_chat_deployment
        self.api_version = settings.azure_openai_api_version
        self.key = settings.azure_openai_api_key

    @property
    def is_reasoning_model(self) -> bool:
        name = self.deployment.lower()
        return name.startswith(("gpt-5", "o1", "o3", "o4"))

    @property
    def chat_url(self) -> str:
        return (
            f"{self.endpoint}/openai/deployments/{self.deployment}"
            f"/chat/completions?api-version={self.api_version}"
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1200,
    ) -> dict[str, Any]:
        """Returns the raw choice message: {role, content, tool_calls?}."""
        if not self.enabled:
            raise RuntimeError("Azure OpenAI is not configured")

        payload: dict[str, Any] = {"messages": messages}

        # The gpt-5 and o-series families renamed the token cap and fix temperature at 1.
        # Sending the older field names to them is a 400, so the shape of the request is
        # chosen from the deployment rather than hardcoded — Azure retires model versions
        # on a schedule and this client has to survive the next rename too.
        if self.is_reasoning_model:
            payload["max_completion_tokens"] = max_tokens
        else:
            payload["max_tokens"] = max_tokens
            payload["temperature"] = temperature

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                self.chat_url, json=payload, headers={"api-key": self.key}
            )
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.enabled:
            return []
        url = (
            f"{self.endpoint}/openai/deployments/{settings.azure_openai_embedding_deployment}"
            f"/embeddings?api-version={self.api_version}"
        )
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json={"input": texts}, headers={"api-key": self.key})
            resp.raise_for_status()
            return [d["embedding"] for d in resp.json()["data"]]


openai_client = AzureOpenAIClient()


def tool_schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def parse_tool_calls(message: dict[str, Any]) -> list[tuple[str, str, dict]]:
    """→ [(call_id, tool_name, arguments)]"""
    out = []
    for call in message.get("tool_calls") or []:
        fn = call.get("function", {})
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        out.append((call["id"], fn.get("name", ""), args))
    return out

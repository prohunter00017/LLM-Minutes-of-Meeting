"""Cloudflare Workers AI provider — uses direct Workers AI REST API.

AI Gateway endpoints (gateway.ai.cloudflare.com) often return 403/1010 for 
Workers AI models, so this provider uses the direct API path automatically.
"""
from typing import List, Dict, Any

import httpx

from app.providers.llm.base import BaseLLMProvider


class CloudflareWorkersAI(BaseLLMProvider):
    """
    Cloudflare Workers AI via direct REST API.
    Handles @cf/ prefix models and converts AI Gateway URLs to direct API.
    """

    # Direct API base
    DIRECT_BASE = "https://api.cloudflare.com/client/v4/accounts"

    def __init__(self, base_url: str, api_key: str, model: str):
        self.model = model
        self.api_key = api_key
        self.account_id = self._extract_account_id(base_url)
        if not self.account_id:
            raise ValueError(
                "Could not extract Cloudflare account_id from base_url. "
                "Use direct API base: https://api.cloudflare.com/client/v4/accounts/{account_id}"
            )
        self.endpoint = f"{self.DIRECT_BASE}/{self.account_id}/ai/run/{model}"

    def _extract_account_id(self, url: str) -> str:
        """Pull 32-char Cloudflare account ID from URL."""
        parts = url.split("/")
        for i, p in enumerate(parts):
            if p == "v1" and i + 1 < len(parts) and len(parts[i + 1]) == 32:
                return parts[i + 1]
            if p == "accounts" and i + 1 < len(parts):
                return parts[i + 1]
        return ""

    def complete(self, messages: List[Dict], **kwargs: Any) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {"messages": messages}
        if "temperature" in kwargs:
            payload["temperature"] = kwargs["temperature"]
        if "max_tokens" in kwargs:
            payload["max_tokens"] = kwargs["max_tokens"]

        with httpx.Client(timeout=120) as client:
            resp = client.post(self.endpoint, headers=headers, json=payload)

        if resp.status_code != 200:
            raise self._wrap_error(resp)

        data = resp.json()
        if not data.get("success", True):
            err = data.get("errors", data.get("error", [{}]))[0]
            raise RuntimeError(f"Workers AI inference error: {err}")

        # Cloudflare wraps OpenAI-compatible result under "result"
        result = data.get("result", {})

        # OpenAI-compatible shape: choices[0].message.content
        if isinstance(result, dict):
            choices = result.get("choices", [])
            if choices and isinstance(choices, list):
                msg = choices[0].get("message", {})
                # Standard content field
                content = msg.get("content", "")
                if content:
                    return content
                # GPT-OSS / reasoning models put output in reasoning_content
                reasoning = msg.get("reasoning_content", "")
                if reasoning:
                    return reasoning

            # Fallback for other result shapes
            if "response" in result:
                return result["response"]
            if "content" in result:
                return result["content"]

        raise RuntimeError(f"Unexpected Workers AI response shape: {data}")

    def complete_with_reasoning(self, messages: List[Dict], **kwargs: Any) -> Dict:
        content = self.complete(messages, **kwargs)
        return {"content": content, "reasoning_details": None}

    def _wrap_error(self, resp) -> RuntimeError:
        """Turn an opaque Cloudflare error into an actionable message."""
        body = resp.text[:400]
        if resp.status_code in (401, 403):
            return RuntimeError(
                f"Cloudflare Workers AI rejected the API token ({resp.status_code}). "
                "The token in your .env is invalid, expired or revoked, or it lacks "
                "the 'Workers AI' permission. Create a new token at "
                "https://dash.cloudflare.com/profile/api-tokens with the "
                "'Workers AI' permission, update LLM_API_KEY, then redeploy. "
                f"Response: {body}"
            )
        if resp.status_code == 404:
            return RuntimeError(
                f"Cloudflare model not found (404). Check LLM_MODEL is valid for "
                f"this account. Response: {body}"
            )
        if resp.status_code == 429:
            return RuntimeError(f"Cloudflare rate limit exhausted (429). Response: {body}")
        return RuntimeError(f"Workers AI error {resp.status_code}: {body}")

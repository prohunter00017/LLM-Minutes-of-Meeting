from typing import List, Dict, Any
import re
from openai import OpenAI
from app.providers.llm.base import BaseLLMProvider


class OpenAICompatibleLLM(BaseLLMProvider):
    """
    Works with any OpenAI-compatible provider:
    OpenAI, OpenRouter, Groq, Together, Azure, Gemini (via compat endpoint), etc.

    Usage:
        client = OpenAICompatibleLLM(
            base_url="https://openrouter.ai/api/v1",
            api_key="sk-...",
            model="anthropic/claude-opus-4",
        )
        result = client.complete(messages=[{"role": "user", "content": "Hello"}])
    """

    # Reasoning models (MiniMax, Qwen, DeepSeek...) leak <think>...</think> blocks
    # into the visible content. Strip them so only the real answer is returned.
    _THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
    _OPEN_THINK_RE = re.compile(r"^<think>.*", re.DOTALL | re.IGNORECASE)

    def __init__(self, base_url: str, api_key: str, model: str):
        self.model = model
        self._client = OpenAI(base_url=base_url, api_key=api_key or "none")

    @classmethod
    def _strip_reasoning(cls, text: str) -> str:
        if not text:
            return text
        cleaned = cls._THINK_RE.sub("", text)
        # Unterminated <think> (truncated output) — drop everything from the tag on.
        cleaned = cls._OPEN_THINK_RE.sub("", cleaned)
        return cleaned.strip()

    def complete(self, messages: List[Dict], **kwargs: Any) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            **kwargs,
        )
        return self._strip_reasoning(response.choices[0].message.content or "")

    def complete_with_reasoning(self, messages: List[Dict], **kwargs: Any) -> Dict:
        """Returns both content and reasoning_details (for providers that support it)."""
        extra_body = kwargs.pop("extra_body", {"reasoning": {"enabled": True}})
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            extra_body=extra_body,
            **kwargs,
        )
        msg = response.choices[0].message
        return {
            "content": msg.content or "",
            "reasoning_details": getattr(msg, "reasoning_details", None),
        }

from app.providers.llm.openai_compatible import OpenAICompatibleLLM
from app.providers.llm.cloudflare_workers import CloudflareWorkersAI
from app.models import SystemConfig


def get_llm_client():
    """Return a configured LLM client using DB config."""
    base_url = SystemConfig.get("llm_base_url", "https://api.openai.com/v1")
    api_key = SystemConfig.get("llm_api_key", "")
    model = SystemConfig.get("llm_model", "gpt-4o-mini")

    # Route Cloudflare Workers AI (@cf/ models or gateway.ai.cloudflare.com) to custom provider
    if model.startswith("@cf/") or "cloudflare.com" in (base_url or ""):
        return CloudflareWorkersAI(base_url=base_url, api_key=api_key, model=model)

    return OpenAICompatibleLLM(base_url=base_url, api_key=api_key, model=model)

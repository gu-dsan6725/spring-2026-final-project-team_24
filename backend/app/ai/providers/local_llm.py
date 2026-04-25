"""Open-source LLM provider — Groq (demo) or local Ollama/vLLM.

For the demo, this uses **Groq** — a free API that serves open-source
models (Llama 3, Mistral, Gemma) with an OpenAI-compatible interface.
No local GPU, no credit card, no cost.

For production, swap to a locally deployed model (Ollama, vLLM) by
changing GROQ_BASE_URL to the local server endpoint.

Backends (all OpenAI-compatible, selected by VERIFICATION_PROVIDER):
- groq   → https://api.groq.com/openai/v1  (FREE, default for demo)
- ollama → http://localhost:11434/v1         (local, needs GPU)
- vllm   → http://localhost:8000/v1          (local, production)

Used as:
- Stage 2 verification backend in similarity_verifier.py.
- Cost-free chat provider for any pipeline (writing assist, note
  evaluation, connection inference) that wants to avoid API spend.

Configuration (from app.config.settings, sourced from .env or ../.env):
- GROQ_API_KEY: API key (free from https://console.groq.com/)
- GROQ_BASE_URL: endpoint (default: Groq cloud)
- GROQ_MODEL: model name (default: llama-3.3-70b-versatile)

Implements the same ChatProvider interface as openai_chat.py and
anthropic_chat.py — uses the openai Python SDK with a custom base_url.
"""

from openai import AsyncOpenAI

from app.config import settings


def get_groq_client() -> AsyncOpenAI:
    """Create an AsyncOpenAI client pointed at Groq (or any compatible server)."""
    return AsyncOpenAI(
        api_key=settings.GROQ_API_KEY,
        base_url=settings.GROQ_BASE_URL,
    )


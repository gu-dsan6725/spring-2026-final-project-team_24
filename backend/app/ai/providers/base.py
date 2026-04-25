"""Base interfaces for chat and embedding providers.

All AI providers implement one of these interfaces so that pipelines,
ACE roles, and services can swap implementations without code changes.

Chat providers (for generation, evaluation, verification):
- OpenAI    (app.ai.providers.openai_chat)
- Anthropic (app.ai.providers.anthropic_chat)
- Groq / local LLM (app.ai.providers.local_llm)
  Demo default: Groq (free, serves Llama/Mistral via OpenAI-compatible API).
  Production: swap to Ollama or vLLM by changing GROQ_BASE_URL.

Embedding providers (for vector indexing):
- OpenAI embeddings (app.ai.providers.openai_embeddings)

Composite providers:
- SimilarityVerifier (app.ai.providers.similarity_verifier)
  Two-stage: Pinecone vector search → Groq/local LLM confirmation.
  Used by merge detection, edge dedup, concept search, item dedup.
"""

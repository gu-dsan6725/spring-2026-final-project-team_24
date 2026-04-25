"""Two-stage similarity verification — general provider.

Every similarity operation in the platform goes through this verifier:
merge detection, edge dedup, user-facing concept search, item dedup.

Stage 1 — Vector search (Pinecone):
  Fast, cheap, high recall. Returns top-K candidates by cosine similarity.
  May include false positives (e.g., "Bayesian inference" vs "Bayesian
  optimization" are embedding-close but conceptually distinct).

Stage 2 — LLM confirmation (via open-source model on Groq / local):
  An open-source model (Llama 3, Mistral — served by Groq for the demo,
  or a local Ollama/vLLM server in production) reads both the query text
  and each candidate's text, then classifies:

  - SAME: genuinely the same concept/edge/idea.
  - SIMILAR_BUT_DIFFERENT: related topic, different concept. Useful for
    "related but distinct" flags and connection suggestions.
  - UNRELATED: false positive from embedding search — discard.

  The provider is selected by VERIFICATION_PROVIDER in settings
  (default: "groq" — free, no cost). See local_llm.py.

Returns verified matches with classification labels and original
similarity scores from Stage 1.

Usage pattern:
  verifier = SimilarityVerifier(pinecone_client, groq_client)
  results = await verifier.verify(
      query_text="Bayes Theorem derivation",
      namespaces=["group_42_landscape", "user_alice_concepts", ...],
      top_k=10,
      stage2_threshold=0.70,  # only LLM-verify candidates above this
  )
  # results: [VerifiedMatch(id, score, classification, namespace), ...]

Privacy note: Stage 2 requires reading the candidate's raw text from
MongoDB. The verifier fetches text internally but NEVER exposes it in
its return value when searching across users. Callers receive only
IDs, scores, classifications, and owner counts — not content.
"""


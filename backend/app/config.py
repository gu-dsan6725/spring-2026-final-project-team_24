from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    # PostgreSQL
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "app"
    POSTGRES_PASSWORD: str = "changeme"
    POSTGRES_DB: str = "knowledge"

    # MongoDB
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB: str = "knowledge"

    # Pinecone
    PINECONE_API_KEY: str = ""
    PINECONE_INDEX: str = "knowledge"

    # S3 / MinIO
    S3_ENDPOINT: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET: str = "uploads"

    # AI providers — cloud
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    MISTRAL_API_KEY: str = ""
    COHERE_API_KEY: str = ""

    # AI providers — free / open-source model access (demo default: Groq)
    GROQ_API_KEY: str = ""
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # Stage 2 verification provider selection
    # "groq" (default, free), "openai", "anthropic", "mistral", "ollama"
    VERIFICATION_PROVIDER: str = "groq"

    # Item generation pipeline
    ITEM_GENERATION_PROVIDER: str = "anthropic"
    ITEMS_PER_ROUND: int = 3
    MAX_REFINEMENT_ITERATIONS: int = 3
    MAX_HARDENING_ITERATIONS: int = 3

    # MinerU — local PDF/document extraction.
    # Valid values (per mineru.cli.common.do_parse):
    #   - "pipeline"           : CPU-friendly classical pipeline (default, portable)
    #   - "vlm-auto-engine"    : pick best VLM engine (vllm / huggingface) — needs GPU
    #   - "vlm-huggingface"    : HuggingFace transformers VLM
    #   - "vlm-vllm-engine"    : vLLM sync engine
    #   - "hybrid-auto-engine" : pipeline + VLM hybrid
    # "auto" is NOT recognized by MinerU and will silently produce no output.
    MINERU_BACKEND: str = "pipeline"
    EXTRACTED_DIR: str = "data/extracted"

    # Paper ingestion (section split + sub-chunk + embed)
    # If set, ingest-paper copies the finished paper folder here (e.g. Obsidian vault path).
    PAPER_EXPORT_DIR: str = ""
    # Char-window sub-chunker parameters.
    DOC_CHUNK_SIZE: int = 1500
    DOC_CHUNK_OVERLAP: int = 200

    # Dependency graph builder (link-architect agent over section MDs).
    # When enabled and a chat provider key is configured, ingest will run one
    # extra LLM call per paper to propose typed directed edges
    # (depends_on / generalizes / contrasts / instantiates) and assign each
    # section a topological depth. Used by the depth-aware item scheduler.
    INGEST_BUILD_GRAPH: bool = True
    # Empty string ⇒ same provider as ITEM_GENERATION_PROVIDER.
    GRAPH_LLM_PROVIDER: str = ""

    # Auth
    JWT_SECRET: str = "changeme-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    # Observability — Prometheus scrape endpoint (off unless enabled)
    PROMETHEUS_METRICS_ENABLED: bool = False
    PROMETHEUS_METRICS_PATH: str = "/metrics"

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # Load env from multiple candidate locations so users can keep a
    # single shared .env for the whole DSAN 6725 project tree instead
    # of duplicating keys per sub-project. pydantic-settings processes
    # the tuple left-to-right; later files override earlier ones, so
    # the closest (most specific) file wins.
    model_config = {
        "env_file": ("../../.env", "../.env", ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()

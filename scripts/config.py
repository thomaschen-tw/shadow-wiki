"""
Application settings — loaded from `.env` (project root).

Each field maps to an environment variable (uppercase, same name):
  lmstudio_model  ←  LMSTUDIO_MODEL in .env
  ollama_model    ←  OLLAMA_MODEL
  qwen_cloud_model ← QWEN_CLOUD_MODEL
  …

Change models and API keys in `.env` only. Values in Python below are fallbacks
when a variable is missing (e.g. fresh clone before `cp .env.example .env`).
After editing `.env`, restart long-running processes (worker, MCP) or call
`reload_settings()` so they pick up changes.
"""
from enum import Enum

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LocalBackend(str, Enum):
    AUTO = "auto"
    LMSTUDIO = "lmstudio"
    OLLAMA = "ollama"


class CloudBackend(str, Enum):
    CLAUDE = "claude"
    QWEN_CLOUD = "qwen_cloud"
    DEEPSEEK = "deepseek"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # LMSTUDIO_MODEL in .env → lmstudio_model (case-insensitive match)
        env_nested_delimiter="__",
    )

    # LLM routing
    local_llm_backend: LocalBackend = LocalBackend.AUTO
    cloud_llm_backend: CloudBackend = CloudBackend.CLAUDE

    # LM Studio — set LMSTUDIO_MODEL in .env (id from GET …/v1/models)
    lmstudio_base_url: str = Field(default="http://localhost:1234/v1", validation_alias="LMSTUDIO_BASE_URL")
    lmstudio_model: str = Field(default="", validation_alias="LMSTUDIO_MODEL")

    # Ollama — set OLLAMA_MODEL in .env
    ollama_base_url: str = Field(default="http://localhost:11434/v1", validation_alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="", validation_alias="OLLAMA_MODEL")

    # Claude — ANTHROPIC_API_KEY, CLAUDE_MODEL
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    claude_model: str = Field(default="claude-sonnet-4-6", validation_alias="CLAUDE_MODEL")

    # Qwen Cloud — DASHSCOPE_API_KEY, QWEN_CLOUD_MODEL
    dashscope_api_key: str = Field(default="", validation_alias="DASHSCOPE_API_KEY")
    qwen_cloud_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        validation_alias="QWEN_CLOUD_BASE_URL",
    )
    qwen_cloud_model: str = Field(default="qwen-plus", validation_alias="QWEN_CLOUD_MODEL")

    # DeepSeek — DEEPSEEK_API_KEY, DEEPSEEK_MODEL
    deepseek_api_key: str = Field(default="", validation_alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field(default="https://api.deepseek.com/v1", validation_alias="DEEPSEEK_BASE_URL")
    deepseek_model: str = Field(default="deepseek-chat", validation_alias="DEEPSEEK_MODEL")

    # GitHub
    github_token: str = Field(default="", validation_alias="GITHUB_TOKEN")
    github_repo: str = Field(default="", validation_alias="GITHUB_REPO")
    github_webhook_secret: str = Field(default="", validation_alias="GITHUB_WEBHOOK_SECRET")

    # Slack
    slack_bot_token: str = Field(default="", validation_alias="SLACK_BOT_TOKEN")
    slack_app_token: str = Field(default="", validation_alias="SLACK_APP_TOKEN")
    slack_channels: str = Field(default="", validation_alias="SLACK_CHANNELS")

    # Linear
    linear_api_key: str = Field(default="", validation_alias="LINEAR_API_KEY")

    # Local scan
    local_scan_paths: str = Field(default="./src", validation_alias="LOCAL_SCAN_PATHS")
    local_scan_extensions: str = Field(default=".py,.ts,.tsx,.md,.go", validation_alias="LOCAL_SCAN_EXTENSIONS")

    # LLM behaviour
    use_cloud_llm: bool = Field(default=False, validation_alias="USE_CLOUD_LLM")
    llm_timeout: int = Field(default=300, validation_alias="LLM_TIMEOUT")
    enable_thinking: bool = Field(default=False, validation_alias="ENABLE_THINKING")

    # Database
    use_local_db: bool = Field(default=True, validation_alias="USE_LOCAL_DB")
    database_url: str = Field(default="", validation_alias="DATABASE_URL")

    # Knowledge Base — KNOWLEDGE_BASE_PATH, KNOWLEDGE_BASE_SIMILARITY_THRESHOLD
    knowledge_base_path: str = Field(default="", validation_alias="KNOWLEDGE_BASE_PATH")
    knowledge_base_extensions: str = Field(default=".md", validation_alias="KNOWLEDGE_BASE_EXTENSIONS")
    knowledge_base_similarity_threshold: float = Field(
        default=0.85, validation_alias="KNOWLEDGE_BASE_SIMILARITY_THRESHOLD"
    )

    # System
    wiki_dir: str = Field(default="./wiki", validation_alias="WIKI_DIR")
    db_path: str = Field(default="./db/shadow.db", validation_alias="DB_PATH")
    raw_dir: str = Field(default="./raw", validation_alias="RAW_DIR")


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """Drop cached settings and reload from .env (after resource_mgr cloud/db toggles)."""
    global _settings
    _settings = None
    return get_settings()

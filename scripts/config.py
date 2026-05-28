from enum import Enum
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
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM routing
    local_llm_backend: LocalBackend = LocalBackend.AUTO
    cloud_llm_backend: CloudBackend = CloudBackend.CLAUDE

    # LM Studio
    lmstudio_base_url: str = "http://localhost:1234/v1"
    lmstudio_model: str = "qwen3-35b"

    # Ollama
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen3:35b"

    # Claude
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"

    # Qwen Cloud
    dashscope_api_key: str = ""
    qwen_cloud_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_cloud_model: str = "qwen-plus"

    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"

    # GitHub
    github_token: str = ""
    github_repo: str = ""
    github_webhook_secret: str = ""

    # Slack
    slack_bot_token: str = ""
    slack_app_token: str = ""
    slack_channels: str = ""

    # Linear
    linear_api_key: str = ""

    # Local scan
    local_scan_paths: str = "./src"
    local_scan_extensions: str = ".py,.ts,.tsx,.md,.go"

    # LLM behaviour
    use_cloud_llm: bool = False   # false = all tasks use local; true = cloud for new pages
    llm_timeout: int = 300
    enable_thinking: bool = False

    # Database
    use_local_db: bool = True   # false = use DATABASE_URL (PostgreSQL / remote)
    database_url: str = ""      # e.g. postgresql://user:pass@host/dbname

    # System
    wiki_dir: str = "./wiki"
    db_path: str = "./db/shadow.db"
    raw_dir: str = "./raw"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings

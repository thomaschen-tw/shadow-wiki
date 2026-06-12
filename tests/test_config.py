import os
import pytest
from pydantic import ValidationError


def test_default_local_backend():
    from scripts.config import Settings, LocalBackend
    s = Settings(_env_file=None)
    assert s.local_llm_backend == LocalBackend.AUTO


def test_default_cloud_backend():
    from scripts.config import Settings, CloudBackend
    s = Settings(_env_file=None)
    assert s.cloud_llm_backend == CloudBackend.CLAUDE


def test_override_local_backend_from_env(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_BACKEND", "ollama")
    from scripts.config import Settings, LocalBackend
    s = Settings()
    assert s.local_llm_backend == LocalBackend.OLLAMA


def test_override_cloud_backend_from_env(monkeypatch):
    monkeypatch.setenv("CLOUD_LLM_BACKEND", "deepseek")
    from scripts.config import Settings, CloudBackend
    s = Settings()
    assert s.cloud_llm_backend == CloudBackend.DEEPSEEK


def test_lmstudio_defaults_without_env():
    from scripts.config import Settings
    s = Settings(_env_file=None)
    assert s.lmstudio_base_url == "http://localhost:1234/v1"
    # Model ids come from .env in production; empty when unset
    assert s.lmstudio_model == ""


def test_lmstudio_model_loaded_from_env(monkeypatch):
    monkeypatch.setenv("LMSTUDIO_MODEL", "qwen/qwen3.6-27b")
    from scripts.config import Settings
    s = Settings(_env_file=None)
    assert s.lmstudio_model == "qwen/qwen3.6-27b"


def test_default_pipeline_mode_and_write_target():
    from scripts.config import Settings, PipelineMode, WikiWriteTarget
    s = Settings(_env_file=None)
    assert s.pipeline_mode == PipelineMode.LEGACY
    assert s.wiki_write_target == WikiWriteTarget.LEGACY
    assert s.resolved_wiki_dir.endswith("wiki_content/legacy")


def test_write_target_switches_resolved_wiki_dir(monkeypatch):
    monkeypatch.setenv("WIKI_WRITE_TARGET", "etl")
    from scripts.config import Settings
    s = Settings(_env_file=None)
    assert s.resolved_wiki_dir.endswith("wiki_content/etl")


def test_explicit_wiki_dir_overrides_write_target(monkeypatch):
    monkeypatch.setenv("WIKI_WRITE_TARGET", "etl")
    monkeypatch.setenv("WIKI_DIR", "/tmp/custom-wiki")
    from scripts.config import Settings
    s = Settings(_env_file=None)
    assert s.resolved_wiki_dir == "/tmp/custom-wiki"


def test_get_settings_singleton(monkeypatch):
    import scripts.config as cfg
    cfg._settings = None
    s1 = cfg.get_settings()
    s2 = cfg.get_settings()
    assert s1 is s2


def test_get_settings_reset(monkeypatch):
    import scripts.config as cfg
    cfg._settings = None
    s1 = cfg.get_settings()
    cfg._settings = None
    s2 = cfg.get_settings()
    assert s1 is not s2


def test_invalid_local_backend_raises(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_BACKEND", "invalid_backend")
    from scripts.config import Settings
    with pytest.raises(ValidationError):
        Settings()


def test_invalid_cloud_backend_raises(monkeypatch):
    monkeypatch.setenv("CLOUD_LLM_BACKEND", "gpt4")
    from scripts.config import Settings
    with pytest.raises(ValidationError):
        Settings()


def test_invalid_pipeline_mode_raises(monkeypatch):
    monkeypatch.setenv("PIPELINE_MODE", "nightly")
    from scripts.config import Settings
    with pytest.raises(ValidationError):
        Settings()


def test_invalid_write_target_raises(monkeypatch):
    monkeypatch.setenv("WIKI_WRITE_TARGET", "published")
    from scripts.config import Settings
    with pytest.raises(ValidationError):
        Settings()

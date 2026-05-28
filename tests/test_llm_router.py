import pytest
from unittest.mock import patch, MagicMock


def _reset_settings(monkeypatch, **env_vars):
    import scripts.config as cfg
    cfg._settings = None
    for k, v in env_vars.items():
        monkeypatch.setenv(k, v)


def test_classify_routes_to_local(monkeypatch):
    _reset_settings(monkeypatch, LOCAL_LLM_BACKEND="lmstudio")
    with patch("scripts.distill.llm_router._call_local", return_value="result") as mock_local, \
         patch("scripts.distill.llm_router._call_cloud") as mock_cloud:
        from scripts.distill.llm_router import call_llm, TaskType
        result = call_llm(TaskType.CLASSIFY, "prompt")
    mock_local.assert_called_once_with("prompt", "You are a helpful assistant.")
    mock_cloud.assert_not_called()
    assert result == "result"


def test_summarize_routes_to_local(monkeypatch):
    _reset_settings(monkeypatch)
    with patch("scripts.distill.llm_router._call_local", return_value="summary") as mock_local:
        from scripts.distill.llm_router import call_llm, TaskType
        call_llm(TaskType.SUMMARIZE, "prompt", "system")
    mock_local.assert_called_once_with("prompt", "system")


def test_create_page_routes_to_cloud(monkeypatch):
    _reset_settings(monkeypatch, CLOUD_LLM_BACKEND="claude", USE_CLOUD_LLM="true")
    with patch("scripts.distill.llm_router._call_cloud", return_value="page") as mock_cloud, \
         patch("scripts.distill.llm_router._call_local") as mock_local:
        from scripts.distill.llm_router import call_llm, TaskType
        result = call_llm(TaskType.CREATE_PAGE, "prompt")
    mock_cloud.assert_called_once()
    mock_local.assert_not_called()
    assert result == "page"


def test_create_page_uses_local_when_cloud_disabled(monkeypatch):
    _reset_settings(monkeypatch, USE_CLOUD_LLM="false")
    with patch("scripts.distill.llm_router._call_local", return_value="local-page") as mock_local, \
         patch("scripts.distill.llm_router._call_cloud") as mock_cloud:
        from scripts.distill.llm_router import call_llm, TaskType
        result = call_llm(TaskType.CREATE_PAGE, "prompt")
    mock_local.assert_called_once()
    mock_cloud.assert_not_called()
    assert result == "local-page"


def test_call_openai_compatible_uses_correct_model(monkeypatch):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "hello"
    mock_client.chat.completions.create.return_value = mock_response
    with patch("scripts.distill.llm_router._openai_client", return_value=mock_client) as mock_factory:
        from scripts.distill.llm_router import _call_openai_compatible
        result = _call_openai_compatible(
            base_url="http://localhost:1234/v1",
            api_key="",
            model="qwen3-35b",
            prompt="test",
            system="sys",
        )
    assert result == "hello"
    call_kwargs = mock_client.chat.completions.create.call_args
    assert call_kwargs.kwargs["model"] == "qwen3-35b"


def test_local_uses_lmstudio_when_configured(monkeypatch):
    _reset_settings(monkeypatch, LOCAL_LLM_BACKEND="lmstudio",
                    LMSTUDIO_BASE_URL="http://localhost:1234/v1",
                    LMSTUDIO_MODEL="qwen3-35b")
    with patch("scripts.distill.llm_router._call_openai_compatible", return_value="ok") as mock_oa:
        from scripts.distill.llm_router import _call_local
        _call_local("prompt", "system")
    mock_oa.assert_called_once()
    args = mock_oa.call_args
    assert args.kwargs["base_url"] == "http://localhost:1234/v1"
    assert args.kwargs["model"] == "qwen3-35b"


def test_local_uses_ollama_when_configured(monkeypatch):
    _reset_settings(monkeypatch, LOCAL_LLM_BACKEND="ollama",
                    OLLAMA_BASE_URL="http://localhost:11434/v1",
                    OLLAMA_MODEL="qwen3:35b")
    with patch("scripts.distill.llm_router._call_openai_compatible", return_value="ok") as mock_oa:
        from scripts.distill.llm_router import _call_local
        _call_local("prompt", "system")
    args = mock_oa.call_args
    assert args.kwargs["base_url"] == "http://localhost:11434/v1"


def test_cloud_uses_deepseek_when_configured(monkeypatch):
    _reset_settings(monkeypatch, CLOUD_LLM_BACKEND="deepseek",
                    DEEPSEEK_BASE_URL="https://api.deepseek.com/v1",
                    DEEPSEEK_MODEL="deepseek-chat",
                    DEEPSEEK_API_KEY="sk-test")
    with patch("scripts.distill.llm_router._call_openai_compatible", return_value="ok") as mock_oa:
        from scripts.distill.llm_router import _call_cloud
        _call_cloud("prompt", "system")
    args = mock_oa.call_args
    assert args.kwargs["base_url"] == "https://api.deepseek.com/v1"
    assert args.kwargs["api_key"] == "sk-test"

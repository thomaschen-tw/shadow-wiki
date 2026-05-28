from enum import Enum
import functools
import logging
import openai
import anthropic
import httpx
from scripts.config import get_settings, LocalBackend, CloudBackend

logger = logging.getLogger(__name__)


class TaskType(Enum):
    CLASSIFY    = "classify"
    SUMMARIZE   = "summarize"
    APPEND      = "append"
    QUERY       = "query"
    CREATE_PAGE = "create_page"
    SYNTHESIZE  = "synthesize"


_LOCAL_TASKS = {TaskType.CLASSIFY, TaskType.SUMMARIZE, TaskType.APPEND, TaskType.QUERY}


@functools.lru_cache(maxsize=8)
def _openai_client(base_url: str, api_key: str) -> openai.OpenAI:
    return openai.OpenAI(base_url=base_url, api_key=api_key or "not-needed")


@functools.lru_cache(maxsize=1)
def _anthropic_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().anthropic_api_key)


def _call_openai_compatible(
    base_url: str, api_key: str, model: str, prompt: str, system: str,
    extra_body: dict | None = None,
) -> str:
    s = get_settings()
    client = _openai_client(base_url, api_key or "")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        timeout=s.llm_timeout,
        extra_body=extra_body or {},
    )
    if not response.choices:
        raise ValueError(f"LLM returned no choices (model={model})")
    content = response.choices[0].message.content
    if content is None:
        raise ValueError(f"LLM returned null content (model={model})")
    return content


def _call_claude(prompt: str, system: str) -> str:
    client = _anthropic_client()
    response = client.messages.create(
        model=get_settings().claude_model,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    if not response.content:
        raise ValueError("Claude returned no content blocks")
    text = response.content[0].text
    if text is None:
        raise ValueError("Claude returned null text")
    return text


@functools.lru_cache(maxsize=1)
def _detect_local_backend() -> LocalBackend:
    s = get_settings()
    candidates = [
        (LocalBackend.LMSTUDIO, s.lmstudio_base_url),
        (LocalBackend.OLLAMA, s.ollama_base_url),
    ]
    for backend, base_url in candidates:
        try:
            httpx.get(f"{base_url}/models", timeout=2.0)
            logger.info("Auto-detected local LLM backend: %s (%s)", backend.value, base_url)
            return backend
        except Exception:
            continue
    raise RuntimeError(
        "No local LLM reachable. Start LM Studio or Ollama, "
        "or set LOCAL_LLM_BACKEND=lmstudio|ollama explicitly in .env."
    )


def _call_local(prompt: str, system: str) -> str:
    s = get_settings()
    backend = _detect_local_backend() if s.local_llm_backend == LocalBackend.AUTO else s.local_llm_backend
    extra = {"enable_thinking": s.enable_thinking}
    if backend == LocalBackend.LMSTUDIO:
        return _call_openai_compatible(
            base_url=s.lmstudio_base_url, api_key="", model=s.lmstudio_model,
            prompt=prompt, system=system, extra_body=extra,
        )
    return _call_openai_compatible(
        base_url=s.ollama_base_url, api_key="ollama", model=s.ollama_model,
        prompt=prompt, system=system, extra_body=extra,
    )


def _call_cloud(prompt: str, system: str) -> str:
    s = get_settings()
    if s.cloud_llm_backend == CloudBackend.CLAUDE:
        return _call_claude(prompt, system)
    if s.cloud_llm_backend == CloudBackend.QWEN_CLOUD:
        return _call_openai_compatible(
            base_url=s.qwen_cloud_base_url, api_key=s.dashscope_api_key,
            model=s.qwen_cloud_model, prompt=prompt, system=system,
        )
    return _call_openai_compatible(
        base_url=s.deepseek_base_url, api_key=s.deepseek_api_key,
        model=s.deepseek_model, prompt=prompt, system=system,
    )


def call_llm(
    task_type: TaskType,
    prompt: str,
    system: str = "You are a helpful assistant.",
) -> str:
    # When USE_CLOUD_LLM=false all tasks run locally (no cloud API calls)
    if not get_settings().use_cloud_llm or task_type in _LOCAL_TASKS:
        return _call_local(prompt, system)
    return _call_cloud(prompt, system)

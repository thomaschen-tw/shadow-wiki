from enum import Enum
import openai
import anthropic
from scripts.config import get_settings, LocalBackend, CloudBackend


class TaskType(Enum):
    CLASSIFY    = "classify"
    SUMMARIZE   = "summarize"
    APPEND      = "append"
    QUERY       = "query"
    CREATE_PAGE = "create_page"
    SYNTHESIZE  = "synthesize"


_LOCAL_TASKS = {TaskType.CLASSIFY, TaskType.SUMMARIZE, TaskType.APPEND, TaskType.QUERY}


def _call_openai_compatible(
    base_url: str, api_key: str, model: str, prompt: str, system: str
) -> str:
    client = openai.OpenAI(base_url=base_url, api_key=api_key or "not-needed")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content


def _call_claude(prompt: str, system: str) -> str:
    s = get_settings()
    client = anthropic.Anthropic(api_key=s.anthropic_api_key)
    response = client.messages.create(
        model=s.claude_model,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def _call_local(prompt: str, system: str) -> str:
    s = get_settings()
    if s.local_llm_backend == LocalBackend.LMSTUDIO:
        return _call_openai_compatible(
            base_url=s.lmstudio_base_url, api_key="", model=s.lmstudio_model,
            prompt=prompt, system=system,
        )
    return _call_openai_compatible(
        base_url=s.ollama_base_url, api_key="ollama", model=s.ollama_model,
        prompt=prompt, system=system,
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
    if task_type in _LOCAL_TASKS:
        return _call_local(prompt, system)
    return _call_cloud(prompt, system)

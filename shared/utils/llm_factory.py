"""
shared/utils/llm_factory.py
统一 LLM 初始化，支持 OpenAI / 通义千问 / Z.AI / vLLM / Ollama
新增 provider 只需在 PROVIDER_REGISTRY 加一行，不改代码逻辑
"""
import os
from langchain_openai import ChatOpenAI
from shared.config.settings import settings
from pydantic import SecretStr

# ── Provider 注册表（新增 provider 只改这里）──
PROVIDER_REGISTRY = {
    "openai": {
        "api_key_env": "OPENAI_API_KEY",
        "base_url_env": "OPENAI_BASE_URL",
        "base_url_default": "https://api.openai.com/v1",
    },
    "qwen": {
        "api_key_env": "DASHSCOPE_API_KEY",
        "base_url_env": "DASHSCOPE_BASE_URL",
        "base_url_default": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
    "zai": {
        "api_key_env": "ZAI_API_KEY",
        "base_url_env": "ZAI_BASE_URL",
        "base_url_default": "https://api.z.ai/v1",
    },
    "vllm": {
        "api_key_env": "",                            # vLLM 默认不需要 key
        "base_url_env": "VLLM_BASE_URL",
        "base_url_default": "http://localhost:8000/v1",
    },
    "ollama": {
        "api_key_env": "",                            # Ollama 不需要 key
        "base_url_env": "OLLAMA_BASE_URL",
        "base_url_default": "http://localhost:11434/v1",
    },
}


def get_llm(model_type: str = "main", temperature: float | None = None, **kwargs) -> ChatOpenAI:
    """
    获取 LLM 实例。provider 从 LLM_PROVIDER 环境变量读取。

    model_type: "main" | "judge" | "fast"
    新增 provider 用法：
      LLM_PROVIDER=vllm VLLM_BASE_URL=http://gpu-server:8000/v1 python main.py
      LLM_PROVIDER=ollama MAIN_MODEL=qwen2.5:7b python main.py
    """
    model_map = {
        "main": settings.llm.main_model,
        "judge": settings.llm.judge_model,
        "fast": settings.llm.fast_model,
    }
    model_name = model_map.get(model_type, settings.llm.main_model)
    temp = temperature if temperature is not None else settings.llm.temperature

    # 默认超时 10s，调用方可通过 kwargs 覆盖
    if "timeout" not in kwargs and "request_timeout" not in kwargs:
        kwargs["timeout"] = 10

    # ── 查表获取 provider 配置 ──
    provider = settings.llm.provider
    cfg = PROVIDER_REGISTRY.get(provider)
    if cfg is None:
        raise ValueError(
            f"不支持的 LLM provider: {provider}。"
            f"已注册: {list(PROVIDER_REGISTRY.keys())}。"
            f"新增 provider 请在 llm_factory.py 的 PROVIDER_REGISTRY 加一行。"
        )

    api_key = os.getenv(cfg["api_key_env"], "") if cfg["api_key_env"] else ""
    base_url = os.getenv(cfg["base_url_env"], cfg["base_url_default"]) if cfg["base_url_env"] else cfg["base_url_default"]

    return ChatOpenAI(
        model=model_name,
        temperature=temp,
        api_key=SecretStr(api_key),
        base_url=base_url,
        **kwargs,
    )

"""
shared/config/settings.py
统一配置管理，所有项目共用
"""
import os
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


class LLMConfig(BaseModel):
    provider: str = os.getenv("LLM_PROVIDER", "openai")
    main_model: str = os.getenv("MAIN_MODEL", "gpt-4o")
    judge_model: str = os.getenv("JUDGE_MODEL", "gpt-4o")
    fast_model: str = os.getenv("FAST_MODEL", "gpt-4o-mini")
    
    # TODO: 这里的 API Key 和 Base URL 可以根据 provider 进行区分，或者直接在 get_llm 函数中读取环境变量，这里先放在一起方便管理
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    dashscope_api_key: str = os.getenv("DASHSCOPE_API_KEY", "")
    dashscope_base_url: str = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    zai_api_key: str = os.getenv("ZAI_API_KEY", "")
    zai_base_url: str = os.getenv("ZAI_BASE_URL", "https://api.zai.com/v1")
    
    temperature: float = 0.7
    max_tokens: int = 2048


class MapConfig(BaseModel):
    amap_api_key: str = os.getenv("AMAP_API_KEY", "")


class AppConfig(BaseModel):
    llm: LLMConfig = LLMConfig()
    map: MapConfig = MapConfig()
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    data_dir: str = "data"
    output_dir: str = "outputs"


# 全局单例
settings = AppConfig()

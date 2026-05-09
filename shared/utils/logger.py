"""
shared/utils/logger.py
统一日志
"""
import sys
from loguru import logger
from shared.config.settings import settings

logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> - {message}",
    level=settings.log_level,
    colorize=True,
)
logger.add("logs/app.log", rotation="10 MB", retention="7 days", level="DEBUG")

__all__ = ["logger"]

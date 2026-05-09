"""
shared/utils/metrics.py
轻量级性能追踪，记录各节点耗时和 Token 消耗
"""
import time
import functools
from dataclasses import dataclass, field
from typing import Optional
from shared.utils.logger import logger

# dataclass 是 Python 3.7 引入的一个装饰器，用于简化类的定义，自动生成 __init__、__repr__、__eq__ 等方法，非常适合用来定义数据结构。
# 这里定义 NodeMetrics 类，记录每个节点的性能指标。
@dataclass
class NodeMetrics:
    node_name: str
    latency_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    success: bool = True
    error: Optional[str] = None


# 本次会话的 metrics 列表（生产环境应写入 Prometheus 或 ClickHouse）
# 怎么理解（生产环境应写入 Prometheus 或 ClickHouse），意思是这个列表只是一个临时存储，
# 实际使用中应该将这些数据发送到一个持久化的监控系统（如 Prometheus）或数据库（如 ClickHouse）进行存储和分析，而不是仅保存在内存中的列表里。
_session_metrics: list[NodeMetrics] = []


def track_node(node_name: str):
    """
    装饰器：自动记录节点执行耗时。
    生产环境可在此上报 Prometheus metrics。
    """
    def decorator(fn):
        @functools.wraps(fn)
        async def async_wrapper(state, *args, **kwargs):
            start = time.perf_counter()
            try:
                result = await fn(state, *args, **kwargs)
                latency = (time.perf_counter() - start) * 1000
                logger.info(f"[metrics] {node_name} latency={latency:.1f}ms")
                _session_metrics.append(NodeMetrics(node_name, latency))
                return result
            except Exception as e:
                latency = (time.perf_counter() - start) * 1000
                _session_metrics.append(NodeMetrics(node_name, latency, success=False, error=str(e)))
                raise

        @functools.wraps(fn)
        def sync_wrapper(state, *args, **kwargs):
            start = time.perf_counter()
            try:
                result = fn(state, *args, **kwargs)
                latency = (time.perf_counter() - start) * 1000
                logger.info(f"[metrics] {node_name} latency={latency:.1f}ms")
                _session_metrics.append(NodeMetrics(node_name, latency))
                return result
            except Exception as e:
                latency = (time.perf_counter() - start) * 1000
                _session_metrics.append(NodeMetrics(node_name, latency, success=False, error=str(e)))
                raise

        import asyncio
        if asyncio.iscoroutinefunction(fn):
            return async_wrapper
        return sync_wrapper
    return decorator


def reset_metrics() -> None:
    """清空本次会话的 metrics 列表，用于单轮 benchmark 隔离"""
    _session_metrics.clear()


def get_session_summary() -> dict:
    """返回本次会话的性能摘要"""
    if not _session_metrics:
        return {}
    total_latency = sum(m.latency_ms for m in _session_metrics)
    return {
        "total_latency_ms": round(total_latency, 1),
        "nodes": [
            {"node": m.node_name, "latency_ms": round(m.latency_ms, 1), "success": m.success}
            for m in _session_metrics
        ],
    }
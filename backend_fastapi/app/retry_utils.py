"""重试工具模块 - 基于 tenacity 提供指数退避重试

公开 API 与原手写实现保持一致：
- RetryConfig / calculate_delay
- retry_async / retry_sync
- with_retry
- RETRY_CONFIG_DEFAULT / RETRY_CONFIG_LLM_API / RETRY_CONFIG_KIMI
"""

from __future__ import annotations

import asyncio
import functools
import logging
import random
from typing import Any, Callable, TypeVar, cast

from tenacity import (
    AsyncRetrying,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryConfig:
    """重试配置

    Args:
        max_retries: 最大重试次数（不含首次尝试）
        base_delay: 基础延迟（秒）
        max_delay: 最大延迟（秒）
        exponential_base: 指数基数
        jitter: 是否添加随机抖动
        retryable_exceptions: 可重试的异常类型
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.retryable_exceptions = retryable_exceptions


def calculate_delay(attempt: int, config: RetryConfig) -> float:
    """计算重试延迟：min(base_delay * base^attempt, max_delay)，可选±20%抖动。"""
    delay = config.base_delay * (config.exponential_base**attempt)
    delay = min(delay, config.max_delay)

    if config.jitter:
        jitter_factor = 0.8 + random.random() * 0.4
        delay *= jitter_factor

    return delay


def _build_retrying(
    config: RetryConfig,
    func: Callable[..., Any],
    on_retry: Callable[[int, Exception, float], None] | None,
    retried: list[int],
    *,
    is_async: bool,
) -> AsyncRetrying | Retrying:
    """基于配置构造 tenacity Retrying/AsyncRetrying。

    retried: 单元素列表，记录实际发生的重试次数（用于耗尽后的 error 日志判定）。
    """

    def _wait(retry_state: Any) -> float:
        return calculate_delay(retry_state.attempt_number - 1, config)

    def _before_sleep(retry_state: Any) -> None:
        retried[0] += 1
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        delay = retry_state.next_action.sleep if retry_state.next_action else 0.0
        logger.warning(
            "Function %s failed (attempt %d/%d). Retrying in %.2fs. Error: %s",
            getattr(func, "__name__", func),
            retry_state.attempt_number,
            config.max_retries + 1,
            delay,
            exc,
        )
        if on_retry:
            on_retry(retry_state.attempt_number, exc, delay)

    cls: type[AsyncRetrying] | type[Retrying] = AsyncRetrying if is_async else Retrying
    return cls(
        stop=stop_after_attempt(config.max_retries + 1),
        wait=_wait,
        retry=retry_if_exception_type(config.retryable_exceptions),
        before_sleep=_before_sleep,
        reraise=True,
    )


async def retry_async(
    func: Callable[..., Any],
    *args: Any,
    config: RetryConfig | None = None,
    on_retry: Callable[[int, Exception, float], None] | None = None,
    **kwargs: Any,
) -> Any:
    """异步函数重试包装器。

    Raises:
        Exception: 重试耗尽或异常不可重试时，抛出原始异常
    """
    config = config or RetryConfig()
    retried = [0]
    retrying = cast(
        AsyncRetrying, _build_retrying(config, func, on_retry, retried, is_async=True)
    )

    async def _invoke() -> Any:
        return await func(*args, **kwargs)

    try:
        return await retrying(_invoke)
    except Exception:
        if retried[0] >= config.max_retries:
            logger.error(
                "Function %s failed after %d attempts.",
                getattr(func, "__name__", func),
                config.max_retries + 1,
            )
        raise


def retry_sync(
    func: Callable[..., Any],
    *args: Any,
    config: RetryConfig | None = None,
    on_retry: Callable[[int, Exception, float], None] | None = None,
    **kwargs: Any,
) -> Any:
    """同步函数重试包装器。"""
    config = config or RetryConfig()
    retried = [0]
    retrying = cast(
        Retrying, _build_retrying(config, func, on_retry, retried, is_async=False)
    )
    try:
        return retrying(lambda: func(*args, **kwargs))
    except Exception:
        if retried[0] >= config.max_retries:
            logger.error(
                "Function %s failed after %d attempts.",
                getattr(func, "__name__", func),
                config.max_retries + 1,
            )
        raise


def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """重试装饰器（支持同步和异步函数）。

    Example:
        @with_retry(max_retries=3, base_delay=1.0)
        async def my_async_function():
            pass
    """
    config = RetryConfig(
        max_retries=max_retries,
        base_delay=base_delay,
        max_delay=max_delay,
        retryable_exceptions=retryable_exceptions,
    )

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> T:
            return await retry_async(func, *args, config=config, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> T:
            return retry_sync(func, *args, config=config, **kwargs)

        if asyncio.iscoroutinefunction(func):
            return cast(Callable[..., T], async_wrapper)
        else:
            return cast(Callable[..., T], sync_wrapper)

    return decorator


# 预定义的重试配置
RETRY_CONFIG_DEFAULT = RetryConfig(max_retries=3, base_delay=1.0)
RETRY_CONFIG_LLM_API = RetryConfig(
    max_retries=3,
    base_delay=1.0,
    max_delay=30.0,
    retryable_exceptions=(ConnectionError, TimeoutError, Exception),
)
RETRY_CONFIG_KIMI = RetryConfig(
    max_retries=3,
    base_delay=2.0,
    max_delay=30.0,
    retryable_exceptions=(ConnectionError, TimeoutError, Exception),
)


__all__ = [
    "RetryConfig",
    "calculate_delay",
    "retry_async",
    "retry_sync",
    "with_retry",
    "RETRY_CONFIG_DEFAULT",
    "RETRY_CONFIG_LLM_API",
    "RETRY_CONFIG_KIMI",
]

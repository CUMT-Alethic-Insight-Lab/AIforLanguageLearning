"""Celery 应用配置"""

from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

try:
    from celery import Celery
    from kombu import Exchange, Queue

    CELERY_AVAILABLE = True
except ImportError:
    CELERY_AVAILABLE = False

broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

task_routes = {
    "app.infrastructure.messaging.tasks.grade_essay_task": {
        "queue": "urgent_tasks",
        "routing_key": "urgent.essay",
    },
    "app.infrastructure.messaging.tasks.generate_daily_vocab_task": {
        "queue": "default_tasks",
        "routing_key": "default.vocab",
    },
    "app.infrastructure.messaging.analytics_tasks.generate_all_daily_summaries_task": {
        "queue": "batch_tasks",
        "routing_key": "batch.analytics.daily",
    },
    "app.infrastructure.messaging.analytics_tasks.run_tiered_analysis_task": {
        "queue": "batch_tasks",
        "routing_key": "batch.analytics.tiered",
    },
    "app.infrastructure.messaging.analytics_tasks.generate_class_weekly_report_task": {
        "queue": "batch_tasks",
        "routing_key": "batch.analytics.weekly",
    },
}

if CELERY_AVAILABLE:
    dlx = Exchange("dlx", type="direct")
    dlq = Queue("dlq", exchange=dlx, routing_key="dlq")

    queue_args = {
        "x-max-priority": 10,
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "dlq",
    }

    task_queues = (
        Queue("urgent_tasks", Exchange("urgent"), routing_key="urgent.#", queue_arguments=queue_args),
        Queue(
            "default_tasks", Exchange("default"), routing_key="default.#", queue_arguments=queue_args
        ),
        Queue("batch_tasks", Exchange("batch"), routing_key="batch.#", queue_arguments=queue_args),
        dlq,
    )
else:
    task_queues = ()

app: Any | None = None
if CELERY_AVAILABLE:
    app = Celery("aifl_tasks", broker=broker_url, backend=result_backend)
    app.conf.update(
        task_queues=task_queues,
        task_routes=task_routes,
        task_default_queue="default_tasks",
        task_default_exchange="default",
        task_default_routing_key="default.any",
        worker_prefetch_multiplier=1,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_retry_backoff=True,
        task_retry_max_retries=3,
        task_always_eager=os.getenv("CELERY_DEMO_EAGER", "1") == "1",
    )
else:
    class _DummyBoundTask:
        def retry(self, *, exc: Exception, countdown: int = 0) -> None:
            raise exc

    class _EagerResult:
        def __init__(self, result: Any) -> None:
            self.id = f"local-{uuid4().hex[:8]}"
            self.result = result

    class _DummyTask:
        def __init__(self, func: Any) -> None:
            self.func = func

        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            return self.run(*args, **kwargs)

        def run(self, *args: Any, **kwargs: Any) -> Any:
            return self.func(_DummyBoundTask(), *args, **kwargs)

        def delay(self, *args: Any, **kwargs: Any) -> _EagerResult:
            return _EagerResult(self.run(*args, **kwargs))

    class _DummyCelery:
        def task(self, *args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
            def decorator(func: Any) -> _DummyTask:
                return _DummyTask(func)

            return decorator

    app = _DummyCelery()

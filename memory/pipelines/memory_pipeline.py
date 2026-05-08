from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Final

from gateway.memory_jobs import process_memory_task
from memory import memory_service

logger = logging.getLogger(__name__)
DEFAULT_MEMORY_SCOPE: Final[str] = "global"


@dataclass(slots=True)
class MemoryTask:
    memory_scope: str
    user_text: str
    assistant_text: str


@dataclass(frozen=True, slots=True)
class MemoryPipelineConfig:
    queue_max_size: int
    drain_timeout_seconds: float
    backend: str
    redis_url: str
    rq_queue_name: str
    worker_name: str = "memory-pipeline-worker"

    @classmethod
    def from_env(cls) -> "MemoryPipelineConfig":
        queue_max_size = max(100, int(os.getenv("MEMORY_PIPELINE_MAX_QUEUE") or "5000"))
        drain_timeout_seconds = max(1.0, float(os.getenv("MEMORY_PIPELINE_DRAIN_TIMEOUT_SECONDS") or "5"))
        backend = (os.getenv("MEMORY_QUEUE_BACKEND") or "inprocess").strip().lower()
        return cls(
            queue_max_size=queue_max_size,
            drain_timeout_seconds=drain_timeout_seconds,
            backend=backend,
            redis_url=(os.getenv("MEMORY_REDIS_URL") or "redis://127.0.0.1:6379/0").strip(),
            rq_queue_name=(os.getenv("MEMORY_RQ_QUEUE") or "memory").strip() or "memory",
        )


@dataclass(slots=True)
class MemoryPipelineStats:
    enqueued_count: int = 0
    processed_count: int = 0
    dropped_count: int = 0
    error_count: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "enqueued_count": self.enqueued_count,
            "processed_count": self.processed_count,
            "dropped_count": self.dropped_count,
            "error_count": self.error_count,
        }


class MemoryPipeline:
    """Background memory write pipeline."""

    def __init__(self, config: MemoryPipelineConfig | None = None) -> None:
        self._config = config or MemoryPipelineConfig.from_env()
        self._queue: asyncio.Queue[MemoryTask | None] = asyncio.Queue(maxsize=self._config.queue_max_size)
        self._worker_task: asyncio.Task[None] | None = None
        self._start_stop_lock = asyncio.Lock()
        self._started = False
        self._stats = MemoryPipelineStats()
        self._rq_queue = None
        self._rq_backend_enabled = False

    @property
    def stats(self) -> dict[str, int]:
        return self._stats.as_dict()

    @property
    def queue_size(self) -> int:
        if self._rq_backend_enabled and self._rq_queue is not None:
            try:
                return int(self._rq_queue.count)
            except Exception:
                return 0
        return self._queue.qsize()

    async def start(self) -> None:
        async with self._start_stop_lock:
            if self._started:
                return
            if self._config.backend == "rq":
                self._rq_backend_enabled = self._try_init_rq_backend()
            if self._rq_backend_enabled:
                self._started = True
                logger.info(json.dumps({"event": "memory_pipeline_start", "backend": "rq", "rq_queue": self._config.rq_queue_name}))
                return
            if self._worker_task and not self._worker_task.done():
                self._started = True
                return
            self._started = True
            self._worker_task = asyncio.create_task(self._worker_loop(), name=self._config.worker_name)
            logger.info(json.dumps({"event": "memory_pipeline_start", "backend": "inprocess", "queue_max_size": self._config.queue_max_size}))

    async def stop(self) -> None:
        async with self._start_stop_lock:
            if self._rq_backend_enabled:
                self._started = False
                return
            if not self._worker_task:
                self._started = False
                return
            worker = self._worker_task
            self._started = False
            self._worker_task = None
            try:
                self._queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
            try:
                await asyncio.wait_for(worker, timeout=self._config.drain_timeout_seconds)
            except asyncio.TimeoutError:
                worker.cancel()
                try:
                    await worker
                except asyncio.CancelledError:
                    pass
                logger.warning(json.dumps({"event": "memory_pipeline_stop_timeout", "drain_timeout_seconds": self._config.drain_timeout_seconds, "remaining_queue_size": self._queue.qsize()}))

    def enqueue(self, *, memory_scope: str, user_text: str, assistant_text: str) -> None:
        task = self._build_task(memory_scope=memory_scope, user_text=user_text, assistant_text=assistant_text)
        if not task:
            return
        if self._rq_backend_enabled and self._rq_queue is not None:
            try:
                self._rq_queue.enqueue(process_memory_task, {"memory_scope": task.memory_scope, "user_text": task.user_text, "assistant_text": task.assistant_text})
                self._stats.enqueued_count += 1
                return
            except Exception as exc:
                logger.warning("RQ enqueue failed, falling back to local queue: %s", exc)
        try:
            self._queue.put_nowait(task)
            self._stats.enqueued_count += 1
        except asyncio.QueueFull:
            self._stats.dropped_count += 1
            logger.warning(json.dumps({"event": "memory_pipeline_queue_full", "queue_max_size": self._config.queue_max_size, "dropped_count": self._stats.dropped_count}))

    def _build_task(self, *, memory_scope: str, user_text: str, assistant_text: str) -> MemoryTask | None:
        normalized_user_text = (user_text or "").strip()
        normalized_assistant_text = (assistant_text or "").strip()
        if not normalized_user_text and not normalized_assistant_text:
            return None
        normalized_scope = (memory_scope or DEFAULT_MEMORY_SCOPE).strip() or DEFAULT_MEMORY_SCOPE
        return MemoryTask(memory_scope=normalized_scope, user_text=normalized_user_text, assistant_text=normalized_assistant_text)

    async def _worker_loop(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                if item is None:
                    break
                await self._process_item(item)
                self._stats.processed_count += 1
            except Exception as exc:
                self._stats.error_count += 1
                logger.exception("Memory pipeline worker error: %s", exc)
            finally:
                self._queue.task_done()

    async def _process_item(self, item: MemoryTask) -> None:
        await asyncio.to_thread(memory_service.maybe_store_from_user_turn, text=item.user_text, memory_scope=item.memory_scope)
        await asyncio.to_thread(memory_service.maybe_store_from_assistant_turn, text=item.assistant_text, memory_scope=item.memory_scope)

    def _try_init_rq_backend(self) -> bool:
        try:
            from redis import Redis
            from rq import Queue
        except Exception as exc:
            logger.warning("RQ backend requested but dependencies unavailable: %s", exc)
            return False
        try:
            conn = Redis.from_url(self._config.redis_url)
            conn.ping()
            self._rq_queue = Queue(self._config.rq_queue_name, connection=conn)
            return True
        except Exception as exc:
            logger.warning("RQ backend requested but Redis unavailable: %s", exc)
            self._rq_queue = None
            return False


memory_pipeline = MemoryPipeline()


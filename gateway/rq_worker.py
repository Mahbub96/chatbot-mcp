from __future__ import annotations

import os


def main() -> None:
    try:
        from redis import Redis
        from rq import Connection, Queue, Worker
    except Exception as exc:
        raise RuntimeError(
            "RQ worker dependencies are missing. Install requirements with `pip install -r requirements.txt`."
        ) from exc

    redis_url = os.getenv("MEMORY_REDIS_URL") or "redis://127.0.0.1:6379/0"
    queue_name = (os.getenv("MEMORY_RQ_QUEUE") or "memory").strip() or "memory"
    conn = Redis.from_url(redis_url)
    with Connection(conn):
        queue = Queue(queue_name)
        worker = Worker([queue])
        worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()


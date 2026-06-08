import os
import logging
import time

import redis

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("notes-worker")

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_CHANNEL = "notes-events"


def run() -> None:
    backoff = 1
    while True:
        try:
            client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
            client.ping()
            pubsub = client.pubsub()
            pubsub.subscribe(REDIS_CHANNEL)
            log.info("worker subscribed to channel '%s'", REDIS_CHANNEL)
            backoff = 1
            for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                data = message["data"]
                client.lpush("notes-events-log", data)
                client.ltrim("notes-events-log", 0, 99)
                log.info("processed event: %s", data)
        except redis.RedisError as exc:
            log.warning("redis error: %s — retrying in %ss", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)


if __name__ == "__main__":
    run()

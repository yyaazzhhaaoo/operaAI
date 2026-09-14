import os
import redis
from redis.backoff import ExponentialBackoff
from redis.retry import Retry
from redis.exceptions import ConnectionError
from dotenv import load_dotenv

load_dotenv(override=False)

_pool = redis.ConnectionPool(
    host=os.getenv("REDIS_HOST"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    password=os.getenv("REDIS_PASSWORD"),
    db=os.getenv("REDIS_DB"),
    max_connections=50,
    socket_timeout=2,
    socket_connect_timeout=2,
    health_check_interval=30,
    decode_responses=True,
    retry=Retry(ExponentialBackoff(cap=10, base=1), 3),
    retry_on_error=[ConnectionError],
)

def get_redis():
    return redis.Redis(connection_pool=_pool)
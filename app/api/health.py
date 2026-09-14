from app.api import api_bp
from app.response import ok
from app.redis_client import get_redis


@api_bp.route("/health",methods=["GET"])
def health():
    redis = get_redis()
    result = redis.get("id")
    return ok(result)
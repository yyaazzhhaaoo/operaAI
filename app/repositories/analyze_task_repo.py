# -*- coding: utf-8 -*-
"""分析任务状态在 redis 里的读写（《5-接口清单》3.1）。

任务是一次性的、1 小时后自动过期，也从不按内容检索，所以用 redis hash
而不是建表：不值得占一张表加一次迁移。

**每个字段单独存**，所以写入前必须把值压成 redis 能编码的形态。redis-py 的
encoder 只收 bytes/str/int/float，**传 None 会抛 DataError**——旧实现把
result=None 直接塞进 hset，B2 因此在文件存在时恒 500。_encode() 统一兜住。
"""

import json

from app.redis_client import get_redis

TASK_TTL = 3600                      # 任务结果保留 1 小时
TASK_PREFIX = "analyze:task:"


def _client():
    """每次现取一个客户端。

    get_redis() 只是把一个已存在的连接池包成 Redis 对象，不建连接，
    开销可以忽略；这样写也让本模块在 import 期没有副作用，便于测试替换。
    """
    return get_redis()


def _key(task_id: str) -> str:
    return f"{TASK_PREFIX}{task_id}"


def _encode(value):
    """把 Python 值压成 redis 能编码的形态。

    None → 空串（`hgetall` 会把空串原样读回来，读侧再还原成 None）。
    布尔必须显式转换：isinstance(True, int) 为真，不转就会和整数 1 混淆，
    读回来分不清「true」和「1」。
    dict/list → JSON 文本，读侧 json.loads 还原。
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def create(task_id: str, ttl: int = TASK_TTL, **fields) -> None:
    """整体写入（B2 建任务时用）。"""
    key = _key(task_id)
    pipe = _client().pipeline()
    pipe.hset(key, mapping={k: _encode(v) for k, v in fields.items()})
    pipe.expire(key, ttl)
    pipe.execute()


def update(task_id: str, ttl: int = TASK_TTL, **fields) -> None:
    """局部更新字段，并续期。

    续期是刻意的：一个跑满 1 小时的任务，若每阶段更新都不续期，
    结果会在最后一个阶段写入前就过期，B4 永远取不到。
    """
    if not fields:
        return
    key = _key(task_id)
    pipe = _client().pipeline()
    pipe.hset(key, mapping={k: _encode(v) for k, v in fields.items()})
    pipe.expire(key, ttl)
    pipe.execute()


def get(task_id: str) -> dict | None:
    """读整个任务，把 progress 转回 int、result 反序列化回对象。

    读不到返回 None（任务不存在或已过期）。字段缺失或格式不对时给安全兜底值，
    不让一条脏数据把 B3 的轮询打成 500。
    """
    raw = _client().hgetall(_key(task_id))
    if not raw:
        return None

    task = dict(raw)

    try:
        task["progress"] = int(task.get("progress", 0))
    except (TypeError, ValueError):
        task["progress"] = 0

    raw_result = task.get("result")
    if raw_result:
        try:
            task["result"] = json.loads(raw_result)
        except (TypeError, json.JSONDecodeError):
            task["result"] = None
    else:
        task["result"] = None

    return task

# -*- coding: utf-8 -*-
"""示范库解析任务状态在 redis 里的读写。

与 analyze_task_repo 是**两份独立实现**，前缀也不同（`parse:demo:` vs
`analyze:task:`），这是刻意的：

- 那个模块服务着正在跑的 B2/B3/B4，本次改造一行不动它，避免把风险引到线上。
- 两边的状态词表本就不一样。B 组用 `queued/processing/done/failed`，而示范库
  前端 `startPolling`（demo_library.html）判的是 `parsed`/`error`。共用一个
  模块就得在读写两侧加分支，反而更容易串味。

代价是 _encode() 这类代码重复一份。少量重复换零风险，等两条链路的状态词表
真正统一了再合并。

任务一次性、1 小时后过期、从不按内容检索，所以同样用 redis hash 不建表。
"""

import json

from app.redis_client import get_redis

TASK_TTL = 3600                      # 解析任务保留 1 小时（与 B 组一致）
TASK_PREFIX = "parse:demo:"


def _client():
    """每次现取一个客户端。get_redis() 只包连接池、不建连接，开销可忽略。"""
    return get_redis()


def _key(task_id: str) -> str:
    return f"{TASK_PREFIX}{task_id}"


def _encode(value):
    """把 Python 值压成 redis 能编码的形态。

    None → 空串（`hgetall` 会把空串原样读回来，读侧再还原成 None）。
    布尔必须显式转换：isinstance(True, int) 为真，不转就会和整数 1 混淆，
    读回来分不清「true」和「1」。
    dict/list → JSON 文本，读侧 json.loads 还原。

    这段是照抄 analyze_task_repo 的：它的 docstring 记着一个真实事故——
    redis-py 的 encoder 只收 bytes/str/int/float，**传 None 会抛 DataError**，
    旧实现把 result=None 直接塞进 hset，B2 因此在文件存在时恒 500。
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def create(task_id: str, ttl: int = TASK_TTL, **fields) -> None:
    """整体写入（提交解析时建任务用）。"""
    key = _key(task_id)
    pipe = _client().pipeline()
    pipe.hset(key, mapping={k: _encode(v) for k, v in fields.items()})
    pipe.expire(key, ttl)
    pipe.execute()


def update(task_id: str, ttl: int = TASK_TTL, **fields) -> None:
    """局部更新字段，并续期。

    续期是刻意的：解析要跑 8–15 分钟，若每阶段更新都不续期、而 TTL 又恰好
    短于总时长，结果会在最后一个阶段写入前就过期，前端永远轮询不到 `parsed`。
    """
    if not fields:
        return
    key = _key(task_id)
    pipe = _client().pipeline()
    pipe.hset(key, mapping={k: _encode(v) for k, v in fields.items()})
    pipe.expire(key, ttl)
    pipe.execute()


def get(task_id: str) -> dict | None:
    """读整个任务，把 progress 转回 int。

    读不到返回 None（任务不存在或已过期）。字段缺失或格式不对时给安全兜底值，
    不让一条脏数据把轮询接口打成 500。
    """
    raw = _client().hgetall(_key(task_id))
    if not raw:
        return None

    task = dict(raw)

    try:
        task["progress"] = int(task.get("progress", 0))
    except (TypeError, ValueError):
        task["progress"] = 0

    # demo_id 也要转回 int：前端拿它跟列表里的 id 比。空串（未写入）保持 None，
    # 不硬转 0——0 是个合法 id，会把「没写」和「id=0」混为一谈。
    raw_demo_id = task.get("demo_id")
    if raw_demo_id:
        try:
            task["demo_id"] = int(raw_demo_id)
        except (TypeError, ValueError):
            task["demo_id"] = None
    else:
        task["demo_id"] = None

    return task

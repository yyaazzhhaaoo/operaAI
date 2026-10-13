# -*- coding: utf-8 -*-
"""临时脚本：验证 E2 的解析降级与真实往返。验完即删（Task 8）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import session_scope
from app.repositories import chat_repo
from app.services import coach_service

# ── 第一部分：纯函数，不碰网络也不碰库 ────────────────────────
# 1. 正常 JSON
reply, meta = coach_service.parse_reply(
    '{"reply":"我们先听听音准。","strategy":"引导","emotion":"neutral",'
    '"quick_replies":["再看一遍曲线","直接告诉我"]}')
print("1)", reply, meta)
assert reply == "我们先听听音准。"
assert meta["strategy"] == "引导" and meta["emotion"] == "neutral"
assert meta["quick_replies"] == ["再看一遍曲线", "直接告诉我"]

# 2. 被 markdown 代码块包住也要能解
reply, meta = coach_service.parse_reply(
    '```json\n{"reply":"好的","strategy":"鼓励","emotion":"positive","quick_replies":[]}\n```')
assert reply == "好的" and meta["strategy"] == "鼓励", f"实际 {reply!r} {meta}"
print("2) 剥掉代码块 ✓")

# 3. 完全不是 JSON → 降级：整段当 reply，其余给默认值
reply, meta = coach_service.parse_reply("你的气息不太稳，我们慢慢来。")
assert reply == "你的气息不太稳，我们慢慢来。"
assert meta["strategy"] == "引导" and meta["emotion"] == "neutral"
assert meta["quick_replies"] == []
print("3) 非 JSON 降级 ✓")

# 4. JSON 合法但 strategy 越界 → 只重置该字段
reply, meta = coach_service.parse_reply(
    '{"reply":"嗯","strategy":"随便写的","emotion":"neutral","quick_replies":[]}')
assert reply == "嗯" and meta["strategy"] == "引导", f"实际 {meta}"
print("4) strategy 越界降级 ✓")

# 5. reply 缺失 → 整段降级
reply, meta = coach_service.parse_reply('{"strategy":"引导"}')
assert reply == '{"strategy":"引导"}', "reply 缺失时该把原文当回复，不能丢内容"
print("5) reply 缺失降级 ✓")

# 6. quick_replies 不是数组 → 置空而不是崩
reply, meta = coach_service.parse_reply(
    '{"reply":"嗯","strategy":"引导","emotion":"neutral","quick_replies":"再看看"}')
assert meta["quick_replies"] == []
print("6) quick_replies 类型异常降级 ✓")

# ── 第二部分：真实往返 + 落库 ────────────────────────────────
with session_scope() as db:
    before = len(chat_repo.get_recent(db, 48, 200))
    out = coach_service.chat(db, 48, "这一句总是唱不准")
    print("7) 真实回复:", out["reply"][:60])
    print("   strategy/emotion:", out["strategy"], "/", out["emotion"])
    assert set(out) == {"reply", "strategy", "emotion", "quick_replies"}
    assert out["reply"].strip()

    after = chat_repo.get_recent(db, 48, 200)
    assert len(after) == before + 2, f"应双写两条，实际多了 {len(after)-before}"
    assert after[-2].role == "user" and after[-2].content == "这一句总是唱不准"
    assert after[-2].context_snapshot is None, "user 那条不写快照"
    assert after[-1].role == "assistant"
    snap = after[-1].context_snapshot
    print("8) 快照键:", sorted(snap))
    assert snap["strategy"] == out["strategy"]
    assert snap["本次偏差"] is None, "无源项在快照里也要如实写 None"
    assert snap["RAG 检索"] is None
    assert "学生画像" in snap and "薄弱技法" in snap

    # 清理，脚本可重复执行
    for m in after[-2:]:
        db.delete(m)

# ── 第三部分：LLM 不可达时不落库 ─────────────────────────────
from app.config import settings
from app.common.errors import BusinessError

orig = settings.llm_base_url
try:
    settings.llm_base_url = "http://127.0.0.1:1/v1"
    with session_scope() as db:
        n_before = len(chat_repo.get_recent(db, 48, 200))
    try:
        with session_scope() as db:
            coach_service.chat(db, 48, "这条不该落库")
        raise AssertionError("LLM 不可达时应抛 BusinessError")
    except BusinessError as e:
        print("9) 不可达时抛出:", type(e).__name__, e.message)
        assert e.code == 503, f"实际 {e.code}"
    with session_scope() as db:
        n_after = len(chat_repo.get_recent(db, 48, 200))
    assert n_after == n_before, f"失败时不该落库：{n_before} → {n_after}"
    print("9) 失败未落库 ✓")
finally:
    settings.llm_base_url = orig

print("全部通过")

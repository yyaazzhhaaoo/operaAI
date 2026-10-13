# -*- coding: utf-8 -*-
"""临时脚本：验证 E3 历史回读。验完即删（Task 8）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import session_scope
from app.schemas.coach import ChatMessageOut
from app.services import coach_service

with session_scope() as db:
    rows = coach_service.history(db, 48)
    print("1) 历史条数:", len(rows))
    assert rows, "库里本来就有 student_id=48 的行，不该为空"

    # 正序：id 递增（created_at 无小数秒，同一秒内会并列，故用 id 近似）
    ids = [r["id"] for r in rows]
    assert ids == sorted(ids), f"应按时间正序，实际 {ids}"
    print("2) 正序 ✓")

    # 字段齐且能被 schema 吃下
    out = ChatMessageOut.model_validate(rows[0])
    assert set(out.model_dump()) == {"id", "role", "content", "created_at"}
    print("3) 首条:", out.role, repr(out.content[:30]))

    # 不含 context_snapshot：那是审计用的内部字段，不该给前端
    assert "context_snapshot" not in rows[0], "快照不对外暴露"
    print("4) 未泄漏 context_snapshot ✓")

    # 从没聊过的学生 → 空列表，不是报错
    assert coach_service.history(db, 2) == []
    print("5) 学生 2 无历史 → [] ✓")

    # limit 生效
    assert len(coach_service.history(db, 48, limit=1)) == 1
    print("6) limit 生效 ✓")

print("全部通过")

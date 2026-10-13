# -*- coding: utf-8 -*-
"""临时脚本：验证 coach 用到的四个仓储函数。验完即删（Task 8）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import session_scope
from app.repositories import bkt_history_repo, chat_repo, practice_records_repo, user_repo

with session_scope() as db:
    # 1. user_id → students.id。s01(users.id=50) → students.id=48
    sid = user_repo.get_student_id_by_user_id(db, 50)
    print("1) users.id=50 →", sid)
    assert sid == 48, f"期望 48，实际 {sid}"

    # 2. 不存在的用户 → None（不是抛异常）
    assert user_repo.get_student_id_by_user_id(db, 999999) is None
    print("2) 不存在的用户 → None ✓")

    # 3. 学生档案
    prof = user_repo.get_student_profile(db, 48)
    print("3) 档案:", prof)
    assert prof and prof[0] == 48 and prof[1] == "李小燕", f"实际 {prof}"

    # 4. 每技法最新一行：学生 48 有 8 个技法
    rows = bkt_history_repo.get_latest_per_skill_for_student(db, 48)
    skills = sorted(r.skill for r in rows)
    print("4) 技法数:", len(rows), skills)
    assert len(rows) == 8, f"期望 8 个技法，实际 {len(rows)}"
    assert len(set(skills)) == 8, "出现了重复技法，DISTINCT ON 没生效"

    # 5. 无数据的学生 → 空列表而不是报错
    assert bkt_history_repo.get_latest_per_skill_for_student(db, 2) == []
    print("5) 无数据学生 → [] ✓")

    # 6. 最新练习记录：学生 48 无记录（这 6 条都属于 50-55）
    assert practice_records_repo.get_latest_for_student(db, 48) is None
    print("6) 学生 48 无练习记录 → None ✓")
    rec = practice_records_repo.get_latest_for_student(db, 50)
    print("6) 学生 50 最新一条:", rec and (rec.id, rec.created_at))

    # 7. 对话读写（在事务里做，退出时 session_scope 提交，脚本末尾手动清理）
    before = len(chat_repo.get_recent(db, 48, 100))
    chat_repo.add_message(db, 48, "user", "临时验证消息", None)
    chat_repo.add_message(db, 48, "assistant", "临时验证回复", {"strategy": "引导"})
    after = chat_repo.get_recent(db, 48, 100)
    print("7) 落库前后:", before, "→", len(after))
    assert len(after) == before + 2
    assert after[-1].context_snapshot == {"strategy": "引导"}
    assert [m.role for m in after[-2:]] == ["user", "assistant"], "顺序应是先 user 后 assistant"

    # 清掉本次写入的两条，脚本可重复执行
    for m in after[-2:]:
        db.delete(m)
    print("清理完毕")

print("全部通过")

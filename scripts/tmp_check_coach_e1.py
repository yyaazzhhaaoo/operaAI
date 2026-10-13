# -*- coding: utf-8 -*-
"""临时脚本：验证 E1 的 context 组装与身份校验。验完即删（Task 8）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.common.errors import BusinessError
from app.db import session_scope
from app.schemas.coach import CoachContextOut
from app.services import coach_service

with session_scope() as db:
    # 1. 有数据的学生（students.id=48 李小燕）
    ctx = coach_service.build_context(db, 48)
    print("1) 学生:", ctx["student"])
    assert ctx["student"]["id"] == 48
    assert ctx["student"]["display_name"] == "李小燕"
    assert len(ctx["bkt"]) == 8, f"BKT 应有 8 项，实际 {len(ctx['bkt'])}"
    assert len(ctx["weak_skills"]) == 3, "薄弱技法取 p_l 最低的 3 项"
    # 薄弱技法按 p_l 升序：第一项应是最低的
    assert ctx["weak_skills"][0]["p_l"] <= ctx["weak_skills"][-1]["p_l"]
    print("   薄弱技法:", ctx["weak_skills"])

    # 2. 三项无源字段是 None 而不是 []
    assert ctx["deviations"] is None, "逐字偏差无数据源，必须是 None"
    assert ctx["cdm"] is None
    assert ctx["rag"] is None
    print("2) 三项空位均为 None ✓")

    # 3. 学生 48 没有练习记录 → last_practice 为 None，且不报错
    assert ctx["last_practice"] is None, f"实际 {ctx['last_practice']}"
    print("3) last_practice=None ✓")

    # 4. 有练习记录的学生（students.id=50）
    ctx50 = coach_service.build_context(db, 50)
    print("4) 学生 50 last_practice:", ctx50["last_practice"])
    assert ctx50["last_practice"] is not None

    # 5. 出参 schema 能吃下这个 dict（字段名对得上）
    out = CoachContextOut.model_validate(ctx50)
    dumped = out.model_dump(mode="json")
    assert set(dumped) == {"student", "last_practice", "bkt", "weak_skills",
                           "deviations", "cdm", "rag"}
    print("5) schema 字段:", sorted(dumped))

    # 6. 身份校验：路径 student_id 与登录人对不上 → 403
    assert coach_service.resolve_student_id(db, 48, user_id=50) == 48
    print("6) 本人访问 ✓")
    try:
        coach_service.resolve_student_id(db, 49, user_id=50)
        raise AssertionError("跨学生访问应抛 403")
    except BusinessError as e:
        assert e.code == 403, f"实际 {e.code}"
        print("6) 跨学生访问 → 403 ✓")

    # 7. stu002（users.id=4）：role='student' 但 students 表里没有它那一行。
    #    @student_required 会放它进来，全靠 resolve_student_id 的这一条挡。
    try:
        coach_service.resolve_student_id(db, 48, user_id=4)
        raise AssertionError("无学生档案的账号应抛 403")
    except BusinessError as e:
        assert e.code == 403, f"实际 {e.code}"
        print("7) role=student 但无学生档案 → 403 ✓")

    # 7b. teacher01（users.id=2）在 students 表里**有**行（students.id=1），
    #     所以这一层只能靠「不是我那条」挡住。真正把教师拦在门外的是路由上的
    #     @student_required，这里只确认本函数的比对逻辑不误放行。
    try:
        coach_service.resolve_student_id(db, 48, user_id=2)
        raise AssertionError("跨学生访问应抛 403")
    except BusinessError as e:
        assert e.code == 403
        print("7b) teacher01 跨学生 → 403 ✓")

    # 8. 不存在的学生 id：与「别人的 id」一视同仁 → 403。
    #    实现里**故意不区分**「不存在」和「不是你的」——用 403/404 的差异
    #    去枚举库里有哪些学生，是不必要的泄漏面。
    try:
        coach_service.resolve_student_id(db, 999999, user_id=50)
        raise AssertionError("不存在的学生应抛 403")
    except BusinessError as e:
        assert e.code == 403, f"实际 {e.code}"
        print("8) 不存在的学生 → 403（不区分不存在/不是你的）✓")

print("全部通过")

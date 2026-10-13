# -*- coding: utf-8 -*-
"""AI 教练对话（模块3）的业务逻辑。

三个接口见《5-接口清单-V1.0》2.5；E2 的请求/响应契约见 3.3；
数据流见《2-系统设计说明》5.3。
"""
import json
import logging

from sqlalchemy.orm import Session

from app.common.errors import BusinessError
from app.models import ChatMessage, Segment
from app.repositories import (
    bkt_history_repo,
    chat_repo,
    practice_records_repo,
    user_repo,
)

logger = logging.getLogger(__name__)

# 拼进 prompt 的历史轮数。文档未规定——上限由延迟定，不是由 max_model_len 定：
# 该模型上下文有 65536，远不是瓶颈；真正的约束是历史越长 prompt 越长、
# 首字节越慢，而 PRD 3.2 卡的是 2 秒。
HISTORY_TURNS = 10

# 「薄弱技法」取 p_l 最低的几项
WEAK_SKILL_TOP_N = 3

# 约束条件：随每次请求发给模型的固定条款，也原样写进 context_snapshot。
# 与页面 mock 里那句「禁止编造数值 · 苏格拉底式 · 水平适配」对齐。
CONSTRAINTS = "禁止编造数值 · 苏格拉底式 · 水平适配"


def resolve_student_id(db: Session, path_student_id: int, user_id: int) -> int:
    """校验「路径里的 student_id」确实是登录人自己的，返回它。

    三条 E 接口的路径都带 student_id，但文档（《5-接口清单》2.5）把权限只写成
    「登录」、没区分角色。本实现收紧为「仅学生、且只能看自己」：
      - 路径里的 id 不是自己的 → 403
      - 登录人是学生却没有学生档案 → 403

    **没有 404**：任何「不是你的」id 一律 403，故意不区分「该学生不存在」与
    「不是你的」——拿 403/404 的差异去枚举库里有哪些学生是不必要的泄漏面。
    至于「档案不存在」：own 是从 students 表按 user_id 查出来的 students.id，
    只要不是 None，按同一张表主键再查必定查得到，那个分支不可达，不写。

    后端自己反查、不信任前端传来的 id：只做「传了吗」的判断没有意义，
    必须比对。

    **两道闸门，缺一不可**，别以为这一层够用：
      - 教师靠路由上的 @student_required 挡（文案「需要学生权限」）。
        它们**挡不住**：teacher01（users.id=2）在 students 表里有一行
        （students.id=1，种子数据如此），算得出 own=1，若请求的正是
        /coach/context/1，下面两个判断都会放过。
      - 学生里没有 students 行的那种（stu002，users.id=4，role='student'
        但 students 表无行）靠本函数的 `own is None` 挡——@student_required
        会放它进来。
    """
    own = user_repo.get_student_id_by_user_id(db, user_id)
    if own is None:
        raise BusinessError(403, "AI 教练仅学生可用")
    if own != path_student_id:
        raise BusinessError(403, "无权访问该学员数据")
    return own


def _bkt_items(db: Session, student_id: int) -> list[dict]:
    rows = bkt_history_repo.get_latest_per_skill_for_student(db, student_id)
    return [
        {"skill": r.skill, "p_l": round(r.p_l, 4), "confidence": r.confidence}
        for r in rows
    ]


def _weak_skills(bkt: list[dict]) -> list[dict]:
    """p_l 最低的若干项，即最薄弱的技法。

    数据不足 WEAK_SKILL_TOP_N 项时给几项算几项——新生只有一两个技法有记录
    是常态，不该为了凑数去补零值。
    """
    ranked = sorted(bkt, key=lambda x: x["p_l"])
    return [{"skill": x["skill"], "p_l": x["p_l"]} for x in ranked[:WEAK_SKILL_TOP_N]]


def _last_practice(db: Session, student_id: int) -> dict | None:
    """最近一次练习；从没练过返回 None（正常情况，不是错误）。"""
    rec = practice_records_repo.get_latest_for_student(db, student_id)
    if rec is None:
        return None
    # 曲目名要从 segments 表取。实测 6 条练习记录里 5 条的 segment_id 是 NULL，
    # 取不到就填 None，不要编一个曲目名出来。
    title = None
    if rec.segment_id is not None:
        seg = db.get(Segment, rec.segment_id)
        title = seg.title if seg else None
    return {
        "segment_id": rec.segment_id,
        "segment_title": title,
        "ai_score": rec.ai_score,
        "duration_sec": rec.duration_sec,
        # created_at 存的是北京时间（服务器时区 Asia/Shanghai），直接出 ISO 串
        "recorded_at": rec.created_at.isoformat() if rec.created_at else None,
    }


def build_context(db: Session, student_id: int) -> dict:
    """组装 E1 的客观上下文，同时是 E2 拼 prompt 的输入。

    只放**程序算出来的**数据，不含任何模型生成内容——这是页面「数据/生成分离」
    那条设计线的服务端一半（AI_teacher.html 的客观数据区）。
    """
    profile = user_repo.get_student_profile(db, student_id)
    if profile is None:
        raise BusinessError(404, "学员档案不存在")
    sid, display_name, level = profile

    bkt = _bkt_items(db, sid)
    return {
        "student": {"id": sid, "display_name": display_name, "level": level},
        "last_practice": _last_practice(db, sid),
        "bkt": bkt,
        "weak_skills": _weak_skills(bkt),
        # ↓ 三项显式空位，理由见 schemas/coach.py 的 CoachContextOut
        "deviations": None,
        "cdm": None,
        "rag": None,
    }

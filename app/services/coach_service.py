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
from app.services import llm_client
from app.services.llm_client import LlmError

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
    """数据不足 WEAK_SKILL_TOP_N 项时给几项算几项——新生只有一两个技法有记录
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


SYSTEM_PROMPT = """你是「戏韵AI」的戏曲演唱教练，面向京剧等戏曲的初学者。

教学方式：苏格拉底式引导——不直接给出答案，先用提问引导学生自己发现问题；
反复引导无效后才给出明确提示。语言风格按学生水平适配，初级学生多用生活化类比。

学生若表达挫败（如「太难」「算了」「不想练」「没劲」「放弃」），必须切到鼓励模式：
先肯定已有进步，再主动降低难度建议，不要继续追问。

strategy 只能取这四个值之一：引导、提示、鼓励、降难度
emotion 只能取这三个值之一：positive、neutral、concerned

只输出一个 JSON 对象，不要输出任何其它文字，不要用 markdown 代码块包裹：
{"reply":"给学生的回复正文","strategy":"引导","emotion":"neutral","quick_replies":["选项一","选项二"]}

用户消息里会带一段程序计算出的客观数据。所有数值一律以它为准，不要编造任何
分数、音分或百分比。数据里为 null 的项表示该维度暂无数据，直接跳过、不要提及。"""

_ALLOWED_STRATEGY = ("引导", "提示", "鼓励", "降难度")
_ALLOWED_EMOTION = ("positive", "neutral", "concerned")

_STRATEGY_DESC = {
    "引导": "不直接指出错误，通过提问引导学生自主发现偏差。",
    "提示": "反复引导无效后，给出明确的可执行提示。",
    "鼓励": "学生表达挫败，先肯定已有进步，再降低难度建议。",
    "降难度": "当前段落反复练不好，建议换成更短的片段再练。",
}

_JSON_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "coach_reply",
        "schema": {
            "type": "object",
            "properties": {
                "reply": {"type": "string"},
                "strategy": {"type": "string", "enum": list(_ALLOWED_STRATEGY)},
                "emotion": {"type": "string", "enum": list(_ALLOWED_EMOTION)},
                "quick_replies": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["reply", "strategy", "emotion", "quick_replies"],
        },
    },
}

# 2026-10-13 实测该部署支持 guided decoding（带 response_format 请求回 HTTP 200
# 且 content 是合法 JSON）。换到不支持的部署时改回 False，走 prompt 约束那条路
# ——带着 response_format 请求会被 vLLM 直接 400。
GUIDED_DECODING_SUPPORTED = True


def parse_reply(raw: str) -> tuple[str, dict]:
    """把 LLM 的原始输出解析成 (reply, meta)。

    meta 恒含四个键：strategy / emotion / quick_replies / strategy_desc。

    **任何异常都降级，绝不抛**：模型偶发不守格式是常态，一次格式抖动不该让
    整轮对话不可用。降级时把模型原文当 reply —— 内容本身仍是有效的教练回复，
    丢掉它才是真的损失；另外三个字段给默认值。

    取值越界（strategy 不在枚举内）只重置该字段，不整段降级：JSON 解出来了
    说明模型基本守约，reply 是可信的。
    """
    def fallback() -> dict:
        return {
            "strategy": "引导",
            "emotion": "neutral",
            "quick_replies": [],
            "strategy_desc": _STRATEGY_DESC["引导"],
        }

    text = raw.strip()
    # 即便 prompt 里说了不要用代码块，模型仍可能包一层；剥掉再试
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        obj = json.loads(text)
    except ValueError:
        logger.warning("LLM 输出不是合法 JSON，走降级：%s", raw[:120])
        return raw.strip(), fallback()

    if not isinstance(obj, dict):
        logger.warning("LLM 输出不是 JSON 对象，走降级：%s", raw[:120])
        return raw.strip(), fallback()

    reply = obj.get("reply")
    if not isinstance(reply, str) or not reply.strip():
        logger.warning("LLM 输出缺 reply 字段，走降级：%s", raw[:120])
        return raw.strip(), fallback()

    strategy = obj.get("strategy")
    if strategy not in _ALLOWED_STRATEGY:
        logger.warning("strategy 越界（%r），重置为「引导」", strategy)
        strategy = "引导"

    emotion = obj.get("emotion")
    if emotion not in _ALLOWED_EMOTION:
        logger.warning("emotion 越界（%r），重置为 neutral", emotion)
        emotion = "neutral"

    qr = obj.get("quick_replies")
    if not isinstance(qr, list):
        qr = []
    qr = [x for x in qr if isinstance(x, str) and x.strip()][:4]

    return reply.strip(), {
        "strategy": strategy,
        "emotion": emotion,
        "quick_replies": qr,
        "strategy_desc": _STRATEGY_DESC[strategy],
    }


def _build_messages(context: dict, history: list[ChatMessage], message: str) -> list[dict]:
    """客观数据只注入**当前这一轮**的 user 消息，不重复注入历史——历史里
    那些轮次的数据已经在各自的快照里了，重复塞既费 token 又会让模型
    以为数据在变化。
    """
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in history:
        msgs.append({"role": h.role, "content": h.content})
    msgs.append({
        "role": "user",
        "content": (
            "【客观数据】"
            + json.dumps(context, ensure_ascii=False)
            + "\n\n【学生说】" + message
        ),
    })
    return msgs


def _snapshot(context: dict, meta: dict) -> dict:
    """写进 chat_messages.context_snapshot 的快照。

    形状照库里已有那行（student_id=48）的中文键组织，便于对照。
    无源的三项如实写 None —— 快照是「当时 AI 到底用了什么」的审计记录，
    写假值会让它失去意义。
    """
    weak = " · ".join(f"{w['skill']}({w['p_l']})" for w in context["weak_skills"])
    stu = context["student"]
    return {
        "strategy": meta["strategy"],
        "strategy_desc": meta["strategy_desc"],
        "emotion": meta["emotion"],
        "学生画像": f"{stu['display_name']} · {stu['level']}",
        "薄弱技法": weak or None,
        "本次偏差": None,      # 无源
        "RAG 检索": None,      # 无源
        "约束条件": CONSTRAINTS,
    }


def chat(db: Session, student_id: int, message: str) -> dict:
    """E2：发消息 → 调 LLM → 双写 chat_messages。

    失败（LLM 超时/不可达/响应异常）一律抛 BusinessError(503)，且**一条都不写**：
    留半截对话会让 E3 读出来的轮次错乱，用户重试后还会堆一串孤立提问。
    """
    context = build_context(db, student_id)
    history = chat_repo.get_recent(db, student_id, HISTORY_TURNS)
    messages = _build_messages(context, history, message)

    try:
        raw = llm_client.chat(
            messages,
            response_format=_JSON_SCHEMA if GUIDED_DECODING_SUPPORTED else None,
        )
    except LlmError as e:
        logger.error("AI 教练调用失败：%s", e)
        raise BusinessError(503, "AI 教练暂时不可用，请稍后再试") from e

    reply, meta = parse_reply(raw)

    # 双写在同一事务里：api 层用 get_db() 不提交，这里一次 commit 落两条，
    # 要么都进要么都不进。
    chat_repo.add_message(db, student_id, "user", message, None)
    chat_repo.add_message(db, student_id, "assistant", reply, _snapshot(context, meta))
    db.commit()

    return {
        "reply": reply,
        "strategy": meta["strategy"],
        "emotion": meta["emotion"],
        "quick_replies": meta["quick_replies"],
    }


def history(db: Session, student_id: int, limit: int = 50) -> list[dict]:
    """E3：回读某学生的对话，按时间正序。

    只出 id/role/content/created_at，**不出 context_snapshot** ——
    那是「这条回复当时基于什么」的审计记录，含学生画像等内部信息，
    前端渲染对话根本用不到，没必要暴露。

    created_at 存的是北京时间，直接给 ISO 串（前端 new Date() 解析本地时间）。
    """
    rows = chat_repo.get_recent(db, student_id, limit)
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in rows
    ]

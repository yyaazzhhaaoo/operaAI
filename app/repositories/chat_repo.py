"""AI 教练对话（`chat_messages` 表）的数据访问。

目前只有「班级畏难倾向指数」的第 4 个分量在用（功能 5.8）；模块 3 的对话接口
将来接后端时，会话读写也放这里。
"""

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import ChatMessage


def count_user_messages(
    db: Session, start: datetime, end: datetime, keywords: tuple[str, ...]
) -> tuple[int, int]:
    """窗口内 `role='user'` 的消息数与其中命中关键词的条数，(命中, 总数)。

    挫败关键词触发率 = 命中 / 总数（设计第 3.4 节）。**只统计 role='user'**：
    AI 回复里出现「太难」是在描述学生的困难，不是学生的挫败表达，算进去就错了。

    一条消息命中多个关键词只计一次（计数的是「条」不是「命中次数」），所以这里
    用「整体取一次 count + 一个 or_ 条件」，不把词表展开成多条 COUNT 相加。

    分母为 0 的处理（记 0 而不是跳过）由 service 层做——本层只管把两个数报回去。

    子串匹配用 LIKE，词表里没有 % 和 _ 所以不转义；将来若加入带通配符的词，
    这里要补 escape。
    """
    if start >= end:
        return 0, 0

    window = (
        ChatMessage.role == "user",
        ChatMessage.created_at >= start,
        ChatMessage.created_at < end,
    )
    total = db.scalar(select(func.count()).select_from(ChatMessage).where(*window)) or 0
    if total == 0 or not keywords:
        # 没有消息时不必再查一次；词表为空时 or_() 会抛，直接短路
        return 0, total

    hit = db.scalar(
        select(func.count())
        .select_from(ChatMessage)
        .where(*window)
        .where(or_(*[ChatMessage.content.like(f"%{k}%") for k in keywords]))
    ) or 0
    return hit, total

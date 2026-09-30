from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models import Homework
from app.repositories import homeworks_repo, user_repo
from app.schemas.homework import HomeworkListItem, HomeworkListResponse

# 判档与排序的口径**与看板 G7 逐字同源**（app/services/dashboard_service.py:536 的
# homework_progress）。同一份作业在两条接口上必须是同一个档位与同一个顺序，否则
# 教师会在看板和作业页看到两个状态。改这里时那边要一起改——两处是**有意的重复**：
# 抽公共函数就要动已上线的看板，而两处的差异（分母位置）是真实的语义差异。
_STATUS_ORDER = {"grading": 0, "ongoing": 1, "closed": 2}

# 判的是**今天的日期**，与库无关；用 datetime.now() 会拿到宿主机本地时区，
# 跨机器跑出不同结果。同 dashboard_service._beijing_now（那边是私有函数，不跨模块 import）。
_BEIJING = ZoneInfo("Asia/Shanghai")


def _beijing_now() -> datetime:
    return datetime.now(_BEIJING)


def _status_of(hw: Homework, pending: int, today: date) -> str:
    """三档判定，判据见 HomeworkListItem 的注释。

    `pending`（待批条数）不为 0 时**优先判 grading**——截止没截止都要批，这是唯一
    需要教师动手的一档，漏看会让学生一直拿不到成绩。

    「已截止」同时认 `homeworks.status` 与 `deadline` 两个来源：种子数据里就有
    `status='open'` 但 deadline 早已过期的作业（教师忘了关），只看 status 会把它显示
    成「进行中」。
    """
    if pending:
        return "grading"
    if hw.status == "closed" or (hw.deadline is not None and hw.deadline < today):
        return "closed"
    return "ongoing"


def _sort_key(it: HomeworkListItem) -> tuple:
    """待办优先：grading → ongoing → closed；同档按截止日**降序**（最近的在前），
    没填截止日的沉底——与仓储层 `deadline desc nulls_last` 同一方向，两层不打架。
    次键取 id 降序，同一天截止的几份作业顺序才稳定。
    """
    return (
        _STATUS_ORDER[it.status],
        it.deadline is None,
        -(it.deadline.toordinal() if it.deadline else 0),
        -it.homework_id,
    )


def list_homeworks(db: Session) -> HomeworkListResponse:
    """教师端作业列表（功能 4.1）：每份作业的提交人数、截止日与状态。

    原始行由 `homeworks_repo.get_progress_rows` 出——它与看板 G7 共用同一个底层，
    提交人数已按学生去重、只统计在册学生，这里只负责判档、装配与排序。

    `total` 是**在册学生数**：`homeworks` 表没有班级/名单字段，所以今天每份作业的
    分母相同。放在行内而不是响应级的理由见 HomeworkListItem 的文档字符串。
    """
    student_ids = [row[0] for row in user_repo.get_student_roster(db)]
    today = _beijing_now().date()
    # 在册 0 人时 total 给 0 而不是让 ZeroDivisionError 冒成 500，同 G7。
    # 这里只是避免除零，**不替调用方把 0 人粉饰成 1 人**——出参的 total 仍是真实的 0。
    n = len(student_ids)

    items: list[HomeworkListItem] = []
    for hw, demo, submitted, pending in homeworks_repo.get_progress_rows(db, student_ids):
        items.append(HomeworkListItem(
            homework_id=hw.id,
            title=hw.title,
            deadline=hw.deadline,
            # demo 可空：作业允许不挂曲目（demo_id 为 NULL），三列一起为 None
            demo_title=demo.title if demo else None,
            demo_role=demo.role if demo else None,
            demo_banshi=demo.banshi if demo else None,
            submitted_count=submitted,
            total=n,
            progress=submitted / n if n else 0.0,
            pending_review_count=pending,
            status=_status_of(hw, pending, today),
        ))

    items.sort(key=_sort_key)
    return HomeworkListResponse(homeworks=items)

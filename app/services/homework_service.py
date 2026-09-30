from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.common.errors import BusinessError
from app.models import Homework
from app.repositories import homeworks_repo, user_repo
from app.schemas.homework import (
    HomeworkListItem,
    HomeworkListResponse,
    PendingSubmissionItem,
    PendingSubmissionListResponse,
    SubmissionTag,
)

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


# 标签的置信度下限（spec 3.5）。0.7 这个数是**页面自己声明的**（待批改卡片区写着
# 「只展示置信度 > 0.7 的标签」），文档从未规定要按置信度筛、也没规定阈值取多少。
# **严格大于**，0.7 本身不算。
_CONFIDENCE_MIN = 0.7


def _num(v) -> float | None:
    """JSONB 列没有类型约束，只放行真正的数值，其余一律 None。同 library_service._num。

    挡住字符串 "0.82"、True 这类：拿它们比大小在 Python 里要么抛 TypeError、要么
    按字符串字典序算出莫名其妙的结果。

    bool 要单独排除——Python 里 isinstance(True, int) 是 True。
    """
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v


def _tags_of(ai_detail: dict | None) -> list[SubmissionTag]:
    """从 ai_detail.defects 取置信度过线的标签，按置信度降序（spec 3.4–3.6）。

    整条路径防御式取值：`ai_detail` 可空，其结构由 AI 侧写入、不受本服务约束，
    而**一条坏数据不该让整个待批列表 500**——教师打开页面看不到任何待批提交，
    比少看一个标签严重得多。所以 ai_detail 不是 dict / defects 不是 list /
    元素不是 dict，一律跳过（最坏出 []，仍是 200）。

    **必须重排**：库里的 defects 不按置信度排序（李小燕那条是 0.82 / 0.45 / 0.78），
    不排的话过滤完卡片上第一个标签会是 0.78 而不是 0.82，顺序看起来是随机的。

    label 缺失或空串的整条丢弃——构造不出标签文字，前端会渲染成一个空胶囊。
    """
    if not isinstance(ai_detail, dict):
        return []
    defects = ai_detail.get("defects")
    if not isinstance(defects, list):
        return []

    scored: list[tuple[float, SubmissionTag]] = []
    for d in defects:
        if not isinstance(d, dict):
            continue
        label = d.get("label")
        if not isinstance(label, str) or not label:
            continue
        conf = _num(d.get("confidence"))
        if conf is None or conf <= _CONFIDENCE_MIN:
            continue
        # severity 原样透传，不做白名单；取不到就给 "unknown"，前端按中性色渲染。
        # 这里**不**把未知档滤掉：滤掉会让标签凭空消失，比多一个颜色怪异的档严重。
        sev = d.get("status")
        scored.append((conf, SubmissionTag(
            label=label,
            severity=sev if isinstance(sev, str) and sev else "unknown",
        )))

    scored.sort(key=lambda t: -t[0])
    return [tag for _, tag in scored]


def list_pending_submissions(db: Session, homework_id: int) -> PendingSubmissionListResponse:
    """某作业的待批改提交列表（功能 4.3）：AI 已初评、教师尚未终审的那些提交。

    作业不存在抛 404。作业存在但没有待批提交返回**空列表**，不是 404——「这份作业
    没有东西要批」是正常状态（同 library_service.demo_segments 对「有曲目没分段」的处理）。

    取数与口径全在 `homeworks_repo.get_pending_submissions`（内含与 F1 的同源性说明），
    这里只做 JSONB 解析与装配。
    """
    hw = homeworks_repo.get_homework(db, homework_id)
    if hw is None:
        raise BusinessError(404, "作业不存在")

    # 注意仓储层返回的元组顺序是 (提交, 姓名, 等级, 头像)，不是 (提交, 姓名, 头像, 等级)。
    # 解包顺序写错不会报错——等级与头像都是 str，pydantic 照收，只是两个字段对调了。
    items = [
        PendingSubmissionItem(
            submission_id=sub.id,
            student_id=sub.student_id,
            student_name=name,
            student_avatar=avatar,
            student_level=level,
            ai_score=sub.ai_score,
            submitted_at=sub.submitted_at,
            tags=_tags_of(sub.ai_detail),
        )
        for sub, name, level, avatar in homeworks_repo.get_pending_submissions(db, homework_id)
    ]

    return PendingSubmissionListResponse(
        homework_id=hw.id,
        homework_title=hw.title,
        submissions=items,
    )

from sqlalchemy import Date, cast, distinct, func, select, tuple_
from sqlalchemy.orm import Session

from app.models import Homework, Submission, TeacherDemo


def get_open_homeworks(db:Session,status:str) -> Homework:
    return list(db.scalars(select(Homework).where(Homework.status == status)).all())


def get_progress_rows(
    db: Session, student_ids: list[int]
) -> list[tuple[Homework, TeacherDemo | None, int, int]]:
    """作业进度（功能 5.9）的原始行，[(作业, 曲目或 None, 已提交人数, 待批条数)]。

    提交数**按学生去重**（`count(distinct student_id)`）：表上没有「一个学生一份作业
    只能提交一次」的唯一约束，重复提交时若按条数算，页面会出现「6/5 人已提交」。
    这也是页面文案是「人」而不是「份」的原因。

    **只统计在册学生**（传入的 student_ids）：分母是这份名单，分子若把名单外的人
    （`students` 表里连 teacher01 都有自己的行，见 students.id=1）也算进来，
    完成度会超过 100%。过滤后分子天然不超过分母。

    「待批」= `status != 'reviewed'` 的提交条数，是 `grading` 档的判定依据；不过滤
    学生，与提交数同源同口径。

    `status` 为 NULL 的提交（列有默认值但没 NOT NULL）按「未终审」算：NULL != 'reviewed'
    在 SQL 里是 NULL 而非 true，所以这里显式用 `is_not`/`or_` 兜，不能指望 `!=`。
    """
    sub = (
        select(
            Submission.homework_id.label("homework_id"),
            func.count(func.distinct(Submission.student_id)).label("submitted"),
            func.count()
            .filter((Submission.status.is_(None)) | (Submission.status != "reviewed"))
            .label("pending"),
        )
        .where(Submission.student_id.in_(set(student_ids)))
        .group_by(Submission.homework_id)
        .subquery()
    )

    stmt = (
        select(
            Homework,
            TeacherDemo,
            func.coalesce(sub.c.submitted, 0),
            func.coalesce(sub.c.pending, 0),
        )
        # 曲目可空（demo_id 允许 NULL），作业不能因为没挂曲目就从列表里消失
        .outerjoin(TeacherDemo, TeacherDemo.id == Homework.demo_id)
        .outerjoin(sub, sub.c.homework_id == Homework.id)
        # 这里只保证顺序稳定；面向教师的那套「待办优先」排序在 service 里做
        .order_by(Homework.deadline.desc().nulls_last(), Homework.id.desc())
    )
    return [tuple(row) for row in db.execute(stmt).all()]


def get_submission_stats(db: Session, student_ids: list[int]) -> tuple[int, int, int]:
    """全部作业的提交情况，(作业总数, 已提交组合数, 逾期提交组合数)。

    供「班级畏难倾向指数」的第 5 个分量（设计第 3.5 节）。**不按周切**：
    作业截止日不随周滚动，按周切分母会频繁为 0（当前库 3 份作业的截止日全在
    2026-07/08），本周与上周共用同一个值。

    组合 = (homework_id, student_id)，**去重**（表上没有唯一约束，重复提交时按条数
    算会得出「6/5 人已提交」）。只统计 `student_ids` 里的在册学生，与分母同一份名单。

    逾期 = `submitted_at` 的日期**晚于** `deadline`。deadline 为 NULL 的作业不会有
    逾期（判不了就当没逾期，不猜）。逾期属于「已提交」，所以它**不是**「未提交」的
    子集之外的东西——调用方算未提交率时要「未提交 + 逾期」，两项相加不会超过总数。

    没有在册学生或库里没有作业时提前返回，避免空 `IN ()` 与无谓的查询。
    """
    hw_count = db.scalar(select(func.count()).select_from(Homework)) or 0
    if not student_ids or hw_count == 0:
        return hw_count, 0, 0

    pair = tuple_(Submission.homework_id, Submission.student_id)
    roster = Submission.student_id.in_(set(student_ids))

    submitted = db.scalar(
        select(func.count(distinct(pair))).where(roster)
    ) or 0

    late = db.scalar(
        select(func.count(distinct(pair)))
        .join(Homework, Homework.id == Submission.homework_id)
        .where(roster)
        .where(Submission.submitted_at.is_not(None))
        .where(Homework.deadline.is_not(None))
        .where(cast(Submission.submitted_at, Date) > Homework.deadline)
    ) or 0

    return hw_count, int(submitted), int(late)

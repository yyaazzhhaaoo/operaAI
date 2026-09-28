from sqlalchemy import func, select
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

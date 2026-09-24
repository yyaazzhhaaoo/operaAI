from datetime import datetime, timedelta

from sqlalchemy import desc, select, func, extract
from sqlalchemy.orm import Session, aliased

from app.models import PracticeRecord, Student, User
from app.schemas.dashboard import OverduePracticeAlert


def get_records(db:Session) -> list[OverduePracticeAlert]:
    subq = (
        select(
            PracticeRecord,
            func.row_number()
            .over(
                partition_by=PracticeRecord.student_id,
                order_by=desc(PracticeRecord.created_at),
            )
            .label("rn"),
        )
        .subquery()
    )
    pr = aliased(PracticeRecord, subq, name="pr")

    two_days_ago = datetime.now() - timedelta(days=2)
    days_over = extract("day", func.now() - pr.created_at).label("days_over")

    stmt = (
        select(pr, days_over, User.display_name)          # 顺带查学生姓名
        # student_id 外键指向 students.id 而不是 users.id，姓名要多拐一次
        # students.user_id → users.id，直接 join users 会取到另一个人的名字
        # （见 DOC_ISSUES 第 21 条）
        .join(Student, Student.id == pr.student_id)
        .join(User, User.id == Student.user_id)
        .where(subq.c.rn == 1)
        .where(pr.created_at < two_days_ago)
        .order_by(desc(pr.created_at))
    )

    return [
        OverduePracticeAlert(
            days_over=row.days_over,
            student_id=row.pr.student_id,
            student_name=row.display_name,
        )
        for row in db.execute(stmt).all()
    ]


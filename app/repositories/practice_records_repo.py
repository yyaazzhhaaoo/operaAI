from datetime import datetime, timedelta

from sqlalchemy import desc, select, func, extract
from sqlalchemy.orm import Session, aliased

from app.models import PracticeRecord, User
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
        .join(User, User.id == pr.student_id)  # 关联学生表
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


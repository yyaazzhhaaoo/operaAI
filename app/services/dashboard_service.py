from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.repositories import user_repo, library_repo, annotations_repo, homeworks_repo, bkt_history_repo, \
    practice_records_repo
from app.schemas.dashboard import DashBoardSummary, MasteryDropAlert, AlertResponse


def summary(db:Session) -> DashBoardSummary:
    # 在班学生
    user_list = user_repo.get_by_role(db,role="student") or []
    user_count = len(user_list)
    # 第二步：在这批结果里按 created_at 筛选本周
    today = datetime.now()
    start_of_week = (today - timedelta(days=today.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    weekly_students = [u for u in user_list if u.created_at >= start_of_week]

    # 新增人数
    new_student_count = len(weekly_students)

    # 示范曲目
    library_list = library_repo.get_library_list(db) or []
    library_count = len(library_list)
    weekly_library = [l for l in library_list if l.created_at >= start_of_week]
    new_library_count = len(weekly_library)

    # 标注规则
    annotations_list = annotations_repo.get_annotations_list(db) or []
    annotations_count = len(annotations_list)
    weekly_annotations = [a for a in annotations_list if a.created_at >= start_of_week]
    new_annotations_count = len(weekly_annotations)

    # 待批改
    homeworks_list = homeworks_repo.get_open_homeworks(db,status="open") or []
    homeworks_count = len(homeworks_list)

    return DashBoardSummary(
        user_count=user_count,
        new_student_count=new_student_count,
        library_count=library_count,
        new_library_count=new_library_count,
        annotations_count=annotations_count,
        new_annotations_count=new_annotations_count,
        homeworks_count=homeworks_count
    )

def alerts(db:Session):
    records = bkt_history_repo.get_history_list(db)
    grouped: dict[tuple[int, str], list] = {}
    for r in records:
        key = (r.student_id, r.skill)
        lst = grouped.setdefault(key, [])
        if len(lst) < 2:
            lst.append(r)

    # 组装结果；不足两条跳过
    result: list[MasteryDropAlert] = []
    for (student_id, skill), lst in grouped.items():
        if len(lst) < 2 or (lst[1].p_l - lst[0].p_l) <= 0.1:
            continue
        latest, previous = lst[0], lst[1]
        user = user_repo.get_by_id(db, student_id)
        result.append(MasteryDropAlert(
            student_id=student_id,
            student_name=user.display_name if user else None,
            skill=skill,
            latest=latest.p_l,
            previous=previous.p_l,
            diff=round(latest.p_l - previous.p_l, 2),
        ))

    # 连续未提交统计
    records = practice_records_repo.get_records(db)


    return AlertResponse(masteryDropAlert=result,overduePracticeAlert=records)



from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.repositories import user_repo, library_repo, annotations_repo, homeworks_repo, bkt_history_repo, \
    practice_records_repo, graph_repo
from app.schemas.dashboard import DashBoardSummary, MasteryDropAlert, AlertResponse, PrereqLockAlert, PrereqSkill


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
    # r.student_id 是 students.id 不是 users.id，姓名要经 students.user_id 拐一次，
    # 这里按学生批量取好，避免逐条查一次库（见 DOC_ISSUES 第 21 条）
    drop_names = user_repo.get_student_names(db, [r.student_id for r in records])
    result: list[MasteryDropAlert] = []
    for (student_id, skill), lst in grouped.items():
        if len(lst) < 2 or (lst[1].p_l - lst[0].p_l) <= 0.1:
            continue
        latest, previous = lst[0], lst[1]
        result.append(MasteryDropAlert(
            student_id=student_id,
            student_name=drop_names.get(student_id),
            skill=skill,
            latest=latest.p_l,
            previous=previous.p_l,
            diff=round(latest.p_l - previous.p_l, 2),
        ))

    # 连续未提交统计
    records = practice_records_repo.get_records(db)

    # 前置技法锁定：前置技法当前的掌握度低于它自己的达标线，就把下游技法锁掉。
    # 判的是「前置」而不是「下游」——下游自己掌握度低只是练得少，不算被卡住。
    current = bkt_history_repo.get_latest_by_skill(db)
    mastery_by_skill: dict[str, list[tuple[int, float]]] = {}
    for r in current:
        mastery_by_skill.setdefault(r.skill, []).append((r.student_id, r.p_l))
    # student_id 是 students.id，姓名要经 students.user_id 拐一次
    lock_names = user_repo.get_student_names(db, [r.student_id for r in current])

    # 按学生聚合：一个学生只出一行，否则同一个名字会因为锁了多项技法重复多行
    grouped_locks: dict[int, tuple[list[str], list[PrereqSkill]]] = {}
    for prereq_skill, threshold, locked_skill in graph_repo.get_prereq_edges(db):
        # 前置技法在 bkt_history 里没有数据的边直接跳过：判不了就不报，
        # 图谱 label 与 bkt_history.skill 名字对不上时就是这种情况（见 DOC_ISSUES）
        for student_id, p_l in mastery_by_skill.get(prereq_skill, []):
            if p_l >= threshold:
                continue
            locked_skills, prereqs = grouped_locks.setdefault(student_id, ([], []))
            # 两边都去重：气息支撑一个前置锁住归韵+拖腔，润腔则被滑音和装饰音各锁一次
            if locked_skill not in locked_skills:
                locked_skills.append(locked_skill)
            if all(p.skill != prereq_skill for p in prereqs):
                prereqs.append(PrereqSkill(skill=prereq_skill, mastery=p_l, threshold=threshold))

    locks = [
        PrereqLockAlert(
            student_id=student_id,
            student_name=lock_names.get(student_id),
            locked_skills=locked_skills,
            prereqs=prereqs,
        )
        for student_id, (locked_skills, prereqs) in grouped_locks.items()
    ]
    locks.sort(key=lambda a: a.student_id)

    return AlertResponse(
        masteryDropAlert=result,
        overduePracticeAlert=records,
        prerequisiteLockAlert=locks,
    )
def heatmap(db:Session):
    pass


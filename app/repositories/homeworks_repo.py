from sqlalchemy import Date, cast, distinct, func, select, tuple_
from sqlalchemy.orm import Session

from app.models import Homework, Student, Submission, TeacherDemo, User


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


def get_homework(db: Session, homework_id: int) -> Homework | None:
    """按 id 取作业，不存在返回 None。供 F4 判 404。"""
    return db.get(Homework, homework_id)


def get_pending_submissions(
    db: Session, homework_id: int
) -> list[tuple[Submission, str | None, str | None, str | None]]:
    """某作业下未终审的提交，[(提交, 姓名, 等级, 头像)]，最早提交在前。

    「未终审」= `status IS NULL OR status != 'reviewed'`，与上面的 get_progress_rows
    的 `pending` **逐字同源**——同一批提交在 F1（出条数）与 F4（出行本身）上必须
    是一致的，改这里必须同时改那里。NULL 同样要显式兜：`NULL != 'reviewed'` 在
    SQL 里求值为 NULL 而非 true。

    与 F1 的 `pending` 有一处**刻意不同：这里不过滤在册名单**。F1 过滤是为了让分子
    不超过分母（students 表里连 teacher01 都有自己的行，见 students.id=1），F4 没有
    分母，过滤只会让「提交人不在名单里」的真实提交永远不出现在待批列表里——教师
    批不到它，比数目对不上严重得多。代价是脏数据下这里的条数会大于 F1 的
    pending_review_count，那是预期不是 bug。

    两个 join 都必须是 LEFT：`submissions.student_id` 可空，INNER JOIN 会把
    student_id 为 NULL 的提交整条删掉，同样造成「批不到」；`students.user_id` 那层
    用 LEFT 则保证 students 有行而 users 缺失时至少还能出 student_id。

    姓名要按 `students.user_id` 拐一次取，**不能** `db.get(User, student_id)`：
    submissions.student_id 指的是 students.id，与 users.id 只是偶尔数值相同，
    直接当 users.id 用会静默取到另一个人的名字（DOC_ISSUES 第 21 条）。

    排序 `submitted_at ASC NULLS LAST, id ASC`。`id` 不是装饰：库里 24/26/27 三条的
    submitted_at 完全相同，只按时间排则顺序由执行计划决定，前端选中的提交会在刷新
    后跳到别人身上。NULL 排最后是因为那说明入库时没写时间，不该插到真实时间前面。
    """
    stmt = (
        select(Submission, User.display_name, Student.level, Student.avatar)
        .outerjoin(Student, Student.id == Submission.student_id)
        .outerjoin(User, User.id == Student.user_id)
        .where(Submission.homework_id == homework_id)
        .where((Submission.status.is_(None)) | (Submission.status != "reviewed"))
        .order_by(Submission.submitted_at.asc().nulls_last(), Submission.id.asc())
    )
    return [tuple(row) for row in db.execute(stmt).all()]


def get_submission_detail(
    db: Session, submission_id: int
) -> tuple[Submission, str | None, str | None, str | None, str | None] | None:
    """一条提交的批改详情原始行，(提交, 姓名, 等级, 头像, 作业标题)，不存在返回 None。

    供 F5 判 404。**返回的是单行元组不是列表**——F5 查的是一个具名资源，与
    `get_pending_submissions` 的集合语义不同（那个查的是集合，空集合是合法结果）。

    三层 join **全必须 LEFT**：`submissions.student_id` / `submissions.homework_id`
    列本身可空，INNER JOIN 会让这两种提交整条 404——教师点开一个真存在的提交却被
    告知「不存在」。`students.user_id` 那层用 LEFT 则保证 students 有行而 users
    缺失时至少还能出 student_id 与头像。

    姓名必须按 `students.user_id` 拐一次取，**不能** `db.get(User, student_id)`：
    submissions.student_id 指的是 students.id，与 users.id 只是偶尔数值相同，直接
    当 users.id 用会静默取到另一个人的名字（DOC_ISSUES 第 21 条）。

    **元组的列顺序是 (提交, 姓名, 等级, 头像, 作业标题)，与上面
    `get_pending_submissions` 的前四列顺序刻意保持一致**（那个是 `(提交, 姓名, 等级,
    头像)`）。中间四个都是 str，解包写错不会报错，pydantic 照收，只是把头像显示成
    姓名——本文件第 171 行有同一条警告。改这里的 SELECT 顺序必须同步改 service 的解包。

    不用 `db.get(Submission, submission_id)`：本接口要四张表的字段，单独 get 会触发
    三条懒加载 SQL，不如一条 join。
    """
    stmt = (
        select(
            Submission,
            User.display_name,
            Student.level,
            Student.avatar,
            Homework.title,
        )
        .outerjoin(Student, Student.id == Submission.student_id)
        .outerjoin(User, User.id == Student.user_id)
        .outerjoin(Homework, Homework.id == Submission.homework_id)
        .where(Submission.id == submission_id)
    )
    row = db.execute(stmt).first()
    return tuple(row) if row is not None else None

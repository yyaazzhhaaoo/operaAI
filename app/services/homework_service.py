from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.errors import BusinessError
from app.models import Homework, ScoreCalibration, Submission
from app.repositories import audio_repo, homeworks_repo, library_repo, user_repo
from app.schemas.audio import AnalyzeSubmitIn
from app.schemas.homework import (
    BktChange,
    CdmTag,
    HomeworkCreateIn,
    HomeworkListItem,
    HomeworkListResponse,
    LyricWord,
    PendingSubmissionItem,
    PendingSubmissionListResponse,
    StudentHomeworkDetail,
    StudentHomeworkItem,
    StudentHomeworkListResponse,
    StudentSubmissionBrief,
    StudentSubmissionDetail,
    SubmissionCalibration,
    SubmissionCalibrationIn,
    SubmissionDetailResponse,
    SubmissionReviewIn,
    SubmissionReviewResponse,
    SubmissionTag,
)
from app.services import analyze_service, practice_service

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


def create_homework(
    db: Session, data: HomeworkCreateIn, teacher_id: int
) -> HomeworkListItem:
    """F2 布置新作业（功能 4.2）：校验引用、写 homeworks、按 F1 的行形状回参。

    《5-接口清单》F2 没有请求体/响应体契约，字段与格式校验见 `HomeworkCreateIn`。
    权限在路由层（`login_required` + `teacher_required`），`teacher_id` 由路由从
    session 取出后传入——本函数不碰 flask.session（同 calibrate_submission）。

    以下三条是本次自拟的：
      1. `demo_id` 必须存在，否则 404，与 C2 的「曲目不存在」同码同文案；
      2. `segment_ids` 必须全部属于该曲目，否则 422——跨曲目的唱段会让 F3 拿错
         参考音轨；请求体引用不存在的从属资源属请求体不合法（同 F6 对语音音频
         的 422 判据），不是 URL 里那个具名资源不存在；
      3. `deadline` 不早于北京时间今天，否则 422：前端弹窗的 min 就是今天，后端
         不校验等于允许绕过页面写一份出生即逾期的作业。

    空 `segment_ids` 合法，语义是「按整曲布置」（前端弹窗的既有口径）。
    """
    demo = library_repo.get_demo(db, data.demo_id)
    if demo is None:
        raise BusinessError(404, "曲目不存在")

    if data.segment_ids:
        owned = {s.id for s in library_repo.list_segments(db, data.demo_id)}
        alien = [sid for sid in data.segment_ids if sid not in owned]
        if alien:
            raise BusinessError(
                422, f"唱段不属于该曲目：{'、'.join(str(x) for x in alien)}"
            )

    today = _beijing_now().date()
    if data.deadline < today:
        raise BusinessError(422, "截止日期不能早于今天")

    hw = homeworks_repo.add_homework(db, Homework(
        teacher_id=teacher_id,
        title=data.title,
        demo_id=data.demo_id,
        segment_ids=data.segment_ids,
        focus_skills=data.focus_skills,
        deadline=data.deadline,
        status="open",
    ))

    # 出参在 commit **之前**组装：commit 会让 ORM 实例的属性过期，之后再读会多发
    # 一条 SELECT 把整行重新拉一遍（同 review_submission）。新作业没有任何提交，
    # 所以三个统计量恒为 0——**不查库**，也就不存在与 F1 口径不一致的风险。
    n = len(user_repo.get_student_roster(db))
    out = HomeworkListItem(
        homework_id=hw.id,
        title=hw.title,
        deadline=hw.deadline,
        demo_title=demo.title,
        demo_role=demo.role,
        demo_banshi=demo.banshi,
        submitted_count=0,
        total=n,
        progress=0.0,
        pending_review_count=0,
        status=_status_of(hw, 0, today),
    )
    db.commit()
    return out


def _student_id_or_403(db: Session, user_id: int) -> int:
    """登录用户 → students.id；没有学生档案回 403。

    与 practice_service._own_student_id 同口径，但不跨模块 import 私有函数：
    两个 service 各自守住自己接口的权限边界，改一个不会意外影响另一个。
    """
    student_id = user_repo.get_student_id_by_user_id(db, user_id)
    if student_id is None:
        raise BusinessError(403, "当前账号没有学生档案")
    return student_id


def _submission_status(sub: Submission | None) -> str:
    """学生端四档：无提交 todo，有提交取列值，NULL 脏数据按 submitted。"""
    if sub is None:
        return "todo"
    return sub.status or "submitted"


def _is_overdue(hw: Homework, sub: Submission | None, today: date) -> bool:
    """与教师端 `get_submission_stats` 的逾期口径逐字同源。

    未提交：deadline 非空且早于北京时间今天；
    已提交：`submitted_at` 的日期晚于 deadline（`submitted_at` 是 UTC，
    与 SQL 侧 `cast(submitted_at, Date) > deadline` 一致）。
    deadline 为空一律 false——判不了就当没逾期，不猜。
    """
    if hw.deadline is None:
        return False
    if sub is None:
        return hw.deadline < today
    return sub.submitted_at is not None and sub.submitted_at.date() > hw.deadline


def _allowed_segment_ids(db: Session, hw: Homework) -> list[int]:
    """作业当前实际可选的唱段，按 segments.seq 升序。

    - `homeworks.segment_ids` 非空：只保留仍存在的那些；
    - 为空（按整曲布置）：该曲目当前全部分段；
    - `demo_id` 为空：空数组。

    分段被重新解析后旧的 id 可能已不存在，所以必须与当前 segments 表求交，
    不能直接把 JSONB 原样给前端。
    """
    if hw.demo_id is None:
        return []
    segments = library_repo.list_segments(db, hw.demo_id)
    if not hw.segment_ids:
        return [s.id for s in segments]
    wanted = set(hw.segment_ids)
    return [s.id for s in segments if s.id in wanted]


def _to_brief(sub: Submission) -> StudentSubmissionBrief:
    return StudentSubmissionBrief(
        submission_id=sub.id,
        status=sub.status or "submitted",
        ai_score=sub.ai_score,
        teacher_score=sub.teacher_score,
        submitted_at=sub.submitted_at,
    )


def _to_detail_submission(sub: Submission) -> StudentSubmissionDetail:
    """详情里的提交块。words / cdm_tags 复用 F5 的解析函数。"""
    return StudentSubmissionDetail(
        submission_id=sub.id,
        status=sub.status or "submitted",
        ai_score=sub.ai_score,
        teacher_score=sub.teacher_score,
        teacher_comment=sub.teacher_comment,
        submitted_at=sub.submitted_at,
        reviewed_at=sub.reviewed_at,
        segment_id=sub.segment_id,
        words=_lyrics(sub.ai_detail),
        cdm_tags=_cdm_tags(sub.ai_detail),
    )


def _build_student_item(
    hw: Homework, demo, sub: Submission | None, today: date
) -> StudentHomeworkItem:
    return StudentHomeworkItem(
        homework_id=hw.id,
        title=hw.title,
        demo_id=hw.demo_id,
        demo_title=demo.title if demo else None,
        segment_count=len(hw.segment_ids or []),
        focus_skills=list(hw.focus_skills or []),
        deadline=hw.deadline,
        status=_submission_status(sub),
        overdue=_is_overdue(hw, sub, today),
        submission=_to_brief(sub) if sub else None,
    )


def _student_sort_key(item: StudentHomeworkItem) -> tuple:
    """4.1 的排序：无提交在前（deadline 升序、NULL 沉底、id 降序），
    有提交在后（submitted_at 降序、NULL 沉底、id 降序）。
    """
    sub = item.submission
    if sub is None:
        return (
            0,
            item.deadline is None,
            item.deadline.toordinal() if item.deadline else 0,
            -item.homework_id,
        )
    ts = sub.submitted_at.timestamp() if sub.submitted_at else 0.0
    return (1, sub.submitted_at is None, -ts, -item.homework_id)


def list_my_homeworks(
    db: Session, *, user_id: int
) -> StudentHomeworkListResponse:
    """学生端作业列表（4.1）。权限在路由层，这里只按 user_id 做身份映射。"""
    student_id = _student_id_or_403(db, user_id)
    today = _beijing_now().date()
    items = [
        _build_student_item(hw, demo, sub, today)
        for hw, demo, sub in homeworks_repo.get_homeworks_with_submission(db, student_id)
    ]
    items.sort(key=_student_sort_key)
    return StudentHomeworkListResponse(homeworks=items)


def my_homework_detail(
    db: Session, *, user_id: int, homework_id: int
) -> StudentHomeworkDetail:
    """学生端作业详情（4.2）。作业不存在回 404；不校验归属（同 F1）。"""
    student_id = _student_id_or_403(db, user_id)
    row = homeworks_repo.get_homework_with_submission(db, homework_id, student_id)
    if row is None:
        raise BusinessError(404, "作业不存在")

    hw, demo, sub = row
    today = _beijing_now().date()
    base = _build_student_item(hw, demo, sub, today)
    allowed = _allowed_segment_ids(db, hw)
    # 不能把 base 里的轻量 submission 直接透传：它的类型是
    # StudentSubmissionBrief，而详情字段要求 StudentSubmissionDetail；
    # 且 StudentHomeworkDetail(**base.model_dump(), submission=...) 会因
    # 关键字重复直接 TypeError。先转 dict 再覆盖。
    payload = base.model_dump()
    payload["submission"] = _to_detail_submission(sub) if sub else None
    return StudentHomeworkDetail(
        **payload,
        segment_ids=list(hw.segment_ids or []),
        allowed_segment_ids=allowed,
        can_submit=sub is None and bool(allowed),
    )


def submit_homework(
    db: Session,
    *,
    user_id: int,
    homework_id: int,
    segment_id: int,
    audio_id: int,
) -> str:
    """F3：校验后建占位提交，投 B2 管线，返回 task_id。

    顺序是「先 flush 拿 id、再派发、最后 commit」：派发失败时占位行还没提交，
    可以干净删除；派发成功但 commit 失败时，worker 末尾找不到提交行会把任务
    置为 failed，不会写出错误数据。
    """
    student_id = _student_id_or_403(db, user_id)

    hw = homeworks_repo.get_homework(db, homework_id)
    if hw is None:
        raise BusinessError(404, "作业不存在")

    audio = audio_repo.get_by_id(db, audio_id)
    if audio is None:
        raise BusinessError(404, "音频不存在")
    if audio.uploader_id != user_id:
        raise BusinessError(403, "只能提交本人录音")

    allowed = _allowed_segment_ids(db, hw)
    if not allowed:
        raise BusinessError(422, "该作业没有可提交的唱段")
    if segment_id not in allowed:
        raise BusinessError(422, "唱段不在本次作业范围内")

    if homeworks_repo.get_submission_for_student(db, homework_id, student_id) is not None:
        raise BusinessError(422, "该作业已提交，不能重复提交")

    sub = Submission(
        homework_id=homework_id,
        student_id=student_id,
        segment_id=segment_id,
        audio_id=audio_id,
        status="submitted",
    )
    try:
        homeworks_repo.add_submission(db, sub)
    except IntegrityError:
        # 并发两个请求同时通过了上面的查询，唯一索引在这里挡住第二个。
        # 必须先 rollback，否则会话处于失败状态，后续任何查询都会报错。
        db.rollback()
        raise BusinessError(422, "该作业已提交，不能重复提交") from None

    try:
        task_id = analyze_service.submit(
            db,
            AnalyzeSubmitIn(segment_id=segment_id, student_audio_id=audio_id),
            persist={"kind": "homework", "submission_id": sub.id},
        )
    except Exception:
        # 分段没绑教师轨、broker 不可达等：占位行还没提交，删掉再原样抛出。
        # 清理本身失败也不能掩盖原始异常。
        try:
            db.delete(sub)
            db.commit()
        except Exception:
            db.rollback()
        raise

    db.commit()
    return task_id


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


def _cdm_tags(ai_detail: dict | None) -> list[CdmTag]:
    """F5 的功能 4.6：`ai_detail.defects` 的**全量**，按置信度降序。

    **与上面 _tags_of 有一处刻意的不同：不套 confidence > 0.7 的阈值。** 那条阈值是
    待批卡片自己的展示口径（F4 spec 3.5）；批改页是教师逐条判断 AI 对不对的地方，
    低置信度的标签恰恰是最该被质疑、因而最该被看见的一条。真库里 23 的 0.45、
    24 的 0.52、26 的 0.65 三条会因此出现在这里而不出现在卡片上。

    **另一处不同：confidence 取不到的元素不丢**，给 None 排末尾。F4 是拿它排序筛选
    的，缺了没法定位；这里只是把它带出去，藏起来比带个 null 严重。

    防御式取值同 _tags_of：ai_detail 可空、结构由 AI 侧写入不受本服务约束，一条坏
    数据不该让教师打不开批改面板——ai_detail 不是 dict / defects 不是 list / 元素
    不是 dict，一律跳过（最坏出 []，仍是 200）。

    label 缺失或空串的整条丢弃——构造不出标签文字，前端会渲染成一个空胶囊。

    排序：有 confidence 的按降序在前，无 confidence 的按**原始数组序**沉底
    （Python 的 list.sort 稳定，同 key 保持原序）。
    """
    if not isinstance(ai_detail, dict):
        return []
    defects = ai_detail.get("defects")
    if not isinstance(defects, list):
        return []

    scored: list[tuple[int, float, CdmTag]] = []
    for d in defects:
        if not isinstance(d, dict):
            continue
        label = d.get("label")
        if not isinstance(label, str) or not label:
            continue

        conf = _num(d.get("confidence"))
        sev = d.get("status")
        cid = d.get("id")
        cat = d.get("category")
        ev = d.get("evidence")
        feats = d.get("features")

        scored.append((
            # 无 confidence 的沉底；同组内按置信度降序
            0 if conf is not None else 1,
            -conf if conf is not None else 0.0,
            CdmTag(
                id=cid if isinstance(cid, str) and cid else None,
                label=label,
                # severity 原样透传、不做白名单；取不到给 "unknown"，前端按中性色渲染
                severity=sev if isinstance(sev, str) and sev else "unknown",
                confidence=conf,
                category=cat if isinstance(cat, str) and cat else None,
                evidence=ev if isinstance(ev, str) and ev else None,
                features=feats if isinstance(feats, dict) else None,
            ),
        ))

    scored.sort(key=lambda t: (t[0], t[1]))
    return [tag for _, _, tag in scored]


def _bkt_changes(before: dict | None, after: dict | None) -> list[BktChange]:
    """F5 的功能 4.7：`bkt_before` / `bkt_after` 两个扁平字典合并成前后对比。

    两个字典的形状是「技法名 → P(L)」，取**两侧 key 的并集**，一侧没有的技法给 None。

    delta 由后端算并 round 到 4 位：`0.48 - 0.46` 在浮点下是 0.020000000000000018，
    直接出会给前端一个 18 位小数。仅两侧都是数值时才算，否则 None。

    只放行真正的数值（复用 _num，bool 要单独排除——`isinstance(True, int)` 是 True）：
    JSONB 列没有类型约束，字符串 `"0.82"` 混进来会让 delta 变成字符串拼接或抛
    TypeError。

    排序按 skill 名升序。**不依赖 JSONB 的键序**——PostgreSQL 的 jsonb 有规范键序
    （短键先、同长按字节序），当前真库里恰好与技法的教学顺序观感一致，但那是实现
    细节，不该被契约依赖。要改成「最弱技法在前」（按 before 升序）只需动这一行。

    两侧都无值 → `[]`（真库 25/26/27 就是这种），**不是 None**：空数组表示「查了，
    没有」，与 dimensions 的 None（表示「这块没实现」）语义不同。任一侧不是 dict
    （脏数据）按该侧无值处理。
    """
    a = before if isinstance(before, dict) else {}
    b = after if isinstance(after, dict) else {}

    out: list[BktChange] = []
    for skill in sorted(set(a) | set(b)):
        bv = _num(a.get(skill))
        av = _num(b.get(skill))
        delta = round(av - bv, 4) if (av is not None and bv is not None) else None
        out.append(BktChange(skill=skill, before=bv, after=av, delta=delta))
    return out


def _feature_matrix(ai_detail: dict | None) -> dict | None:
    """F5 的功能 4.5：原样透传 `ai_detail.featureMatrix`（9 个原始声学量）。

    键名保留 AI 侧的驼峰（pitchStd 等），不做 snake_case 转换——这是 AI 内部特征包，
    改名会让它和写入方对不上，查问题时两边对不上号。

    不做结构校验：ai_detail 不是 dict 或该键不是 dict 就出 None，不抛错。
    """
    if not isinstance(ai_detail, dict):
        return None
    fm = ai_detail.get("featureMatrix")
    return fm if isinstance(fm, dict) else None


def _lyrics(ai_detail: dict | None) -> list[LyricWord]:
    """F5 的功能 4.4：`ai_detail.words`（B4 同形的子集）→ 逐字偏差。

    2026-10-20 起接通读链路：写入方是作业提交分析（F3）——它把 B4 的 `words`
    原样放进 `ai_detail.words`，这里直接读，不再翻译字段名。现有 5 条提交的
    `ai_detail` 只有 CDM 三个键，因此仍出 []（**这是真实的「本次没有」，不是
    接口占位**）；F3 落库后同一个接口自动有值。

    防御式取值同 `_cdm_tags`：`words` 不是 list、元素不是 dict、`index` 不是
    整数，一律跳过——一条坏数据不该让教师打不开批改面板。`word` 允许 None
    （B4 对 `lyrics_json` 里缺字的条目就是给 None），其余数值字段用 `_num`
    挡掉字符串与 bool。
    """
    if not isinstance(ai_detail, dict):
        return []
    words = ai_detail.get("words")
    if not isinstance(words, list):
        return []

    out: list[LyricWord] = []
    for item in words:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        # bool 是 int 的子类；index 缺失或非整数时无法稳定定位这个字，跳过。
        if isinstance(index, bool) or not isinstance(index, int):
            continue
        word = item.get("word")
        warning = item.get("warning")
        out.append(LyricWord(
            index=index,
            word=word if isinstance(word, str) else None,
            start=_num(item.get("start")),
            end=_num(item.get("end")),
            deviation_cents=_num(item.get("deviation_cents")),
            warning=warning if isinstance(warning, bool) else None,
        ))
    return out


def _overall_confidence(ai_detail: dict | None) -> float | None:
    if not isinstance(ai_detail, dict):
        return None
    return _num(ai_detail.get("overallConfidence"))


def _calibration_of(db: Session, sub: Submission) -> SubmissionCalibration | None:
    """F5 出参里的校准块（功能 4.10，F7 写入）。

    没校准过返回 None（**不是空对象**）：页面靠 `null` 判「三个 radio 都不选」。
    取最新一条的理由见 spec 3.6——本表没有唯一约束，多行是可能的。
    """
    row = homeworks_repo.get_latest_calibration(db, sub.id)
    return None if row is None else SubmissionCalibration.model_validate(row)


def submission_detail(db: Session, submission_id: int) -> SubmissionDetailResponse:
    """F5 批改详情（功能 4.4-4.7）。

    提交不存在抛 404。取数与 join 口径全在 `homeworks_repo.get_submission_detail`
    （内含三层 LEFT 与「姓名必须拐 students.user_id」的说明），这里只做 JSONB 解析
    与装配。

    `lyrics` 读 `ai_detail.words`（2026-10-20 起，F3 提交分析写入；现有数据没有
    该键，仍出 []）。`dimensions` 仍是显式空位——功能 4.5 在库里没有数据源，理由
    见 spec 2.5 与 `SubmissionDetailResponse` 的文档字符串。它们不是本次没做，是
    数据不存在，所以出 `[]` 与 `None` 而不是省略键。
    """
    row = homeworks_repo.get_submission_detail(db, submission_id)
    if row is None:
        raise BusinessError(404, "提交不存在")

    # 元组顺序是 (提交, 姓名, 等级, 头像, 作业标题)——**中间四个都是 str，解包写错
    # 不会报错**，pydantic 照收，只是把头像显示成姓名。与仓储函数的 SELECT 逐列对齐，
    # 也与 F4 list_pending_submissions 的解包顺序一致。
    sub, name, level, avatar, hw_title = row

    return SubmissionDetailResponse(
        submission_id=sub.id,
        homework_id=sub.homework_id,
        homework_title=hw_title,
        student_id=sub.student_id,
        student_name=name,
        student_avatar=avatar,
        student_level=level,
        submitted_at=sub.submitted_at,
        audio_id=sub.audio_id,
        ai_score=sub.ai_score,
        overall_confidence=_overall_confidence(sub.ai_detail),
        feature_matrix=_feature_matrix(sub.ai_detail),
        dimensions=None,          # 功能 4.5 四维分数无数据源，显式空位
        lyrics=_lyrics(sub.ai_detail),   # 功能 4.4：ai_detail.words（F3 写入）
        cdm_tags=_cdm_tags(sub.ai_detail),
        bkt=_bkt_changes(sub.bkt_before, sub.bkt_after),
        status=sub.status,
        teacher_score=sub.teacher_score,
        teacher_comment=sub.teacher_comment,
        voice_comment_text=sub.voice_comment_text,
        voice_comment_audio_id=sub.voice_comment_audio_id,
        reviewed_at=sub.reviewed_at,
        calibration=_calibration_of(db, sub),
    )


# F6 入参字段名 → submissions 列名。四个字段与四个列现在一一同名，这张表因此看着
# 冗余，但它是**唯一的映射声明点**：将来对外字段要改名（比如对外叫 audio_id、对内
# 叫 voice_comment_audio_id）只改这里，不用去 review_submission 里逐个 setattr 找。
_REVIEW_FIELDS = (
    "teacher_score",
    "teacher_comment",
    "voice_comment_text",
    "voice_comment_audio_id",
)


def review_submission(
    db: Session, submission_id: int, data: SubmissionReviewIn
) -> SubmissionReviewResponse:
    """F6 教师终审（功能 4.8 终审评分 / 4.9 终审点评 / 4.11 语音点评）。

    提交不存在抛 404。已 `reviewed` 的再调用 = **覆盖更新**，`reviewed_at` 刷新到
    本次（spec 3.3）——库里没有「退回/撤销终审」的接口，所以覆盖是唯一的修改途径。

    只写**请求里显式出现过**的字段：没出现 = 保持原值，显式 null = 清空。用
    `model_fields_set` 判，不用 `is not None`（spec 3.2）。

    这是全项目**第一处**把 `submissions.status` 写成 `'reviewed'` 的代码，落地后
    F4 的待批列表与 F1 的「批改中」判据才会真正流转起来（DOC_ISSUES 第 25/34 条
    都记着「等 F6 落地即自动恢复」）。
    """
    row = homeworks_repo.get_submission(db, submission_id)
    if row is None:
        raise BusinessError(404, "提交不存在")

    changes = {
        f: getattr(data, f) for f in _REVIEW_FIELDS if f in data.model_fields_set
    }

    # 引用的音频必须存在。查不到回 422 而不是 404——404 在本项目里留给「URL 里那个
    # 具名资源不存在」（F4/F5 的「作业不存在」「提交不存在」），而这是请求体里引用了
    # 一个不存在的资源，属请求体不合法（spec 3.8）。
    if changes.get("voice_comment_audio_id") is not None:
        if audio_repo.get_by_id(db, changes["voice_comment_audio_id"]) is None:
            raise BusinessError(422, "语音点评音频不存在")

    homeworks_repo.apply_review(db, row, changes)
    row.status = "reviewed"
    # 不用 func.now()：那是 SQL 表达式，赋进属性后 row.reviewed_at 拿到的是表达式
    # 对象而不是 datetime，拿去装出参会炸。落库格式一致（TIMESTAMP，无时区）。
    row.reviewed_at = datetime.now()

    # 出参在 commit **之前**组装：commit 会让 ORM 实例的属性过期，之后再读
    # row.teacher_score 会多发一条 SELECT 把整行重新拉一遍。同 C5 的注释。
    out = SubmissionReviewResponse(
        submission_id=row.id,
        status=row.status,
        reviewed_at=row.reviewed_at,
        **{f: getattr(row, f) for f in _REVIEW_FIELDS},
    )
    db.commit()
    return out


def calibrate_submission(
    db: Session, submission_id: int, data: SubmissionCalibrationIn, teacher_id: int
) -> SubmissionCalibration | None:
    """F7 教师 AI 评分校准（功能 4.10）。

    提交不存在抛 404。按 (submission_id, teacher_id) **upsert**：有则更新并刷新
    created_at，无则插入（spec 3.3）。`bias_mode` 显式给 null = **删除该行**
    （撤销，spec 3.4），此时返回 None。

    分数不由客户端传：ai_score 取 submissions.ai_score（AI 的原始分），teacher_score
    取 submissions.teacher_score（F6 刚写进去的值）。前端把本接口串在 F6 之后发，
    正是为了让 teacher_score 有值——先发的话这行记录的「偏差对比」就没有意义了
    （spec 3.9）。

    **本函数不碰 flask.session**：当前教师 id 由路由用 current_user_id() 取出后传进来。
    这条不变量写在 app/api/auth.py 的模块文档里（为的是 service 能脱离请求上下文测试），
    既有先例是 demos_segments_annotations.py:114 的 teacher_id=current_user_id()。
    """
    sub = homeworks_repo.get_submission(db, submission_id)
    if sub is None:
        raise BusinessError(404, "提交不存在")

    # 这里**故意不校验 sub.status**（spec 3.5）：`ai_scored` 也能写校准，此时下面的
    # teacher_score 读出来是 None（F6 还没写过）。别顺手加一个「必须 reviewed」的
    # 前置判断——文档没把校准与终审绑定，加了会让「先勾校准再打分」这个顺序直接 422。

    row = homeworks_repo.get_calibration(db, submission_id, teacher_id)

    if data.bias_mode is None:
        # 撤销：删行而不是写一行 null。写 null 会留下一条无意义的记录，且 F5 的
        # 「取最新一条」会读到它、把有值的旧行盖掉（spec 3.4）。
        if row is not None:
            db.delete(row)
            db.commit()
        return None

    if row is None:
        row = ScoreCalibration(submission_id=submission_id, teacher_id=teacher_id)
        homeworks_repo.add_calibration(db, row)

    # 复用 apply_review：它的名字带 review，实现是通用的「把 changes 里的列写到 row 上」
    # （见它自己的文档字符串）。不为 F7 改名——改名会波及已上线的 F6。
    homeworks_repo.apply_review(db, row, {
        "bias_mode": data.bias_mode,
        "ai_score": sub.ai_score,
        "teacher_score": sub.teacher_score,
    })
    # 刷新到本次，否则 F5 的「取最新一条」永远排到第一次勾选（spec 3.3）。
    # 不用 func.now()：赋进属性后拿到的是表达式对象而不是 datetime，拿去构造出参会炸。
    # 同 review_submission 对 reviewed_at 的处理。
    row.created_at = datetime.now()

    # 出参在 commit **之前**构造：commit 会让 ORM 实例的属性过期，之后再读会多发一条
    # SELECT 把整行重新拉一遍。同 review_submission。
    out = SubmissionCalibration.model_validate(row)
    db.commit()
    return out


def save_result(metadata: dict, result: dict) -> None:
    """F3 worker：把占位提交回填成 ai_scored，并更新 BKT。

    在请求之外执行，所以用 `session_scope()` 而不是 `get_db()`。提交行与
    BKT 必须在同一个事务里：只写分数不写 BKT 会让掌握度停在旧值，只写 BKT
    不写提交则 source_id 指向一个不存在的行。任何一步失败都抛出去，由
    run_analysis 把任务置为 failed 并调用 discard_pending 删掉占位行。
    """
    from app.db import session_scope

    with session_scope() as db:
        submission_id = metadata.get("submission_id")
        sub = db.get(Submission, submission_id) if submission_id is not None else None
        if sub is None:
            raise BusinessError(500, "作业提交记录不存在")
        if sub.status != "submitted":
            # 重复任务或行已被处理；discard_pending 的 status 守卫保证不会删已评分行。
            raise BusinessError(
                500, f"作业提交状态不是 submitted（当前 {sub.status!r}）"
            )

        before, after = practice_service.apply_bkt(
            db,
            student_id=sub.student_id,
            dimensions=result.get("dimensions"),
            source_type="homework",
            source_id=sub.id,
        )

        cdm = result.get("cdm") or {}
        sub.ai_score = result.get("overall")
        # 与既有 5 条种子提交同形（defects / overallConfidence），并补上 F5
        # 已经在读的 words。不写 featureMatrix（B4 没有这个数据源），
        # 不写 dimensions（五维只在当次 B4/redis 里，TTL 1 小时）。
        sub.ai_detail = {
            "words": result.get("words"),
            "defects": cdm.get("defects") if cdm else None,
            "overallConfidence": cdm.get("overallConfidence") if cdm else None,
        }
        sub.bkt_before = before
        sub.bkt_after = after
        sub.status = "ai_scored"


def discard_pending(metadata: dict) -> None:
    """F3 分析失败时删除仍处于 submitted 且未评分的占位行，让学生能重交。

    守卫两个条件缺一不可：`status == 'submitted'` 与 `ai_score is None`。
    若 save_result 已经成功、只是 redis 的 done 写失败，行已是 ai_scored，
    这里不会删——代价是学生看到「分析失败」但作业已算分，重交会 422。
    这是极窄的窗口，按「不丢已算出的成绩」处理。
    """
    from app.db import session_scope

    submission_id = metadata.get("submission_id")
    if submission_id is None:
        return
    with session_scope() as db:
        sub = db.get(Submission, submission_id)
        if sub is not None and sub.status == "submitted" and sub.ai_score is None:
            db.delete(sub)

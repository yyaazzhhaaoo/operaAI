from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.common.errors import BusinessError
from app.models import Homework, ScoreCalibration, Submission
from app.repositories import audio_repo, homeworks_repo, user_repo
from app.schemas.homework import (
    BktChange,
    CdmTag,
    HomeworkListItem,
    HomeworkListResponse,
    LyricWord,  # noqa: F401  # 本次无使用点（lyrics 恒为 []），
    #                        # 但它是 SubmissionDetailResponse.lyrics 的元素类型
    PendingSubmissionItem,
    PendingSubmissionListResponse,
    SubmissionCalibration,
    SubmissionCalibrationIn,
    SubmissionDetailResponse,
    SubmissionReviewIn,
    SubmissionReviewResponse,
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


def _overall_confidence(ai_detail: dict | None) -> float | None:
    """`ai_detail.overallConfidence`，过一遍 _num 挡掉 `"0.68"` 这类字符串。"""
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

    `lyrics` 与 `dimensions` 是**显式空位**——功能 4.4 与 4.5 在库里没有数据源，理由
    见 spec 2.5 与 `SubmissionDetailResponse` 的文档字符串。它们不是本次没做，是数据
    不存在，所以出 `[]` 与 `None` 而不是省略键。
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
        lyrics=[],                # 功能 4.4 逐字偏差无数据源，显式空位
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

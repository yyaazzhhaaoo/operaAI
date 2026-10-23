# -*- coding: utf-8 -*-
"""能力追踪页（BKT）的后端取数。

服务 H1 芯片列表、H2 综合统计 + 掌握度预警、H3 P(L) 历史曲线、H4 练习事件
时间轴。技法明细表（H5）仍由前端用页面内的演示数据组织，本模块不涉及。
"""
import math
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.common.errors import BusinessError
from app.models.practice import BktHistory
from app.repositories import (
    bkt_history_repo,
    homeworks_repo,
    practice_records_repo,
    user_repo,
)

# 八维技法。刻意不复用 dashboard_service.SKILLS（那个只有 6 维，缺颤音与装饰音
# 技巧）——能力追踪页展示的就是这 8 个技法，名单筛选也必须按 8 维判「齐全」。
SKILLS: tuple[str, ...] = (
    "音准控制",
    "气息支撑",
    "滑音",
    "拖腔",
    "归韵咬字",
    "节奏感知",
    "颤音",
    "装饰音技巧",
)

# 与 tracking.html 的 getTrend 保持一致：差值超过 2 个百分点才算上升/下降。
TREND_THRESHOLD = 0.02

BEIJING = ZoneInfo("Asia/Shanghai")

# 功能 6.2 的掌握度分级线，与 tracking.html 的 getPLColor 一致。
MASTERED_LINE = 0.85
WEAK_LINE = 0.60

# 时间范围筛选（功能 6.6）：7 / 14 / 30 / 90 / 全部（页面的「全部」按 365 天算）。
MAX_HISTORY_DAYS = 365

# 掌握度预警（6.7）与事件时间轴（6.8）的窗口。卡片标题写的是「最近 30 天」。
ALERT_WINDOW_DAYS = 30
EVENT_WINDOW_DAYS = 30
DETAIL_WINDOW_DAYS = 30
# 「连续下降」= 最近 3 条记录严格递减且首末降幅 ≥ 2 个百分点，与趋势箭头同一阈值。
DECLINE_MIN_DROP = 0.02


def _overall_trend(rows: list[BktHistory]) -> dict[int, str | None]:
    """每个学生的整体趋势，{students.id: "up"/"down"/"flat"/None}。

    传入的是 get_recent_by_skill(limit=2) 的结果：每个 (student_id, skill)
    组内按 recorded_at 倒序至多两条。对每个技法取「最新 - 次新」的差值，再对
    有两条以上记录的技法求平均——一个学生 8 个技法各自的变化不能因为记录了
    18 次的技法和记录 2 次的技法被等权而失真。

    不足两条记录的技法不参与平均；一个学生所有技法都不足两条时返回 None
    （「记录不足，没有趋势可言」），不能谎报 flat。
    """
    by_student: dict[int, dict[str, list[float]]] = {}
    for row in rows:
        by_student.setdefault(row.student_id, {}).setdefault(row.skill, []).append(row.p_l)

    out: dict[int, str | None] = {}
    for student_id, skills in by_student.items():
        diffs = [pts[0] - pts[1] for pts in skills.values() if len(pts) >= 2]
        if not diffs:
            out[student_id] = None
            continue
        avg = sum(diffs) / len(diffs)
        if avg > TREND_THRESHOLD:
            out[student_id] = "up"
        elif avg < -TREND_THRESHOLD:
            out[student_id] = "down"
        else:
            out[student_id] = "flat"
    return out


def roster(db: Session) -> dict:
    """能力追踪页的学生芯片列表。

    只出八维技法齐全的学生（口径见 user_repo.get_students_with_all_skills）：
    这样每个芯片点进去都有完整的 8 条曲线，不会出现大片空列。
    avatar / level 允许为空，前端自行兜底占位。
    """
    students = user_repo.get_students_with_all_skills(db, list(SKILLS))
    trends = _overall_trend(bkt_history_repo.get_recent_by_skill(db, limit=2))
    return {
        "students": [
            {
                "id": student_id,
                "name": name,
                "level": level,
                "avatar": avatar,
                "trend": trends.get(student_id),
            }
            for student_id, name, level, avatar in students
        ]
    }


def _beijing_now() -> datetime:
    """当前北京时间，naive。

    库里 bkt_history / practice_records 的 recorded_at / created_at 存的是
    北京墙上时间（理由见 dashboard_service._beijing_now），这里显式取同一时区。
    """
    return datetime.now(BEIJING).replace(tzinfo=None)


def _alerts(
    db: Session, student_id: int, latest: dict[str, float], now: datetime
) -> list[dict]:
    """掌握度预警（功能 6.7）。文档只写「P(L)<0.60 或连续下降」，这里定死：

    - danger：该技法最新 P(L) < 0.60（与 6.2 的薄弱线同一条）；
    - warn：近 30 天内该技法最近 3 条 BKT 记录严格递减，且首末降幅 ≥ 0.02。
      用记录级而不是日级曲线：BKT 只在练习/测试后写行，日级曲线会把同一天的
      多次更新压成一个点，「连续」就无从谈起。只看 30 天内的记录，几个月前的
      旧记录不参与判定。
    - 同一技法 danger 优先，不重复报；结果按严重度、P(L) 升序。

    返回结构化字段，文案由页面拼（页面措辞与其他卡片保持一致）。
    """
    since = datetime.combine(
        now.date() - timedelta(days=ALERT_WINDOW_DAYS - 1), time.min
    )
    recent: dict[str, list[float]] = {}
    for row in bkt_history_repo.get_history_for_student_since(db, student_id, since):
        if row.skill in SKILLS:
            recent.setdefault(row.skill, []).append(row.p_l)

    alerts: list[dict] = []
    for skill in SKILLS:
        p_l = latest.get(skill)
        if p_l is None:
            continue
        if p_l < WEAK_LINE:
            alerts.append({"skill": skill, "type": "danger", "p_l": p_l, "from_p_l": None})
            continue
        points = recent.get(skill) or []
        if len(points) >= 3:
            first, middle, last = points[-3], points[-2], points[-1]
            if first > middle > last and first - last >= DECLINE_MIN_DROP:
                alerts.append(
                    {"skill": skill, "type": "warn", "p_l": p_l, "from_p_l": first}
                )

    alerts.sort(key=lambda a: (a["type"] != "danger", a["p_l"]))
    return alerts


def overview(db: Session, student_id: int) -> dict:
    """综合统计四项（功能 6.2 / 接口 H2）。

    文档只给了四个指标名、没给算法，这里定死并写进接口注释：
    - 综合掌握度：该生每个技法最新 P(L) 的均值，只统计 SKILLS 这 8 维；
    - 已掌握技法：最新 P(L) >= 0.85 的个数；skill_count 是参与统计的技法数；
    - 薄弱技法：最新 P(L) < 0.60 的个数；
    - 本周练习/作业次数：practice_records 本周（周一起、北京日期）条数，
      排除摸底测试。与看板 5.6 的 week_practice_count 同一口径——作业练习
      本身也落 practice_records，再数 submissions 会重复计数。
    - 7 日变化：两端都取「该技法截至该时刻的最新值」，只比较两端都有记录的
      技法；一个都没有时返回 None，前端显示「—」而不是 0。
    - alerts：功能 6.7 的掌握度预警，口径见 `_alerts`。
    """
    if user_repo.get_student_profile(db, student_id) is None:
        raise BusinessError(404, "学生不存在")

    latest = {
        row.skill: row.p_l
        for row in bkt_history_repo.get_latest_per_skill_for_student(db, student_id)
        if row.skill in SKILLS
    }
    values = [latest[skill] for skill in SKILLS if skill in latest]
    overall = sum(values) / len(values) if values else None

    now = _beijing_now()
    prev = {
        row.skill: row.p_l
        for row in bkt_history_repo.get_latest_per_skill_for_student_before(
            db, student_id, now - timedelta(days=7)
        )
        if row.skill in SKILLS
    }
    common = [skill for skill in SKILLS if skill in latest and skill in prev]
    delta = None
    if common:
        current_avg = sum(latest[skill] for skill in common) / len(common)
        prev_avg = sum(prev[skill] for skill in common) / len(common)
        delta = current_avg - prev_avg

    days = practice_records_repo.get_practice_days(db, [student_id]).get(student_id, {})
    today = now.date()
    week_start = today - timedelta(days=today.weekday())

    return {
        "student_id": student_id,
        "overall": overall,
        "mastered_count": sum(1 for v in values if v >= MASTERED_LINE),
        "skill_count": len(values),
        "week_practice_count": sum(n for d, n in days.items() if d >= week_start),
        "weak_count": sum(1 for v in values if v < WEAK_LINE),
        "overall_delta_7d": delta,
        # 功能 6.7。文档没有对应接口，随 H2 一起返回，免得每个学生多打一次请求
        "alerts": _alerts(db, student_id, latest, now),
    }


def bkt_history(db: Session, student_id: int, days: int) -> dict:
    """P(L) 历史曲线（功能 6.3 / 6.6 / 接口 H3）。

    返回逐日、与 dates 等长的序列：当天有记录取当天最后一条，无记录沿用前值。
    画成阶梯而不是只给记录点，是因为 BKT 是掌握度信念——两次练习之间不变，
    断线会把「没练」误读成「掌握度未知」。窗口内一条记录都没有的技法不进
    series：那种情况只能画出一条水平线，反而是误导。
    """
    if not 1 <= days <= MAX_HISTORY_DAYS:
        raise BusinessError(400, f"days 必须是 1-{MAX_HISTORY_DAYS} 的整数")
    if user_repo.get_student_profile(db, student_id) is None:
        raise BusinessError(404, "学生不存在")

    today = _beijing_now().date()
    start = today - timedelta(days=days - 1)
    since = datetime.combine(start, time.min)

    # skill -> {北京日期: 当天最终 P(L)}
    daily: dict[str, dict[date, float]] = {}
    for row in bkt_history_repo.get_history_for_student_since(db, student_id, since):
        if row.skill in SKILLS and row.recorded_at is not None:
            daily.setdefault(row.skill, {})[row.recorded_at.date()] = row.p_l

    # 窗口开始前的最后值：曲线要从「练习前已有的水平」起画，不能从 0 或 first record 起
    baseline = {
        row.skill: row.p_l
        for row in bkt_history_repo.get_latest_per_skill_for_student_before(
            db, student_id, since
        )
        if row.skill in SKILLS
    }

    dates = [start + timedelta(days=i) for i in range(days)]

    series: dict[str, list[float | None]] = {}
    for skill in SKILLS:
        day_values = daily.get(skill)
        if not day_values:
            continue
        current = baseline.get(skill)
        points: list[float | None] = []
        for d in dates:
            if d in day_values:
                current = day_values[d]
            points.append(current)
        series[skill] = points

    return {
        "student_id": student_id,
        "days": days,
        "dates": [d.isoformat() for d in dates],
        "series": series,
    }


def skills_detail(db: Session, student_id: int) -> dict:
    """技法详情表（功能 6.9 / 接口 H5）。

    每个技法一行：
    - current / p7 / p30：最新值，以及「截至 7 天前 / 30 天前」的最新值。
      取状态值而不是窗口均值：BKT 是信念，两次练习之间不变。
    - trend / delta：current 对 7 天前，阈值与名单趋势一致（2 个百分点）。
    - confidence：最新一条记录的置信度。
    - practice_count：近 30 天实际更新该技法的练习次数（BKT 行按来源去重）。
    - est_practices / est_state：按近 30 天的「每次平均增量」外推到达 0.85
      还需要的练习次数。每次增量 = (current - 窗口起点值) / 更新次数；窗口
      起点值缺失时从窗口内第一条记录起算，至少要有 2 次更新才估。
      est_state 为 mastered（已达标）/ needs_practice（增量 ≤ 0）/
      insufficient（有效更新不足）/ ok（见 est_practices）。

    p7 / p30 查不到记录时给 None，前端显示「—」——「那时候还没练过」与
    「掌握度是 0」是两件事。
    """
    if user_repo.get_student_profile(db, student_id) is None:
        raise BusinessError(404, "学生不存在")

    now = _beijing_now()
    latest = {
        row.skill: row
        for row in bkt_history_repo.get_latest_per_skill_for_student(db, student_id)
    }
    p7 = {
        row.skill: row.p_l
        for row in bkt_history_repo.get_latest_per_skill_for_student_before(
            db, student_id, now - timedelta(days=7)
        )
    }
    p30 = {
        row.skill: row.p_l
        for row in bkt_history_repo.get_latest_per_skill_for_student_before(
            db, student_id, now - timedelta(days=30)
        )
    }

    since = datetime.combine(
        now.date() - timedelta(days=DETAIL_WINDOW_DAYS - 1), time.min
    )
    window: dict[str, list[BktHistory]] = {}
    for row in bkt_history_repo.get_history_for_student_since(db, student_id, since):
        if row.skill in SKILLS:
            window.setdefault(row.skill, []).append(row)
    baseline = {
        row.skill: row.p_l
        for row in bkt_history_repo.get_latest_per_skill_for_student_before(
            db, student_id, since
        )
    }

    skills = []
    for skill in SKILLS:
        latest_row = latest.get(skill)
        current = latest_row.p_l if latest_row else None
        prev7 = p7.get(skill)
        prev30 = p30.get(skill)

        trend = None
        delta = None
        if current is not None and prev7 is not None:
            delta = current - prev7
            if delta > TREND_THRESHOLD:
                trend = "up"
            elif delta < -TREND_THRESHOLD:
                trend = "down"
            else:
                trend = "flat"

        rows = window.get(skill) or []
        sources = {
            (row.source_type, row.source_id)
            if row.source_type and row.source_id is not None
            else ("row", row.id)
            for row in rows
        }

        est_practices = 0
        est_state = "insufficient"
        if current is not None:
            if current >= MASTERED_LINE:
                est_state = "mastered"
            else:
                start = baseline.get(skill)
                values = ([start] if start is not None else []) + [
                    row.p_l for row in rows
                ]
                steps = len(values) - 1
                if steps >= 2:
                    avg = (current - values[0]) / steps
                    if avg <= 0:
                        est_state = "needs_practice"
                    else:
                        est_state = "ok"
                        est_practices = max(1, math.ceil((MASTERED_LINE - current) / avg))

        skills.append({
            "skill": skill,
            "current": current,
            "p7": prev7,
            "p30": prev30,
            "trend": trend,
            "delta": delta,
            "confidence": latest_row.confidence if latest_row else None,
            "practice_count": len(sources),
            "est_practices": est_practices if est_state in ("mastered", "ok") else None,
            "est_state": est_state,
        })

    return {"student_id": student_id, "skills": skills}


def events(db: Session, student_id: int) -> dict:
    """练习事件时间轴（功能 6.8 / 接口 H4）。

    固定最近 30 天（与卡片标题一致），按「日期 + 类型」合并：一次摸底测试
    会在 practice_records 里留下逐段的多行，逐行展示会把时间轴刷成同一分钟
    的十几条。作业提交按次展示——同一天可能有多份作业，合并会丢掉标题。

    技法标签取这次事件真正写入的 `bkt_history` 行（source_type + source_id）；
    F3 复用练习成绩的提交没有 BKT 行，回退到 `submissions.bkt_after` 的键。
    都没有就留空，不拿 `homeworks.focus_skills` 硬凑：那份数据的维度名
    （音准/发声等）与 8 个技法名不一一对应。
    """
    if user_repo.get_student_profile(db, student_id) is None:
        raise BusinessError(404, "学生不存在")

    now = _beijing_now()
    since = datetime.combine(
        now.date() - timedelta(days=EVENT_WINDOW_DAYS - 1), time.min
    )

    # (source_type, source_id) -> 这次事件更新的技法
    skills_by_source: dict[tuple[str, int], list[str]] = {}
    for row in bkt_history_repo.get_history_for_student_since(db, student_id, since):
        if not row.source_type or row.source_id is None:
            continue
        skills = skills_by_source.setdefault((row.source_type, row.source_id), [])
        if row.skill in SKILLS and row.skill not in skills:
            skills.append(row.skill)

    # practice 类按 (日期, 类型) 合并；提交一条一份，键不冲突
    buckets: dict[tuple, dict] = {}
    for record, _segment_title in practice_records_repo.list_since(
        db, student_id, since
    ):
        created = record.created_at
        if created is None:
            continue
        source = record.source or "practice"
        event_type = (
            "test" if source == "cat_test"
            else ("homework" if source == "homework" else "practice")
        )
        bucket = buckets.setdefault(
            (created.date(), event_type),
            {
                "type": event_type,
                "title": {"test": "摸底测试", "homework": "作业练习"}.get(
                    event_type, "自主练习"
                ),
                "datetime": created,
                "count": 0,
                "scores": [],
                "skills": [],
            },
        )
        bucket["count"] += 1
        if created > bucket["datetime"]:
            bucket["datetime"] = created
        if record.ai_score is not None:
            bucket["scores"].append(record.ai_score)
        for skill in skills_by_source.get((source, record.id), []):
            if skill not in bucket["skills"]:
                bucket["skills"].append(skill)

    for submission, homework_title in homeworks_repo.list_submissions_since(
        db, student_id, since
    ):
        skills = list(skills_by_source.get(("homework", submission.id), []))
        if not skills:
            merged = submission.bkt_after or submission.bkt_before or {}
            skills = [skill for skill in merged if skill in SKILLS]
        buckets[("submission", submission.id)] = {
            "type": "homework",
            "title": homework_title or "作业提交",
            "datetime": submission.submitted_at,
            "detail": (
                f"AI 评分 {submission.ai_score:.1f}"
                if submission.ai_score is not None
                else "已提交"
            ),
            "skills": skills,
        }

    out: list[dict] = []
    for bucket in buckets.values():
        if "count" in bucket:
            detail = f"{bucket['count']} 次"
            if bucket["scores"]:
                avg = sum(bucket["scores"]) / len(bucket["scores"])
                detail += f" · 平均 {avg:.1f} 分"
        else:
            detail = bucket["detail"]
        dt = bucket["datetime"]
        if dt is None:
            continue
        out.append({
            "date": dt.date().isoformat(),
            "time": dt.strftime("%H:%M"),
            "type": bucket["type"],
            "title": bucket["title"],
            "detail": detail,
            "skills": [skill for skill in SKILLS if skill in set(bucket["skills"])],
            "_dt": dt,
        })

    out.sort(key=lambda event: event["_dt"], reverse=True)
    for event in out:
        event.pop("_dt")

    return {"student_id": student_id, "days": EVENT_WINDOW_DAYS, "events": out}

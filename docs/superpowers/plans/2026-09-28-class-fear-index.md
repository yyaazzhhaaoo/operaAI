# 班级畏难倾向指数（G6 `fear_index`）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `GET /api/dashboard/process-metrics` 里恒为 `null` 的 `fear_index` 换成按《班级看板--班级畏难倾向指数说明.md》算出的 0~1 真实值，并让 `dashboard.html` 渲染数值 + 较上周趋势 + 畏难等级。

**Architecture:** 5 个分量各自算一个 0~1 的比率（练习中断率、重试放弃率、连续未练习率、关键词触发率、作业未提交率），按固定权重 0.2 加权求和。4 个按周切的分量分别在「本周」「上周」两个窗口各算一遍，作业项不按周切、两窗口共用。数据访问全部落在 `app/repositories/`，计算落在 `app/services/dashboard_service.py`，接口层不动。

**Tech Stack:** Python 3.11 / Flask / SQLAlchemy 2.x（`select()` 2.0 风格）/ PostgreSQL / Celery（本次不涉及）/ 原生 JS 单页

**依据 spec:** `docs/superpowers/specs/2026-09-28-class-fear-index-design.md`

## Global Constraints

- **不新增测试框架。** 本仓库当前**没有任何测试文件**（`find . -name "test_*.py"` 为空、无 `tests/` 目录、无 pytest 依赖），spec 第 8 节已明确本次不建。每个 Task 的验证一律用**对真库跑的 python 单行片段**，命令与预期输出都写在步骤里——不要 `pip install pytest`，不要新建 `tests/`。
- **Python 解释器一律用 `.venv/bin/python`**，且**必须先 `cd` 到项目根目录**并 `import sys; sys.path.insert(0,'.')`。PATH 上的 `python`/`pip` 是 pyenv 的 3.12，不是本项目的 venv（见记忆 `pip-mirror-and-interpreter-gotchas`）。
- **`app/config.py` 用 `__file__` 定位 `.env`**，与启动时的工作目录无关；`app/db.py` 的 `SessionLocal` 直接可用。
- **时区：库里 `created_at` 存的就是北京时间**（`postgresql.conf` 的 timezone 是 `Asia/Shanghai`），服务层取当前时间一律用 `dashboard_service._beijing_now()`，**不要写 `datetime.now()`**。也**不要**加 `AT TIME ZONE` 换算（见记忆 `postgres-stores-beijing-time`）。
- **不改 `schema.sql` / `seed.sql` / `app/models/*`**——本次没有建表、建列、建索引。
- **不改 `app/api/dashboard.py`**——该路由已用 `model_dump(mode="json")`，新增的 float 字段自动可序列化。
- **`student_id` 列指向 `students.id` 不是 `users.id`**（`DOC_ISSUES.md` 第 21 条）。在册名单一律经 `user_repo.get_student_roster(db)` 拿，不要自己 join `users`。
- **当前真库基线**（2026-09-28 实测，`process_metrics` 的现有输出）：`week_start='2026-09-28'`、`student_count=9`、`avg_duration_sec=0.0`、`avg_duration_sec_last_week=18.333333333333332`、`avg_practice_count=0.0`、`avg_practice_count_last_week=0.8888888888888888`。**前三项之外的这两个本周值在本次改动后必须保持不变**（Task 3 的回归检查）。
- **本周一是 2026-09-28（就是今天）**，所以本周窗口 `[2026-09-28 00:00, 现在)` 内**一条练习记录都没有**（最近一条是 09-23）；上周窗口 `[2026-09-21 00:00, 2026-09-28 00:00)` 内有 8 条。写验证断言时按这个事实来。
- 注释、commit message 一律中文；标识符英文（用户全局约定）。

---

## 文件结构

| 文件 | 职责 | 本次改动 |
|---|---|---|
| `app/repositories/practice_records_repo.py` | 练习记录的 SQL 封装 | +3 个函数：中断判定行、重试分组行、最后练习日期 |
| `app/repositories/chat_repo.py` | **新建**，对话消息的 SQL 封装 | `count_user_messages` |
| `app/repositories/homeworks_repo.py` | 作业与提交的 SQL 封装 | +`get_submission_stats` |
| `app/services/dashboard_service.py` | 指标编排与口径 | +3 组常量、+2 个私有函数、重写 `process_metrics` |
| `app/schemas/dashboard.py` | 响应契约 | `ProcessMetrics` +1 字段、重写注释 |
| `dashboard.html` | 班级看板页 | `fmtTrend` +`invert`、畏难卡片渲染、更新注释 |
| `DOC_ISSUES.md` | 需求文档问题登记 | 第 24 条追加 |

---

## Task 1: 练习行为的三条查询（`practice_records_repo`）

**Files:**
- Modify: `app/repositories/practice_records_repo.py`（在文件末尾追加，保留现有 4 个函数不动）

**Interfaces:**
- Consumes: 无
- Produces（Task 3 依赖这三个签名）:
  - `get_interrupt_rows(db: Session, start: datetime, end: datetime) -> list[tuple[float, float]]` —— 返回 `[(本次练习时长秒, 该唱段时长秒)]`，**左闭右开** `[start, end)`，两端任一缺失的行不在结果里
  - `get_retry_rows(db: Session, start: datetime, end: datetime) -> list[tuple[int, int, float | None, datetime]]` —— 返回 `[(student_id, segment_id, ai_score, created_at)]`，`segment_id` 非空，**按 `created_at` 升序**，`ai_score` 可为 `None`
  - `get_last_practice_dates(db: Session, student_ids: list[int], until: datetime) -> dict[int, date]` —— `{students.id: 最后一次练习的北京日期}`，**含** `until` 当天，没练过的不在字典里

- [ ] **Step 1: 追加三个查询函数**

在 `app/repositories/practice_records_repo.py` 末尾追加（文件顶部现有的 `from datetime import date, datetime, timedelta` / `from sqlalchemy import Date, cast, desc, select, func, extract` / `from app.models import PracticeRecord, Student, User` **已经够用，不要新增 import**）：

```python
# ---- 以下三个查询供「班级畏难倾向指数」（功能 5.8）用 ----
#
# 时区口径与上面 `get_weekly_totals` / `get_practice_days` 一致：created_at 存的
# 就是北京墙上时间，直接比，不做 AT TIME ZONE 换算。


def get_interrupt_rows(db: Session, start: datetime, end: datetime) -> list[tuple[float, float]]:
    """判「练习中断」用的原始行，[(本次练习时长秒, 该唱段时长秒)]，窗口左闭右开。

    practice_records 里**没有**任何「学生主动退出」的字段，只能拿「录下来的时长
    明显短于唱段时长」当「没唱完」的近似（见设计第 3.1 节）。比例阈值不在这里判，
    由 service 层的 INTERRUPT_RATIO 决定——本层只负责把两个时长取齐。

    只取两端都在的行：segment_id 为空、唱段 duration 为空或非正、本次 duration_sec
    为空，任缺其一就判不了，**分子分母都不含它**，不用「班级人均时长」之类的第二把
    尺子兜底。
    """
    if start >= end:
        return []
    rows = db.execute(
        select(PracticeRecord.duration_sec, Segment.duration)
        .join(Segment, Segment.id == PracticeRecord.segment_id)
        .where(Segment.duration > 0)
        .where(PracticeRecord.duration_sec.is_not(None))
        .where(PracticeRecord.created_at >= start)
        .where(PracticeRecord.created_at < end)
    ).all()
    return [(float(dur), float(seg_dur)) for dur, seg_dur in rows]


def get_retry_rows(db: Session, start: datetime, end: datetime) -> list[tuple[int, int, float | None, datetime]]:
    """判「重试放弃」用的原始行，[(student_id, segment_id, ai_score, created_at)]。

    按 `created_at` **升序**返回：service 层判「最后一遍有没有刷新最好成绩」依赖
    这个顺序，不要在那边再排一次。

    segment_id 为空的行取不到——按唱段分组是这条判据的前提。ai_score 为空的行
    **照常返回**（不过滤）：要不要弃用整组由 service 层决定，本层不替它做取舍。
    """
    if start >= end:
        return []
    rows = db.execute(
        select(
            PracticeRecord.student_id,
            PracticeRecord.segment_id,
            PracticeRecord.ai_score,
            PracticeRecord.created_at,
        )
        .where(PracticeRecord.segment_id.is_not(None))
        .where(PracticeRecord.created_at >= start)
        .where(PracticeRecord.created_at < end)
        .order_by(PracticeRecord.created_at)
    ).all()
    return [(sid, seg_id, score, at) for sid, seg_id, score, at in rows]


def get_last_practice_dates(db: Session, student_ids: list[int], until: datetime) -> dict[int, date]:
    """每个学生在 `until`（含当天）之前的最后一次练习日期，{students.id: 北京日期}。

    没练过的学生不在字典里——调用方要自己把「不在字典里」当成「从未练过」处理，
    不能当成 0 或今天（见设计第 3.3 节）。

    返回 date 而不是 datetime：连续未练习天数是按**北京日期**相减的，时分秒不参与。
    用 cast 取日期，与 `get_practice_days` 同一套口径。
    """
    if not student_ids:
        return {}
    day = cast(PracticeRecord.created_at, Date)
    rows = db.execute(
        select(PracticeRecord.student_id, func.max(day))
        .where(PracticeRecord.student_id.in_(set(student_ids)))
        .where(PracticeRecord.created_at.is_not(None))
        .where(PracticeRecord.created_at <= until)
        .group_by(PracticeRecord.student_id)
    ).all()
    return {sid: d for sid, d in rows if d is not None}
```

- [ ] **Step 2: 跑查询确认能出数且口径正确**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from datetime import datetime
from app.db import SessionLocal
from app.repositories import practice_records_repo as r, user_repo

THIS = datetime(2026, 9, 28); LAST = datetime(2026, 9, 21)
with SessionLocal() as db:
    print('本周中断行:', r.get_interrupt_rows(db, THIS, datetime(2026, 9, 28, 23, 59)))
    print('上周中断行:', r.get_interrupt_rows(db, LAST, THIS))
    print('上周重试行:', r.get_retry_rows(db, LAST, THIS))
    ids = [row[0] for row in user_repo.get_student_roster(db)]
    print('名单:', len(ids), '最后练习日:', r.get_last_practice_dates(db, ids, THIS))
"
```

预期输出（2026-09-28 实测）：
- `本周中断行: []` —— 本周一就是今天，窗口内无记录
- `上周中断行: [(21.0, 24.7), (23.0, 44.7), (19.0, 24.7), (11.0, 24.7)]` —— 4 条，来自 id 67/66/64/62。这 4 条的 `created_at` 都是 `14:32`（同一秒），`order_by created_at` 对并列行不保证顺序，**排列顺序可以不同，集合必须一致**
  - 若条数不符，**停下来核对**：先在 psql 里 `select id,student_id,segment_id,ai_score,created_at from practice_records order by created_at;` 看真值，不要改查询去迎合
- `上周重试行:` **4 条** —— `(55,78,71.3)`、`(54,79,87.4)`、`(53,78,78.9)`、`(52,78,85.7)`。注意**不是 6 条**：`ai_score` 为 `None` 的那 4 条记录（id 60/63/65/68）`segment_id` **同时也是 NULL**，已被过滤，所以窗口内根本没有「有序段但没分数」的行
- `名单: 9`，`最后练习日` 是 6 项的字典（键 `students.id` = 50~55，值是 `datetime.date`；9 名在册学生里有 3 名从未练过，**不在字典里**）

- [ ] **Step 3: 提交**

```bash
git add app/repositories/practice_records_repo.py
git commit -m "feat: 练习记录新增畏难指数所需的三条查询

中断判定行、重试分组行、最后练习日期，供功能 5.8 的畏难倾向指数使用。"
```

---

## Task 2: 对话与作业的两条查询（`chat_repo` 新建、`homeworks_repo` 追加）

**Files:**
- Create: `app/repositories/chat_repo.py`
- Modify: `app/repositories/homeworks_repo.py`（追加到文件末尾，保留现有 2 个函数不动）

**Interfaces:**
- Consumes: 无
- Produces（Task 3 依赖）:
  - `chat_repo.count_user_messages(db: Session, start: datetime, end: datetime, keywords: tuple[str, ...]) -> tuple[int, int]` —— 返回 `(命中关键词的条数, role='user' 的消息总数)`，窗口左闭右开
  - `homeworks_repo.get_submission_stats(db: Session, student_ids: list[int]) -> tuple[int, int, int]` —— 返回 `(作业总数, 已提交的(作业,学生)去重组合数, 其中逾期提交的组合数)`，**不按周切**

- [ ] **Step 1: 新建 `app/repositories/chat_repo.py`**

```python
"""AI 教练对话（`chat_messages` 表）的数据访问。

目前只有「班级畏难倾向指数」的第 4 个分量在用（功能 5.8）；模块 3 的对话接口
将来接后端时，会话读写也放这里。
"""

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import ChatMessage


def count_user_messages(
    db: Session, start: datetime, end: datetime, keywords: tuple[str, ...]
) -> tuple[int, int]:
    """窗口内 `role='user'` 的消息数与其中命中关键词的条数，(命中, 总数)。

    挫败关键词触发率 = 命中 / 总数（设计第 3.4 节）。**只统计 role='user'**：
    AI 回复里出现「太难」是在描述学生的困难，不是学生的挫败表达，算进去就错了。

    一条消息命中多个关键词只计一次（计数的是「条」不是「命中次数」），所以这里
    用「整体取一次 count + 一个 or_ 条件」，不把词表展开成多条 COUNT 相加。

    分母为 0 的处理（记 0 而不是跳过）由 service 层做——本层只管把两个数报回去。

    子串匹配用 LIKE，词表里没有 % 和 _ 所以不转义；将来若加入带通配符的词，
    这里要补 escape。
    """
    if start >= end:
        return 0, 0

    window = (
        ChatMessage.role == "user",
        ChatMessage.created_at >= start,
        ChatMessage.created_at < end,
    )
    total = db.scalar(select(func.count()).select_from(ChatMessage).where(*window)) or 0
    if total == 0 or not keywords:
        # 没有消息时不必再查一次；词表为空时 or_() 会抛，直接短路
        return 0, total

    hit = db.scalar(
        select(func.count())
        .select_from(ChatMessage)
        .where(*window)
        .where(or_(*[ChatMessage.content.like(f"%{k}%") for k in keywords]))
    ) or 0
    return hit, total
```

- [ ] **Step 2: 在 `app/repositories/homeworks_repo.py` 追加提交统计**

先把顶部 import 改成（当前是 `from sqlalchemy import func, select`）：

```python
from sqlalchemy import Date, cast, distinct, func, select, tuple_
```

然后在文件末尾追加：

```python
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
```

- [ ] **Step 3: 跑查询确认能出数**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from datetime import datetime
from app.db import SessionLocal
from app.repositories import chat_repo, homeworks_repo, user_repo

THIS = datetime(2026, 9, 28); LAST = datetime(2026, 9, 21)
with SessionLocal() as db:
    ids = [row[0] for row in user_repo.get_student_roster(db)]
    print('名单:', len(ids))
    print('本周对话:', chat_repo.count_user_messages(db, THIS, datetime(2026,9,28,23,59), ('太难','算了','不会')))
    print('上周对话:', chat_repo.count_user_messages(db, LAST, THIS, ('太难','算了','不会')))
    print('作业统计:', homeworks_repo.get_submission_stats(db, ids))
"
```

预期输出（已按真库核算）：
- `名单: 9`
- `本周对话: (0, 0)` 与 `上周对话: (0, 0)` —— `chat_messages` 里只有 1 条记录且 `role='assistant'`，任何窗口下 `role='user'` 都是 0 条。**这是真库事实，不是 bug**；第 4 个分量因此恒为 0（spec 第 7 节局限 2）
- `作业统计: (3, 5, 0)` —— 3 份作业；5 个 (作业,学生) 组合全部落在 homework_id=12 上；逾期 0（提交日 08-01/08-02，截止日 08-02，`cast(...) > deadline` 不成立）

- [ ] **Step 4: 提交**

```bash
git add app/repositories/chat_repo.py app/repositories/homeworks_repo.py
git commit -m "feat: 新增对话关键词计数与作业提交统计查询

供功能 5.8 的畏难倾向指数第 4、5 个分量使用。"
```

---

## Task 3: 服务层计算与响应契约（`dashboard_service` + `schemas`）

**Files:**
- Modify: `app/services/dashboard_service.py:1-27`（import 与常量区）、`:375-402`（`process_metrics` 整体重写）
- Modify: `app/schemas/dashboard.py:174-197`（`ProcessMetrics`）

**Interfaces:**
- Consumes: Task 1 的三个函数、Task 2 的两个函数（签名见上）
- Produces:
  - `dashboard_service.FEAR_WEIGHTS: tuple[float, ...]`、`INTERRUPT_RATIO: float`、`FRUSTRATION_KEYWORDS: tuple[str, ...]`、`IDLE_DAYS: int`
  - `dashboard_service._fear_index(db, student_ids, start, end, as_of, homework_rate) -> float`
  - `dashboard_service._homework_skip_rate(db, student_ids) -> float`
  - `ProcessMetrics.fear_index: float | None`、`ProcessMetrics.fear_index_last_week: float | None`

- [ ] **Step 1: 先跑一遍现状，确认畏难指数还是 `None`**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from app.db import SessionLocal
from app.services import dashboard_service as s
with SessionLocal() as db:
    print(s.process_metrics(db).model_dump(mode='json'))
"
```

预期：输出里 `'fear_index': None`，且 `'fear_index_last_week'` **不存在**（`KeyError` 不会抛，字典里就是没这个键）。这就是本任务要改掉的现状。

- [ ] **Step 2: 改 import 与常量**

`app/services/dashboard_service.py` 第 1 行的 import 改成（加 `time`）：

```python
from datetime import date, datetime, time, timedelta
```

第 6-7 行的仓储 import 改成（加 `chat_repo`）：

```python
from app.repositories import user_repo, library_repo, annotations_repo, homeworks_repo, bkt_history_repo, \
    practice_records_repo, graph_repo, chat_repo
```

在现有常量 `SKILLS`（第 27 行）之后追加：

```python
# ---- 畏难倾向指数（功能 5.8）的实现口径 ----
#
# 依据：《班级看板--班级畏难倾向指数说明.md》（2026-09-28 新增，在 ../艺校_docs/）。
# 文档给了 5 个分量名与加权求和的骨架，但**每个分量的判据都没规定**——下面的
# 常量与 _fear_index 里的判定全是实现时定的，逐条列在设计文档第 3 节。

# 5 个分量的权重。文档写「权重可根据教学经验设定（例如各占 20%）」，这里就取均等。
# 某分量分母为 0 时**记 0 而不重新归一化权重**：权重一旦随缺失项浮动，周与周之间的
# 指数就不再可比，趋势本身会失去意义。代价是「某分量长期没数据」会固定压低指数
# （当前 chat_messages 里 role='user' 就有 0 条，压最多 0.2）。
FEAR_WEIGHTS: tuple[float, ...] = (0.2, 0.2, 0.2, 0.2, 0.2)

# 「练习中断」的代理阈值：录下来的时长不足唱段时长的这个比例就算没唱完。
# practice_records 里没有「学生主动退出」的字段，只能拿时长近似。**未经真实素材
# 标定**，与 parse_service.TOP_DB 同类性质；调参改这一个数（越小判得越宽松）。
INTERRUPT_RATIO = 0.5

# 「连续未练习」的天数门槛。文档写「连续多日不再提交」但没给天数，取 7 天——
# 与「本周」同量级，整整一周没碰就算断练。
IDLE_DAYS = 7

# 「挫败关键词」词表。文档只举了「太难」「算了」「不会」三个加一个「等」，
# 其余是实现时补的；只影响第 4 个分量，可按教学经验增删。
FRUSTRATION_KEYWORDS: tuple[str, ...] = (
    "太难", "好难", "不会", "学不会", "算了",
    "放弃", "不想练", "听不懂", "做不到", "坚持不下去",
)
```

- [ ] **Step 3: 重写 `process_metrics` 并新增两个私有函数**

把 `app/services/dashboard_service.py` 的 `process_metrics`（第 375-402 行，从 `def process_metrics` 到 `)` 结束）整段替换为下面三块：

```python
def process_metrics(db: Session) -> ProcessMetrics:
    """班级过程指标（功能 5.8）：本周人均练习时长、人均练习频次、班级畏难倾向指数。

    三项都附一份**上周同口径**值供前端算趋势，差值不在后端做——与 ProcessMetrics
    里两个 avg_* 字段的分工一致。周期、分母、单位的说明见 ProcessMetrics 注释；
    畏难指数的 5 个分量怎么算见 FEAR_WEIGHTS 附近的常量区与 `_fear_index`。
    """
    student_ids = [row[0] for row in user_repo.get_student_roster(db)]

    # 本周一。与 students() 里的 week_start 同一套算法，两个接口的「本周」必须同一天，
    # 否则同一页面上「本周练习 3 次」和「人均 0.2 次」会打架
    now = _beijing_now()
    this_week = now.date() - timedelta(days=now.date().weekday())
    last_week = this_week - timedelta(days=7)

    totals = practice_records_repo.get_weekly_totals(db, student_ids)
    cur_count, cur_sec = totals.get(this_week, (0, 0.0))
    prev_count, prev_sec = totals.get(last_week, (0, 0.0))

    # 在册 0 人时给 0 而不是让 ZeroDivisionError 冒成 500：库是空的时候这个接口
    # 仍然应该能回 200，页面显示 0 比显示「加载失败」诚实
    n = len(student_ids) or 1

    # 畏难指数的两个窗口，左闭右开：
    #   本周 [本周一 00:00, 现在)、上周 [上周一 00:00, 本周一 00:00)
    # 「连续未练习」的截至日取各窗口**已过完的最后一天**——本周是今天，上周是上周日，
    # 两边都是「该周到头来还剩多少人没练」，口径对齐。
    this_week_start = datetime.combine(this_week, time.min)
    last_week_start = datetime.combine(last_week, time.min)
    # 作业未提交率不按周切，两个窗口共用（见 _homework_skip_rate）
    homework_rate = _homework_skip_rate(db, student_ids)

    if student_ids:
        fear = _fear_index(db, student_ids, this_week_start, now, now.date(), homework_rate)
        fear_previous = _fear_index(
            db, student_ids, last_week_start, this_week_start,
            this_week - timedelta(days=1), homework_rate,
        )
    else:
        # 没有在册学生就没有分母。回 None 而不是 0：0 会被读成「班级一点都不畏难」，
        # 与「没有数据」是两回事（见 ProcessMetrics 的注释）。这是 fear_index 唯一
        # 还会回 None 的场景。
        fear = fear_previous = None

    return ProcessMetrics(
        week_start=this_week,
        student_count=len(student_ids),
        avg_duration_sec=cur_sec / n,
        avg_duration_sec_last_week=prev_sec / n,
        avg_practice_count=cur_count / n,
        avg_practice_count_last_week=prev_count / n,
        fear_index=fear,
        fear_index_last_week=fear_previous,
    )


def _homework_skip_rate(db: Session, student_ids: list[int]) -> float:
    """作业未提交率 = (未提交的「作业×学生」组合 + 逾期提交的组合) / 全部组合。

    逾期单独加一遍：它属于「提交了」，但文档把「逾期提交」和「未提交」并列为畏难
    信号，所以要补进来。两项互不相交，相加不会超过总数。
    """
    hw_count, submitted, late = homeworks_repo.get_submission_stats(db, student_ids)
    total = hw_count * len(student_ids)
    if total == 0:
        return 0.0
    # max/min 是防御：正常取不到（submitted 是去重后的组合数，不会超过 total）
    missing = max(total - submitted, 0)
    return min((missing + late) / total, 1.0)


def _fear_index(db: Session, student_ids: list[int], start: datetime, end: datetime,
                as_of: date, homework_rate: float) -> float:
    """一个窗口的班级畏难倾向指数（0~1，越高越畏难），5 个分量加权求和。

    `[start, end)` 是该窗口；`as_of` 是「连续未练习」的截至日（本周=今天，
    上周=上周日）。`homework_rate` 由调用方算好传进来——它不按周切，两个窗口同值。

    每个分量各自归一化到 0~1 后乘固定权重。**分母为 0 的分量记 0、不重新归一化**
    （理由见 FEAR_WEIGHTS 的注释）。
    """
    w = FEAR_WEIGHTS

    # 1. 练习中断率：录下来的时长不足唱段时长的 INTERRUPT_RATIO 就算没唱完。
    #    唱段时长或本次时长缺一不可，判不了的记录分子分母都不进。
    rows = practice_records_repo.get_interrupt_rows(db, start, end)
    interrupted = sum(1 for dur, seg_dur in rows if dur < INTERRUPT_RATIO * seg_dur)
    interrupt_rate = interrupted / len(rows) if rows else 0.0

    # 2. 重试放弃率：同一（学生,唱段）练了不止一遍，最后一遍没刷新自己的最好成绩。
    #    ai_score 有缺值的组**整组弃用**——只拿到一半分数的组，算出来的「有没有提升」
    #    不可信，不如不算。
    scored: dict[tuple[int, int], list[tuple[datetime, float]]] = {}
    unscored: set[tuple[int, int]] = set()
    for sid, seg_id, score, at in practice_records_repo.get_retry_rows(db, start, end):
        key = (sid, seg_id)
        if score is None:
            unscored.add(key)
        else:
            scored.setdefault(key, []).append((at, score))

    retried = [g for k, g in scored.items() if k not in unscored and len(g) >= 2]
    # 仓储层已按 created_at 升序返回；这里再排一次是按时间判「最后一次」的前提，
    # 不依赖上游的顺序（上游改了排序这里也不会错）
    for g in retried:
        g.sort(key=lambda x: x[0])
    given_up = sum(1 for g in retried if g[-1][1] <= max(s for _, s in g[:-1]))
    retry_rate = given_up / len(retried) if retried else 0.0

    # 3. 连续未练习率：截至 as_of，最后一次练习距今 ≥ IDLE_DAYS 天。
    #    **从未练过的学生计入分子**——「一直没练」是畏难的最强信号，不是缺失值。
    if student_ids:
        last_days = practice_records_repo.get_last_practice_dates(db, student_ids, end)
        idle = sum(
            1 for sid in student_ids
            if sid not in last_days or (as_of - last_days[sid]).days >= IDLE_DAYS
        )
        idle_rate = idle / len(student_ids)
    else:
        idle_rate = 0.0

    # 4. 挫败关键词触发率：只算学生自己发的消息（理由见 chat_repo）。
    #    当前真库 role='user' 有 0 条 → 这项恒 0。
    hit, total_msg = chat_repo.count_user_messages(db, start, end, FRUSTRATION_KEYWORDS)
    keyword_rate = hit / total_msg if total_msg else 0.0

    return (w[0] * interrupt_rate
            + w[1] * retry_rate
            + w[2] * idle_rate
            + w[3] * keyword_rate
            + w[4] * homework_rate)
```

- [ ] **Step 4: 改 `ProcessMetrics`**

把 `app/schemas/dashboard.py` 的 `ProcessMetrics`（第 174-197 行）整段替换为：

```python
class ProcessMetrics(BaseModel):
    """班级过程指标（功能 5.8）。

    三个指标的口径都是本次实现定死的（《1-PRD》5.8、《3-功能清单》5.8、
    《5-接口清单》G6 只给了指标名）：

    - 窗口：**本周**（周一起算，北京日期），与 StudentAbility.week_practice_count 同口径；
      每个指标都另带一份上周同口径值，供前端算趋势箭头。不返回差值本身——减法前端做。
    - 分母：**全体在册学生数**，含本周没练过的。所以两个 avg_* 都是「人均」语义：
      avg_duration_sec 是「人均本周练了多少秒」，不是「单次平均时长」。
    - 单位：时长一律**秒**，与 practice_records.duration_sec 同单位，前端显示分钟自行 /60。

    fear_index 的算法来自 2026-09-28 新增的《班级看板--班级畏难倾向指数说明.md》：
    5 个分量各自归一化到 0~1 后按固定权重（各 0.2）加权求和，范围 0~1，越高越畏难。
    分量的具体判据文档没写，实现口径见 dashboard_service 的 FEAR_WEIGHTS 常量区与
    `_fear_index`，以及 docs/superpowers/specs/2026-09-28-class-fear-index-design.md。
    趋势由前端相减得出，与两个 avg_* 同构。
    """
    model_config = ConfigDict(from_attributes=True)
    week_start: date                      # 本周周一，供前端显示统计口径
    student_count: int                    # 分母，可能为 0
    avg_duration_sec: float               # 本周人均练习时长（秒）
    avg_duration_sec_last_week: float     # 上周同口径，算趋势用
    avg_practice_count: float             # 本周人均练习次数
    avg_practice_count_last_week: float   # 上周同口径，算趋势用
    # 本周班级畏难倾向指数，0~1。**唯一回 None 的场景是在册学生数为 0**——那时
    # 没有分母也没有数据，0 会被读成「一点都不畏难」，与「没有数据」是两回事。
    fear_index: float | None
    fear_index_last_week: float | None    # 上周同口径，算趋势用；与 fear_index 同时为 None
```

- [ ] **Step 5: 跑通并核对数字**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from app.db import SessionLocal
from app.services import dashboard_service as s
with SessionLocal() as db:
    print(s.process_metrics(db).model_dump(mode='json'))
    ids = [r[0] for r in __import__('app.repositories.user_repo', fromlist=['x']).get_student_roster(db)]
    print('作业未提交率:', s._homework_skip_rate(db, ids))
"
```

预期（已按真库手算）：
- `student_count: 9`、`week_start: '2026-09-28'`
- `fear_index_last_week ≈ 0.2 × (0.25 + 0.0 + idle率 + 0.0 + 0.8148)`
  - 中断率 = `1/4 = 0.25`（上周 4 条有序段的记录里，只有 `11.0 < 24.7×0.5=12.35` 那一条算中断；`23.0` 对 `44.7` 差一点但没到线）
  - 重试放弃率 = `0`（上周 4 个 (学生,唱段) 分组每组都只有 1 条，没有「练了不止一遍」的组）
  - 关键词触发率 = `0`（`role='user'` 0 条）
  - 作业未提交率 = `(3×9 - 5 + 0) / (3×9) = 22/27 ≈ 0.8148`
  - `idle率` 由打印的最后练习日期决定：截至 2026-09-27，最后练习日 ≤ 2026-09-20 的学生算断练。**这一步必须拿 Step 5 打印的 idle率代入手算，把结果与打印的 `fear_index_last_week` 对到小数点后 4 位**；对不上就是有分量判错了，不要放过
- `fear_index`（本周）≈ `0.2 × (0 + 0 + idle率 + 0 + 0.8148)` —— 本周窗口内 0 条练习记录，所以第 1、2 分量必为 0
- 两个值都落在 `0.0 ~ 1.0` 之间，且**都不是 `None`**（真库有 9 名在册学生）

- [ ] **Step 6: 回归——三个老指标不许变**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from app.db import SessionLocal
from app.services import dashboard_service as s
with SessionLocal() as db:
    m = s.process_metrics(db).model_dump(mode='json')
print({k: m[k] for k in ('week_start','student_count','avg_duration_sec','avg_duration_sec_last_week','avg_practice_count','avg_practice_count_last_week')})
"
```

预期输出与本次改动前**逐字一致**：

```
{'week_start': '2026-09-28', 'student_count': 9, 'avg_duration_sec': 0.0, 'avg_duration_sec_last_week': 18.333333333333332, 'avg_practice_count': 0.0, 'avg_practice_count_last_week': 0.8888888888888888}
```

- [ ] **Step 7: 边界——在册 0 人时必须回 `None` 而不是 500 或 0**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from app.db import SessionLocal
from app.services import dashboard_service as s
with SessionLocal() as db:
    print('空名单:', s._fear_index(db, [], __import__('datetime').datetime(2026,9,21), __import__('datetime').datetime(2026,9,28), __import__('datetime').date(2026,9,27), 0.8148))
"
```

预期：`空名单: 0.21296`（= `0.2 × (中断率 0.25 + 作业 0.8148)`，窗口传的是**上周**，里面有 4 条有序段的记录，中断率不是 0）。**关键是「不抛异常、不出现 `ZeroDivisionError`」，具体数值不是断言点。**

回 `None` 的判断在 `process_metrics` 里而不是 `_fear_index` 里：那是「响应字段」层面的语义（没有分母就没有这个指标），不是计算层面的——`_fear_index` 对空名单算出一个「只含与名单无关的分量」的值是合理的，反正 `process_metrics` 不会用它。

- [ ] **Step 8: 提交**

```bash
git add app/services/dashboard_service.py app/schemas/dashboard.py
git commit -m "feat: 实现班级畏难倾向指数

按《班级看板--班级畏难倾向指数说明.md》的 5 项加权求和实现功能 5.8 的
fear_index，响应新增 fear_index_last_week 供前端算趋势。

文档只给了公式骨架，5 个分量的判据全部是本次实现定的（时长代理的中断率、
未创新高的重试放弃、7 天窗口的连续未练习、内置词表的关键词触发、累计口径
的作业未提交率），逐条记录在设计文档与代码注释里。"
```

---

## Task 4: 前端渲染（`dashboard.html`）

**Files:**
- Modify: `dashboard.html:914-920`（注释）、`:923-927`（`fmtTrend`）、`:956-962`（畏难卡片渲染）

**Interfaces:**
- Consumes: 接口 `data.fear_index`（float 或 null）、`data.fear_index_last_week`（float 或 null）
- Produces: 无（终点是页面）

- [ ] **Step 1: 更新那段已过时的注释**

`dashboard.html` 第 914-920 行现在是：

```js
// ============================================
// 班级过程指标（GET /api/dashboard/process-metrics，功能 5.8）
// ============================================
// 三个坑，改这段前先看：
// (1) 接口的时长是**秒**（与 practice_records.duration_sec 同单位），卡片文案是「分」，所以 /60；
// (2) 接口的「平均」是**人均**（分母 = 全体在册学生，含本周没练过的），不是单次平均；
// (3) 畏难指数文档没有定义算法，接口恒回 null，必须显示「待定义」——绝不能当 0 用，
//     那会读成「班级一点都不畏难」，与「没有数据」是两回事。
// 趋势由前端相减得出：接口一并给上周同口径值，不在后端算差值。
```

替换为：

```js
// ============================================
// 班级过程指标（GET /api/dashboard/process-metrics，功能 5.8）
// ============================================
// 四个坑，改这段前先看：
// (1) 接口的时长是**秒**（与 practice_records.duration_sec 同单位），卡片文案是「分」，所以 /60；
// (2) 接口的「平均」是**人均**（分母 = 全体在册学生，含本周没练过的），不是单次平均；
// (3) 畏难指数现在有真值了（算法见 ../艺校_docs/班级看板--班级畏难倾向指数说明.md），
//     但**在册学生为 0 时接口仍回 null**。null 必须显示「暂无数据」，绝不能当 0 用——
//     那会读成「班级一点都不畏难」，与「没有数据」是两回事；
// (4) 畏难指数**越高越糟**，趋势箭头的颜色要反着来（上升标红），不能让 fmtTrend 用默认映射。
// 趋势由前端相减得出：接口一并给上周同口径值，不在后端算差值。
```

- [ ] **Step 2: 给 `fmtTrend` 加 `invert` 参数**

把第 923-927 行整个函数替换为：

```js
// invert：给「越高越糟」的指标用（目前只有畏难指数）。默认映射是升=绿、降=红，
// 对练习时长/频次成立，对畏难指数恰好相反，所以要能把两个 class 对调。
function fmtTrend(delta, unit, digits, invert) {
  const suffix = unit ? ` ${unit}` : "";
  if (Math.abs(delta) < 1e-9) return { cls: "", text: unit ? `持平（${unit}）` : "持平" };
  const up = delta > 0;
  const cls = invert ? (up ? "down" : "up") : (up ? "up" : "down");
  return { cls, text: `${up ? "↑ +" : "↓ "}${delta.toFixed(digits)}${suffix}` };
}
```

（现有两处调用 `fmtTrend(curMin - prevMin, "分", 1)` 与 `fmtTrend(data.avg_practice_count - ..., "次", 1)` 不传 `invert`，行为与改动前完全一致。）

- [ ] **Step 3: 加等级映射表**

紧跟在 `fmtTrend` 函数之后插入：

```js
// 畏难指数的等级档位，出自说明文档第五节的四档表。边界值（0.20/0.40/0.60）归入
// **偏高**那一档，所以判定用左闭右开（v < max），与文档的「0 ~ 0.20 / 0.20 ~ 0.40」
// 写法一致而不产生重叠。
const FEAR_LEVELS = [
  { max: 0.20, text: "保持节奏" },
  { max: 0.40, text: "需关注" },
  { max: 0.60, text: "需调整难度" },
  { max: Infinity, text: "需立即干预" },
];
const fearLevel = v => FEAR_LEVELS.find(l => v < l.max).text;
```

- [ ] **Step 4: 改畏难卡片的渲染**

把第 956-962 行这段：

```js
  const fear = data.fear_index;
  const noFear = fear === null || fear === undefined;
  set("metricFear", "metricFearTrend",
      noFear ? "待定义" : Number(fear).toFixed(2),
      noFear ? { cls: "", text: "文档未定义算法" } : null);
```

替换为：

```js
  const fear = data.fear_index;
  if (fear === null || fear === undefined) {
    // 只有在册学生为 0 才会走到这里。显示「暂无数据」而不是 0.00，也不是反过来
    // 把它当成「不畏难」（见本段顶部注释第 3 条）。
    set("metricFear", "metricFearTrend", "—", { cls: "", text: "暂无数据（在册学生为 0）" });
  } else {
    const prev = data.fear_index_last_week;
    // 上周值也缺时不显示趋势，等级照显示——等级只依赖本周值
    const trend = (prev === null || prev === undefined)
      ? null
      : fmtTrend(fear - prev, "", 2, true);
    set("metricFear", "metricFearTrend", Number(fear).toFixed(2), {
      cls: trend ? trend.cls : "",
      text: `${trend ? trend.text + " · " : ""}${fearLevel(fear)}`,
    });
  }
```

- [ ] **Step 5: 静态检查页面没有语法错误**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && awk '/^<script>$/{f=1;next} /^<\/script>$/{f=0;next} f' dashboard.html > /tmp/dash.js && node --check /tmp/dash.js && echo "语法 OK"
```

预期：`语法 OK`。若报 `SyntaxError`，说明 JS 改坏了，先修再往下。

**不要用 `sed -n '/^<script>$/,/^<\/script>$/p'`**：本页有 3 个内联 `<script>` 块（`:533`、`:1090`、`:1156`），sed 的区间会把它们连同中间的 `</script>` 一起抽出来，必然报 `Unexpected token '<'` 的假阳性。awk 的开关写法才会逐块跳过标签本身。

（`node` 不存在时跳过这一步，改到 Step 6 的页面上用浏览器控制台看报错。）

- [ ] **Step 6: 起服务、真实登录、看页面**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python app-d.py
```

另开一个终端：

```bash
curl -s -c /tmp/ck.txt -X POST http://127.0.0.1:8877/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"teacher01","password":"xiyun@2026"}'
curl -s -b /tmp/ck.txt http://127.0.0.1:8877/api/dashboard/process-metrics
```

预期：第二条返回 `{"code":0,"message":"ok","data":{...}}`，`data.fear_index` 是一个 **0~1 之间的小数**（不再是 `null`），`data.fear_index_last_week` 同样存在且是小数。把这两个数与 Task 3 Step 5 打印的值核对一致。

然后用浏览器（**必须走 `/browse` 技能**，不要用 chrome MCP 工具）打开 `http://localhost/index.html`，用 `teacher01 / xiyun@2026` 登录，看「班级过程指标」区第三张卡片：
实测（2026-09-28，`dashboard.html` 的真实 DOM）：
- 畏难卡片：`0.27`，趋势行 `↓ -0.03 · 需关注`，`getComputedStyle` 是 `rgb(74, 143, 107)`（= `--success` 绿），class `metric-trend up`。**下降标绿正是 invert 生效的证据**——若没生效这里会是红色 `rgb(184, 58, 47)`
- 「本周平均练习时长(分)」卡片：`0.0`，趋势 `↓ -0.3 分`（本周 0 条记录，上周人均 18.33 **秒** → 换算成分钟是 0.31 分，所以差值是 -0.3 **分**，不是 -18.3）
- 「平均练习频次(次/周)」卡片：`0.0`，趋势 `↓ -0.9 次`
- 控制台 `$B console --errors` 无任何报错；热力图 canvas、学生能力状态 9 项、作业进度 3 项都正常渲染
- **这两个平均指标与本次改动无关，是改动前就有的现状**

- [ ] **Step 7: 提交**

```bash
git add dashboard.html
git commit -m "feat: 班级看板畏难指数卡片改渲染真值

显示数值 + 较上周趋势 + 四档等级文案；趋势箭头对畏难指数反色（越高越糟，
上升标红）。在册学生为 0 时接口回 null，页面显示「暂无数据」而不是 0.00。"
```

---

## Task 5: 登记文档问题 + 端到端验收

**Files:**
- Modify: `DOC_ISSUES.md`（第 24 条，在「待文档方确认」之后、「另见」之前追加）

**Interfaces:**
- Consumes: Task 1-4 的全部产出
- Produces: 无（终点是文档与验收记录）

- [ ] **Step 1: 在第 24 条追加「已实现」小节**

`DOC_ISSUES.md` 第 24 条里，`**待文档方确认**` 那 4 点的列表之后、`另见第 19、23 条（同属指标口径与数据未标定）。` 这一行**之前**，插入：

```markdown
**2026-09-28 更新：畏难指数已实现**（依据新增的 `../艺校_docs/班级看板--班级畏难倾向指数说明.md`）。该文档补上了算法骨架——5 个分量各自归一化到 0~1、加权求和、范围 0~1、附四档教学建议区间。但**每个分量的判据仍未规定**，以下口径是本次实现定的，逐条写进了代码注释与 `docs/superpowers/specs/2026-09-28-class-fear-index-design.md`：

| 分量 | 文档原文 | 实现口径 | 主要问题 |
|---|---|---|---|
| 练习中断率 | 「练习中断率 = 中断次数 / 总练习次数」 | `duration_sec < 0.5 × segments.duration` 记为中断 | **`practice_records` 里没有中断字段**，「中断」只能拿时长代理，正常快练会被误判；0.5 这个阈值未经真实素材标定 |
| 重试放弃率 | 「同一唱段反复练习但分数未提升，或直接放弃」 | 本周同一（学生,唱段）练 ≥2 次，最后一次 `ai_score` 未超过此前最高分 | 文档没定义「未提升」是相对第一次还是相对最好成绩；`ai_score` 有缺值的组整组弃用 |
| 连续未练习率 | 「学生中断练习后，连续多日不再提交」 | 截至窗口最后一天，最后一次练习距今 ≥ 7 天 | 文档没给「多日」的天数；**没有事件日志表**，只能从 `practice_records.created_at` 反推 |
| 挫败关键词触发率 | 「输入"太难""算了""不会"等关键词的频率」 | 命中词表的 `role='user'` 消息数 / 该窗口 `role='user'` 消息总数 | 词表里除文档举的 3 个词外全是实现时补的；**真库 `role='user'` 消息 0 条，该分量恒为 0**，固定权重下把指数压低最多 0.2 |
| 作业未提交率 | 「已布置作业中，学生未提交或逾期提交的比例」 | 全部作业 × 在册学生数为分母的**累计**口径，不按周切 | 按周切会频繁出现分母 0（当前库 3 份作业截止日全在 2026-07/08），代价是这一项对周趋势无贡献 |

另有两处与文档的结构性出入：**文档第二节列了「练习时长」这个信号，但第三节的公式只有 5 项、不含它**，本次按公式实现；**权重取自文档的「例如各占 20%」**，是示例值而非标定值。某分量分母为 0 时记 0 而**不重新归一化权重**——保住周与周之间可比，代价是长期缺数据的分量会固定压低指数。

**仍未解决**：上文「待文档方确认」的 2、3、4 点（统计周期是否改滚动 7 天、分母是否改为「本周练过的学生」、是否按班级/教师分组）本次**都没有动**，仍按原来的口径。另见 spec 第 7 节的 6 条已知局限。
```

- [ ] **Step 2: 端到端验收**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python scripts/check_db.py
```

**预期：报差异、退出码 1——这是既有漂移，不是本次引入的。** 实测输出：

```
比对范围：15 张表 / 103 列 / 22 个外键 / 2 个自定义索引
结果：有差异 ✗
  - 表集合不一致：真库独有={'demo_versions'} 模型独有=无
  - teacher_demos 列名差异：真库独有={'parse_time_sec', 'parse_status', 'techniques_json'} 模型独有=无
```

`demo_versions` 与 `teacher_demos` 的那 3 列是 Demucs 示范库解析那次加进真库的，没同步回 `schema.sql` 与 `app/models/`。**判断依据**：`git diff --name-only main...HEAD` 里没有 `schema.sql` / `seed.sql` / `app/models/`，而 `check_db.py` 比的是模型与真库——两边模型相同，结果必然相同，所以 `main` 上跑也一样报错。

**这一步的断言是「差异内容与上面逐字一致」，不是「退出码 0」。** 若出现了上面两行之外的差异项，才是动了不该动的模型，回退。本次**不去修**这个既有漂移（超出范围）。

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && git status --short && git log --oneline -6
```

预期：工作区干净；最近 5 条 commit 依次是 Task 4、3、2、1 的提交，再往前是 spec 的 `docs: 畏惧倾向指数实现设计`。

再确认一次页面上**四个**数据区块都正常（用 `/browse` 技能打开 `http://localhost/index.html`）：
1. 过程指标三张卡片（时长 / 频次 / 畏难指数）都有数、趋势箭头方向与颜色正确
2. 热力图有数据（`GET /api/dashboard/heatmap` 未被本次改动影响）
3. 学生列表与告警（`GET /api/dashboard/students` + `/alerts`）未被影响
4. 作业进度（`GET /api/dashboard/homework-progress`）未被影响

任何一块变成「加载失败」，说明本次改动波及了别的接口，回到 Task 3 Step 6 的回归检查定位。

- [ ] **Step 3: 提交**

```bash
git add DOC_ISSUES.md
git commit -m "docs: 登记畏难指数的实现口径与遗留问题

DOC_ISSUES 第 24 条追加：算法骨架来自 2026-09-28 新增的说明文档，但 5 个
分量的判据仍是实现时定的，逐条列出并标出数据缺口（中断字段缺失、对话
role='user' 为空、作业截止日不随周滚动）。"
```

- [ ] **Step 4: 交给用户决定分支去向**

本计划全程在分支 `feat/class-fear-index` 上（基于 `main`）。**不要自行合并或推送**，把分支名与提交列表报给用户，由用户决定是否合回 `main`。

---

## Self-Review

**1. Spec 覆盖：**

| Spec 章节 | 覆盖它的 Task |
|---|---|
| §3 公式与权重 | Task 3 Step 2（常量）、Step 3（计算） |
| §3.1 中断率 | Task 1 Step 1（查询）、Task 3 Step 3（判定） |
| §3.2 重试放弃率 | Task 1 Step 1、Task 3 Step 3 |
| §3.3 连续未练习率 | Task 1 Step 1、Task 3 Step 3 |
| §3.4 关键词触发率 | Task 2 Step 1、Task 3 Step 3 |
| §3.5 作业未提交率 | Task 2 Step 2、Task 3 Step 3（`_homework_skip_rate`） |
| §4 接口契约变更 | Task 3 Step 4 |
| §5 代码改动清单 | Task 1-5 的 Files 段 |
| §6 前端展示 | Task 4 |
| §7 已知局限 | Task 5 Step 1 |
| §8 验证方式 | 各 Task 的验证步骤 + Task 5 Step 2 |

无遗漏。spec 第 5 节表格里列的 7 个文件，Task 1-5 全部覆盖；「不改」清单里的 `app/api/dashboard.py` 全计划无一处触达。

**2. 占位符扫描：** 无 TBD / TODO / 「类似 Task N」/ 「适当处理错误」。所有代码步骤都是可直接粘贴的完整代码，所有验证步骤都有可执行命令与预期输出。

**3. 类型一致性：**
- `get_interrupt_rows` 返回 `list[tuple[float, float]]`，Task 3 里解包为 `for dur, seg_dur in rows` ✅
- `get_retry_rows` 返回 `list[tuple[int, int, float | None, datetime]]`，Task 3 里解包为 `for sid, seg_id, score, at in ...` ✅
- `get_last_practice_dates` 返回 `dict[int, date]`，Task 3 里用 `(as_of - last_days[sid]).days`（两个 `date` 相减得 `timedelta`）✅
- `count_user_messages` 返回 `tuple[int, int]`，Task 3 里解包为 `hit, total_msg` ✅
- `get_submission_stats` 返回 `tuple[int, int, int]`，`_homework_skip_rate` 里解包为 `hw_count, submitted, late` ✅
- `_fear_index(db, student_ids, start, end, as_of, homework_rate)` 六个参数，Task 3 Step 3 的两处调用与 Step 7 的边界验证都是六个实参 ✅
- 前端 `fmtTrend(delta, unit, digits, invert)`：新增第 4 个参数，现有两处三参调用不受影响；畏难处传 `(fear - prev, "", 2, true)` ✅
- 前端字段名 `data.fear_index` / `data.fear_index_last_week` 与 schema 字段名逐字一致 ✅

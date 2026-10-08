# F5 `GET /api/submissions/<id>/detail` 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

日期：2026-10-08
spec：`docs/superpowers/specs/2026-10-08-submission-detail-api-design.md`
接口：《5-接口清单》F5 / 功能 4.4–4.7
DOC_ISSUES：本次新增第 36 条，并更正 §34.3 结尾的错误判断

**Goal:** 实现教师端批改详情接口 `GET /api/submissions/<id>/detail`，交付功能 4.4–4.7，并把挂错地址的旧桩换成正确路由。

**Architecture:** 沿用既有四层——路由（`app/api/homeworks.py`）→ service（`app/services/homework_service.py`）→ 仓储（`app/repositories/homeworks_repo.py`）→ 出参模型（`app/schemas/homework.py`）。一条 join 取完提交＋学生＋姓名＋作业标题，service 里做 JSONB 解析与装配。**本次是纯透传**：库里有什么出什么，功能 4.4（逐字偏差）与 4.5（四维分数）在库里没有数据源，出显式空位（`lyrics: []` / `dimensions: null`），不自造算法。

**Tech Stack:** Flask 3.1.3（蓝图 + 原生 Session）· SQLAlchemy 2.x（ORM 只做映射）· PostgreSQL 15.7（`docker_postgres`）· pydantic v2 · Python 3.11。

## Global Constraints

- **语言**：所有注释、文档、commit message 用简体中文；代码标识符用英文。
- **无测试框架**：`requirements.txt` 里没有 pytest，**不要引入**。验证靠 `/tmp` 临时脚本 + curl/urllib + `docker exec docker_postgres psql`。
- **`/api` 前缀只在 `app/api/__init__.py` 写一次**。业务路由一律写不带前缀的相对路径。
- **`app.register_blueprint(api_bp)` 必须在所有 `@api_bp.route` 之后**——本文件的路由都在模块顶层，天然满足；不要新增在函数内注册路由的写法。
- **`model_dump(mode="json")` 必须加**：出参里有 `datetime`，默认 dump 会给 Flask 一个 datetime 对象并按 RFC-822 序列化成 `"Sat, 01 Aug 2026 00:00:00 GMT"`。
- **`psycopg2-binary` 不得换成 `psycopg2`**；**不引入 `pyproject.toml`**；**不引入 Alembic**；**表结构真源是 `schema.sql`**，本次不改表。
- **姓名必须经 `students.user_id` 拐一次取 `users.display_name`**，不能拿 `submissions.student_id` 当 `users.id` 用（DOC_ISSUES 第 21 条）。
- **脏数据临时改动纪律**（DOC_ISSUES §35.5）：临时改库**只能按抓到的 id 改回**，绝不 `UPDATE/DELETE ... WHERE <别的列>`。
- **Python 解释器**：用 `/Users/meiyazhao/Documents/lianshu/operaAI/.venv/bin/python`（先 `source .venv/bin/activate`）。PATH 上的 `pip`/`python` 是 pyenv 的，不是本项目的 venv。
- **git**：直接提交到 `main`，不开分支、不建 PR。
- **本次不动前端**（`homework.html` 右侧面板仍是 mock），不实现 F6/F7，不补数据源。

---

## 任务 1：`homeworks_repo` 加 `get_submission_detail`

**Files:**
- Modify: `app/repositories/homeworks_repo.py`（文件末尾追加，现共 139 行）

**Interfaces:**
- Consumes: `app.models` 的 `Submission` / `Student` / `User` / `Homework`
- Produces: `get_submission_detail(db: Session, submission_id: int) -> tuple[Submission, str | None, str | None, str | None, str | None] | None`，元组顺序 **`(提交, 姓名, 等级, 头像, 作业标题)`**——前四列**刻意与同文件 `get_pending_submissions` 的 `(提交, 姓名, 等级, 头像)` 一致**，避免同类函数解包顺序不同而互串字段（执行时已按此调整，见文末「执行记录」）

- [ ] **步骤 1.1 确认 import 已够用（应当无需改动）**

第 4 行现在是：

```python
from app.models import Homework, Student, Submission, TeacherDemo, User
```

`Student` 与 `User` 在 F4 落地时已经加进来了，**本任务不需要补 import**。只确认这一行的内容是上面这样；若不同再补齐。

- [ ] **步骤 1.2 文件末尾追加**

```python
def get_submission_detail(
    db: Session, submission_id: int
) -> tuple[Submission, str | None, str | None, str | None, str | None] | None:
    """一条提交的批改详情原始行，(提交, 等级, 头像, 姓名, 作业标题)，不存在返回 None。

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
```

- [ ] **步骤 1.3 单独验一次 repo（不起 Flask）**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && source .venv/bin/activate
python - <<'PY'
from app.db import SessionLocal
from app.repositories import homeworks_repo as r
with SessionLocal() as db:
    for sid in (23, 24, 25, 999):
        row = r.get_submission_detail(db, sid)
        if row is None:
            print(sid, "-> None")
        else:
            sub, name, level, avatar, title = row
            print(sid, "|", name, "|", level, "|", avatar, "|", title,
                  "|", sub.ai_score, "|", sub.status,
                  "| audio_id=", sub.audio_id,
                  "| bkt_before=", sub.bkt_before)
PY
```

**预期输出**（顺序与四个字段都必须逐字对上；`木` 后面是书名号）：

```
23 | 李小燕 | 初学 | 🎭 | 《穆桂英挂帅》· 辕门外三声炮 | 82.5 | ai_scored | audio_id= None | bkt_before= {'拖腔': 0.28, '气息支撑': 0.51, '音准控制': 0.72}
24 | 刘思琪 | 初学 | 🎵 | 《穆桂英挂帅》· 辕门外三声炮 | 75.2 | ai_scored | audio_id= None | bkt_before= {'气息支撑': 0.42, '音准控制': 0.48}
25 | 周明轩 | 初学 | 🎹 | 《穆桂英挂帅》· 辕门外三声炮 | 78.9 | ai_scored | audio_id= None | bkt_before= None
999 -> None
```

**若姓名与头像对调了**（如出现 `初学 | 刘思琪`），说明解包顺序写错，回步骤 1.2 改。

- [ ] **步骤 1.4 提交**

```bash
git add app/repositories/homeworks_repo.py
git commit -m "feat: F5 仓储层加 get_submission_detail（三层 LEFT JOIN 取提交+学生+姓名+作业标题）"
```

---

## 任务 2：`app/schemas/homework.py` 加四个出参模型

**Files:**
- Modify: `app/schemas/homework.py`（文件末尾追加，现共 126 行）

**Interfaces:**
- Consumes: 无
- Produces: `CdmTag` / `BktChange` / `LyricWord` / `SubmissionDetailResponse`，后续任务 3 与任务 4 依赖这四个名字

- [ ] **步骤 2.1 确认 import 已够用（应当无需改动）**

第 1–3 行现在是：

```python
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict
```

`datetime` 已在 F4 落地时加进来（`PendingSubmissionItem.submitted_at` 用到），**本任务不需要补 import**。只确认这一行是 `from datetime import date, datetime`。

- [ ] **步骤 2.2 文件末尾追加四个模型**

```python
class CdmTag(BaseModel):
    """F5 批改详情里的一条 CDM 归因诊断标签（功能 4.6）。

    与 F4 的 `SubmissionTag` **不是同一个模型，也不要合并**：F4 只出 label + severity
    两个字段（卡片上就显示这两样），这里出全字段。两处的字段面会各自演化，共用一个
    模型会逼着它们同步，而它们需要的本来就不是一回事。

    **与 F4 的关键差异一：confidence 不设阈值。** F4 的 tags 只取 > 0.7，那条阈值是
    待批卡片自己的展示口径（F4 spec 3.5）；批改页是教师逐条判断 AI 对不对的地方，
    低置信度的标签恰恰是最该被质疑、因而最该被看见的一条。真库里 23 的 0.45、
    24 的 0.52、26 的 0.65 三条会因此出现在这里而不出现在卡片上，这是**有意的**。

    **与 F4 的关键差异二：confidence 取不到的元素不丢。** F4 是拿它排序筛选的，缺了
    没法定位；这里只是把它带出去，藏起来比带个 `null` 严重。这类元素给 None 排末尾。

    `severity` 是 `defects[].status` 的原文透传（high/medium/low），不是 CSS 类名，
    取不到给 `"unknown"`——同 F4 spec 3.11，不做白名单过滤（滤掉一个未预期的分级会
    让标签凭空消失）。

    `category` / `evidence` / `features` 是 AI 侧写入、F4 刻意不出的字段（F4 spec
    第 1090 行已声明它们是「批改详情页（F5）的内容」）。
    `id` 与 `defects[].id` 同名透传，供将来的逐条确认/驳回定位。
    """

    model_config = ConfigDict(from_attributes=True)
    id: str | None
    label: str
    severity: str
    confidence: float | None
    category: str | None
    evidence: str | None
    features: dict | None


class BktChange(BaseModel):
    """F5 的 BKT 前后对比一条（功能 4.7）。

    由 `submissions.bkt_before` / `bkt_after` 两个扁平字典（技法名 → P(L)）按 key
    并集合并而来，一侧没有的技法给 None。

    `delta` 由**后端**算（教师端只做展示，不该在前端算业务量），且 round 到 4 位：
    `0.48 - 0.46` 在浮点下是 0.020000000000000018，直接出会给前端一个 18 位小数。
    仅 before / after 都是数值时才算，否则 None。
    """

    model_config = ConfigDict(from_attributes=True)
    skill: str
    before: float | None
    after: float | None
    delta: float | None


class LyricWord(BaseModel):
    """F5 的歌词级偏差对比里的一个字（功能 4.4）。

    **当前恒为空数组**：`submissions` 没有逐字列，`ai_detail` 也没有 lyrics/words
    键——库里无数据源（spec 2.5）。契约现在就定死，等 F3 把 B 组结果落进 ai_detail
    时直接读。

    元素对齐 B 组 `words[]` 的**子集**（`app/services/analyze_service.py::_words`），
    字段名用 B 组的 `word` 而不是前端 mock 的 `char`：同一份逐字偏差在 B4 与 F5 两条
    接口上形状必须一致，将来落库时不必再翻译一次。

    **不出展示层的着色档**（excellent/good/fair/punct）：《5-接口清单》3.2 的原文是
    「着色规则在**前端**按 regions.level 渲染」。后端只出 deviation_cents 与 warning
    （B 组已按红黄阈值算好）。

    B 组 words 的另外三个字段 teacher_freq / student_freq / octave_fixed 不出——它们
    服务于音准曲线对比图，不是「歌词级偏差对比」的最小集；将来要加是非破坏性变更。
    """

    model_config = ConfigDict(from_attributes=True)
    index: int
    word: str | None
    start: float | None
    end: float | None
    deviation_cents: float | None
    warning: bool | None


class SubmissionDetailResponse(BaseModel):
    """F5 批改详情（功能 4.4-4.7）。

    学生字段平铺不嵌套，同 F4 spec 3.9（不为一个四字段对象破例）。

    **三处显式空位，都是「库里没有数据源」而不是「本次没做」：**

    - `lyrics` 恒为 `[]`（功能 4.4 逐字偏差无数据源，spec 2.5 / 3.5）
    - `dimensions` 恒为 `None`（功能 4.5 四维分数无数据源，spec 2.5 / 3.6）
    - **不出 `fusion` 键**：前端 mock 的 fusion.total（0.72）按 40/30/20/10 加权它
      自己的 dimensions（84/84/86/80）算出来是 0.84，两数不符，真实语义文档从未
      定义。凭空造一个只会把 mock 的错误固化进契约。总分由 `ai_score` 承担。
      40/30/20/10 这套权重也**不进接口**——没有任何数据能与它相乘。

    功能 4.5 的四块里唯一有数据的是 `feature_matrix` 与 `overall_confidence`，原样
    透传；键名保留 AI 侧的驼峰（pitchStd 等），不做 snake_case 转换——改名会让它和
    写入方对不上，查问题时两边对不上号。

    批改现状那六个字段（status / teacher_score / teacher_comment / voice_comment_text
    / voice_comment_audio_id / reviewed_at）是 F6 写入的列，严格说不属功能 4.4-4.7。
    放进来是因为**没有它们本接口不可用**：status 是判「这份还批不批」的唯一依据；
    一个「批改详情」GET 若不回当前批改结果，F6 提交完还得另调接口才知道自己写了什么；
    `voice_comment_audio_id` 不给的话，功能 4.11 的语音点评音频就取不回来（前端要拿
    它走 B5 `GET /api/audio/<file_id>`）。

    校准现状（`score_calibrations`）**不出**——那是 F7 的读职责，不把 F7 的回显口径
    提前拉进 F5。

    真库里的一个反常照实透传、不替它推断：23/24 的 teacher_score 与 teacher_comment
    已有值，但 status 仍是 `ai_scored`、reviewed_at 仍是 NULL（「写了分数但没走终审」，
    DOC_ISSUES 第 622 行记过全项目还没有代码把 status 写成 reviewed）。
    """

    model_config = ConfigDict(from_attributes=True)
    # 头部
    submission_id: int
    homework_id: int | None
    homework_title: str | None
    student_id: int | None
    student_name: str | None
    student_avatar: str | None
    student_level: str | None
    submitted_at: datetime | None
    audio_id: int | None
    # 4.5 多维加权融合评分
    ai_score: float | None
    overall_confidence: float | None
    feature_matrix: dict | None
    dimensions: dict | None
    # 4.4 歌词级偏差对比
    lyrics: list[LyricWord]
    # 4.6 CDM 归因诊断标签
    cdm_tags: list[CdmTag]
    # 4.7 BKT 状态更新对比
    bkt: list[BktChange]
    # 批改现状
    status: str | None
    teacher_score: float | None
    teacher_comment: str | None
    voice_comment_text: str | None
    voice_comment_audio_id: int | None
    reviewed_at: datetime | None
```

- [ ] **步骤 2.3 验一次模型能构造、`id` 字段名无碍**

`CdmTag` 用了 `id` 作字段名（与 `defects[].id` 同名透传）。pydantic v2 允许这么写，但这一步实测确认一次——**pydantic 若报 `id` 是保留名，就把字段改名 `cdm_id` 并同步改任务 3.2 的装配与 spec §3.4**。

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && source .venv/bin/activate
python - <<'PY'
from app.schemas.homework import CdmTag, BktChange, LyricWord, SubmissionDetailResponse

print(CdmTag(id="d1", label="音准偏差随机", severity="high", confidence=0.85,
             category="音准", evidence="整句…", features={"趋势": "随机波动"}).model_dump())
print(BktChange(skill="音准控制", before=0.48, after=0.46,
                delta=round(0.46 - 0.48, 4)).model_dump())
print(LyricWord(index=0, word="辕", start=0.5, end=1.2,
                deviation_cents=-8.0, warning=False).model_dump())
r = SubmissionDetailResponse(
    submission_id=24, homework_id=12, homework_title="t", student_id=50,
    student_name="刘思琪", student_avatar="🎵", student_level="初学",
    submitted_at=None, audio_id=None, ai_score=75.2, overall_confidence=0.68,
    feature_matrix=None, dimensions=None, lyrics=[], cdm_tags=[], bkt=[],
    status="ai_scored", teacher_score=None, teacher_comment=None,
    voice_comment_text=None, voice_comment_audio_id=None, reviewed_at=None,
)
d = r.model_dump(mode="json")
print("keys:", list(d))
print("float 陷阱检查:", BktChange(skill="x", before=0.48, after=0.46,
                                   delta=round(0.46 - 0.48, 4)).delta)
PY
```

**预期输出**（第一行必须有 `'id': 'd1'`；最后一行必须是 `-0.02`，不是 `-0.020000000000000018`）：

```
{'id': 'd1', 'label': '音准偏差随机', 'severity': 'high', 'confidence': 0.85, 'category': '音准', 'evidence': '整句…', 'features': {'趋势': '随机波动'}}
{'skill': '音准控制', 'before': 0.48, 'after': 0.46, 'delta': -0.02}
{'index': 0, 'word': '辕', 'start': 0.5, 'end': 1.2, 'deviation_cents': -8.0, 'warning': False}
keys: ['submission_id', 'homework_id', 'homework_title', 'student_id', 'student_name', 'student_avatar', 'student_level', 'submitted_at', 'audio_id', 'ai_score', 'overall_confidence', 'feature_matrix', 'dimensions', 'lyrics', 'cdm_tags', 'bkt', 'status', 'teacher_score', 'teacher_comment', 'voice_comment_text', 'voice_comment_audio_id', 'reviewed_at']
float 陷阱检查: -0.02
```

`keys` 那一行共 **22 个键**，且**没有 `fusion`**。

- [ ] **步骤 2.4 提交**

```bash
git add app/schemas/homework.py
git commit -m "feat: F5 出参模型（CdmTag/BktChange/LyricWord/SubmissionDetailResponse）"
```

---

## 任务 3：`homework_service` 加 `submission_detail` 与三个辅助

**Files:**
- Modify: `app/services/homework_service.py`（文件末尾追加，现共 191 行）

**Interfaces:**
- Consumes: 任务 1 的 `homeworks_repo.get_submission_detail`；任务 2 的 `CdmTag` / `BktChange` / `LyricWord` / `SubmissionDetailResponse`；本模块已有的 `_num`（第 104 行）
- Produces: `submission_detail(db: Session, submission_id: int) -> SubmissionDetailResponse`；私有 `_cdm_tags(ai_detail)` / `_bkt_changes(before, after)` / `_feature_matrix(ai_detail)` / `_overall_confidence(ai_detail)`

- [ ] **步骤 3.1 import 补四个模型**

第 9–15 行现在是：

```python
from app.schemas.homework import (
    HomeworkListItem,
    HomeworkListResponse,
    PendingSubmissionItem,
    PendingSubmissionListResponse,
    SubmissionTag,
)
```

改成（四个新名字按字母序插进去，与既有风格一致）：

```python
from app.schemas.homework import (
    BktChange,
    CdmTag,
    HomeworkListItem,
    HomeworkListResponse,
    LyricWord,
    PendingSubmissionItem,
    PendingSubmissionListResponse,
    SubmissionDetailResponse,
    SubmissionTag,
)
```

注意 **`LyricWord` 本次没有实际使用点**（`lyrics` 恒为 `[]`），但 `SubmissionDetailResponse.lyrics` 的类型标注就是它，import 进来是为了让读者知道那个空数组的元素是什么；`ruff`/`flake8` 若报未使用，**不要删**，加 `# noqa: F401` 并留一行说明。

- [ ] **步骤 3.2 文件末尾追加四个函数**

```python
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
    )
```

- [ ] **步骤 3.3 单独验一次 service（不起 Flask）**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && source .venv/bin/activate
python - <<'PY'
from app.db import SessionLocal
from app.common.errors import BusinessError
from app.services import homework_service as svc

with SessionLocal() as db:
    for sid in (23, 24, 25, 26, 27):
        d = svc.submission_detail(db, sid)
        print(sid, "| cdm", len(d.cdm_tags),
              [(c.label, c.severity, c.confidence) for c in d.cdm_tags])
        print("     bkt", [(b.skill, b.before, b.after, b.delta) for b in d.bkt])
        print("     lyrics", d.lyrics, "| dimensions", d.dimensions,
              "| n_feat", len(d.feature_matrix or {}),
              "| conf", d.overall_confidence)
    try:
        svc.submission_detail(db, 999)
    except BusinessError as e:
        print("999 ->", e.code, e.message)
PY
```

**预期输出**（逐条对；`cdm` 的顺序就是列表顺序，`bkt` 按 skill 名升序）：

```
23 | cdm 3 [('气息支撑不足', 'high', 0.82), ('拖腔时值偏短', 'high', 0.78), ('归韵口型保持不足', 'low', 0.45)]
     bkt [('拖腔', 0.28, 0.28, 0.0), ('气息支撑', 0.51, 0.53, 0.02), ('音准控制', 0.72, 0.74, 0.02)]
     lyrics [] | dimensions None | n_feat 9 | conf 0.72
24 | cdm 4 [('音准偏差随机', 'high', 0.85), ('听辨能力弱', 'high', 0.76), ('拖腔不足', 'medium', 0.71), ('气息支撑不足', 'medium', 0.52)]
     bkt [('气息支撑', 0.42, 0.4, -0.02), ('音准控制', 0.48, 0.46, -0.02)]
     lyrics [] | dimensions None | n_feat 9 | conf 0.68
25 | cdm 2 [('节奏感知弱', 'high', 0.8), ('气息不稳定', 'high', 0.74)]
     bkt []
     lyrics [] | dimensions None | n_feat 9 | conf 0.75
26 | cdm 3 [('整体音准偏低', 'high', 0.88), ('调门不准', 'high', 0.82), ('声带紧张', 'medium', 0.65)]
     bkt []
     lyrics [] | dimensions None | n_feat 9 | conf 0.81
27 | cdm 1 [('收尾偏急', 'medium', 0.72)]
     bkt []
     lyrics [] | dimensions None | n_feat 9 | conf 0.55
999 -> 404 提交不存在
```

**四个必须对上的点**：① 条数是 `3/4/2/3/1`——比 F4 的 `2/3/2/2/1` 在 **23/24/26** 三处各多 1（那三条是 0.45 / 0.52 / 0.65，被 0.7 阈值滤掉的）；② 23 的 `拖腔` delta 是 `0.0` 而不是 `None`；③ 25/26/27 的 `bkt` 是 `[]` 而不是 `None`；④ 23 的 bkt 顺序是 `拖腔 → 气息支撑 → 音准控制`。

- [ ] **步骤 3.4 提交**

```bash
git add app/services/homework_service.py
git commit -m "feat: F5 service 装配（CDM 全量不套阈值、BKT 并集合并、4.4/4.5 出空位）"
```

---

## 任务 4：修掉挂错地址的桩并接上

**Files:**
- Modify: `app/api/homeworks.py:39-43`

**Interfaces:**
- Consumes: 任务 3 的 `homework_service.submission_detail(db, submission_id)`
- Produces: 路由 `GET /api/submissions/<int:submission_id>/detail`

- [ ] **步骤 4.1 整条替换错桩**

第 39–43 行现在是：

```python
@api_bp.route("/homeworks/<id>/detail",methods=["GET"])
@login_required
@teacher_required
def homeworks_detail(id):
    return ok(id)
```

换成：

```python
@api_bp.route("/submissions/<int:submission_id>/detail",methods=["GET"])
@login_required
@teacher_required
def submissions_detail(submission_id):
    # mode="json"：出参里有 datetime（submitted_at / reviewed_at）。默认 model_dump()
    # 会给 Flask 一个 datetime 对象，而它按 RFC-822 序列化成
    # "Sat, 01 Aug 2026 00:00:00 GMT"；mode="json" 出的是 ISO-8601。同 F1/F4。
    return ok(homework_service.submission_detail(
        get_db(), submission_id).model_dump(mode="json"))
```

**四处变化，缺一不可**：

1. **路径** `/homeworks/<id>/detail` → `/submissions/<int:submission_id>/detail`。《5-接口清单》F5 是后者；前者文档里根本没有这条路径。**不留别名**——留一个 `/homeworks/<id>/detail` 等于凭空多一条文档里没有的接口。
2. **转换器** `<id>` → `<int:submission_id>`：非数字路径在路由层 404，不进业务代码，是本项目既定约定。
3. **函数名** `homeworks_detail` → `submissions_detail`（旧名与旧地址一样是错的）。
4. **返回体** `ok(id)` → `homework_service.submission_detail(...).model_dump(mode="json")`。

**本文件另外两个桩（`submissions_review` F6、`submissions_calibration` F7）本次不动**，它们还没实现。`post_homeworks` 挂在 `/coach/annotations` 那个错（DOC_ISSUES §34.3）也不属本次范围。

- [ ] **步骤 4.2 语法与路由自检**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && source .venv/bin/activate
python -c "
from app import create_app
app = create_app()
for r in sorted(app.url_map.iter_rules(), key=lambda x: str(x)):
    if 'submission' in str(r) or 'homework' in str(r):
        print(str(r), ','.join(sorted(r.methods - {'HEAD','OPTIONS'})))
"
```

**预期输出**（关键是第 4 行是新地址，且**没有** `/api/homeworks/<id>/detail`）：

```
/api/homeworks POST
/api/homeworks GET
/api/homeworks/<int:homework_id>/submissions GET
/api/submissions/<int:submission_id>/detail GET
/api/submissions/<id>/calibration POST
/api/submissions/<id>/review POST
/api/homeworks/<id>/submit POST
```

（`POST /api/coach/annotations` 不出现在这里是因为过滤条件只保留含 `submission`/`homework` 的规则，这是预期的。）

**若 `/api/homeworks/<id>/detail` 还在**，说明旧桩没删干净，回步骤 4.1。

- [ ] **步骤 4.3 提交**

```bash
git add app/api/homeworks.py
git commit -m "fix: F5 桩地址写错，改到 /api/submissions/<id>/detail 并接上 service"
```

---

## 任务 5：端到端验证

**Files:**
- Create: `/tmp/f5check/check.py`（临时验证脚本，不进仓库）

**Interfaces:**
- Consumes: 任务 4 的路由
- Produces: 无（验证完即弃）

- [ ] **步骤 5.1 起服务（另开一个终端）**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && source .venv/bin/activate
python app-d.py            # 8877
```

页面与接口都要走 HTTP（`file://` 不可用）。本任务的脚本直连 `http://127.0.0.1:8877`，经 nginx 也行，两条路等价。

- [ ] **步骤 5.2 写验证脚本**

用标准库 `urllib`（不引入 `requests`——`requirements.txt` 里没有）。

```bash
mkdir -p /tmp/f5check
```

`/tmp/f5check/check.py`：

```python
# -*- coding: utf-8 -*-
"""F5 端到端验证（spec §5）。标准库实现，不依赖 requests / pytest。"""
import json
import urllib.error
import urllib.request
import http.cookiejar

BASE = "http://127.0.0.1:8877"
ok_cnt = 0
bad = []


def check(name, cond, detail=""):
    global ok_cnt
    if cond:
        ok_cnt += 1
        print("  PASS", name)
    else:
        bad.append(name)
        print("  FAIL", name, detail)


def make_opener():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def call(op, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with op.open(req) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def login(op, user, pwd):
    st, j = call(op, "POST", "/api/auth/login", {"username": user, "password": pwd})
    assert st == 200, (st, j)
    return j


t = make_opener()
login(t, "teacher01", "xiyun@2026")

# 1. submission 24 全字段
st, j = call(t, "GET", "/api/submissions/24/detail")
d = j["data"]
check("24 状态 200", st == 200, st)
check("24 submitted_at 是 ISO-8601",
      d["submitted_at"] == "2026-08-01T00:00:00", d["submitted_at"])
check("24 cdm_tags 4 条", len(d["cdm_tags"]) == 4, len(d["cdm_tags"]))
check("24 cdm 顺序 0.85/0.76/0.71/0.52",
      [c["confidence"] for c in d["cdm_tags"]] == [0.85, 0.76, 0.71, 0.52],
      [c["confidence"] for c in d["cdm_tags"]])
check("24 低置信度那条在（不套 0.7 阈值）",
      any(c["confidence"] == 0.52 for c in d["cdm_tags"]))
check("24 cdm 每条 7 个字段",
      all(set(c) == {"id", "label", "severity", "confidence",
                     "category", "evidence", "features"} for c in d["cdm_tags"]),
      [sorted(c) for c in d["cdm_tags"]])
check("24 bkt 2 条 delta=-0.02",
      [(b["skill"], b["before"], b["after"], b["delta"]) for b in d["bkt"]]
      == [("气息支撑", 0.42, 0.40, -0.02), ("音准控制", 0.48, 0.46, -0.02)],
      d["bkt"])
check("24 lyrics 是 []", d["lyrics"] == [], d["lyrics"])
check("24 dimensions 是 null", d["dimensions"] is None, d["dimensions"])
check("24 无 fusion 键", "fusion" not in d, [k for k in d if "fus" in k])
check("24 feature_matrix 9 键且驼峰",
      isinstance(d["feature_matrix"], dict) and len(d["feature_matrix"]) == 9
      and "pitchStd" in d["feature_matrix"], d["feature_matrix"])
check("24 overall_confidence 0.68", d["overall_confidence"] == 0.68, d["overall_confidence"])
check("24 学生字段", (d["student_name"], d["student_avatar"], d["student_level"])
      == ("刘思琪", "🎵", "初学"), (d["student_name"], d["student_avatar"], d["student_level"]))
check("24 作业标题", d["homework_title"] == "《穆桂英挂帅》· 辕门外三声炮", d["homework_title"])
check("24 teacher_comment 非空", bool(d["teacher_comment"]))
check("24 status/audio_id/reviewed_at",
      (d["status"], d["audio_id"], d["reviewed_at"]) == ("ai_scored", None, None),
      (d["status"], d["audio_id"], d["reviewed_at"]))

# 2. 条数锚点：F5 必须比 F4 在 23/24/26 各多 1
# f4 是 spec §5 第 2 点给出的 F4 实测基线（23→2 / 24→3 / 25→2 / 26→2 / 27→1）
f4 = {24: 3, 26: 2, 27: 1, 23: 2, 25: 2}
f5 = {}
for sid in (23, 24, 25, 26, 27):
    st, j = call(t, "GET", f"/api/submissions/{sid}/detail")
    f5[sid] = len(j["data"]["cdm_tags"])
check("F5 CDM 条数 23→3 / 24→4 / 25→2 / 26→3 / 27→1",
      f5 == {23: 3, 24: 4, 25: 2, 26: 3, 27: 1}, f5)
check("23/24/26 比 F4 各多 1",
      all(f5[s] == f4[s] + 1 for s in (23, 24, 26)), {s: (f4[s], f5[s]) for s in (23, 24, 26)})
check("25/27 与 F4 相同",
      all(f5[s] == f4[s] for s in (25, 27)), {s: (f4[s], f5[s]) for s in (25, 27)})

# 3. 23 的 bkt 3 条，拖腔 delta 是 0.0 不是 None
st, j = call(t, "GET", "/api/submissions/23/detail")
bt = j["data"]["bkt"]
check("23 bkt 3 条按 skill 名升序",
      [b["skill"] for b in bt] == ["拖腔", "气息支撑", "音准控制"], bt)
check("23 拖腔 delta 是 0.0", bt[0]["delta"] == 0.0, bt[0])

# 4. 25/26/27 的 bkt 是 [] 不是 null
for sid in (25, 26, 27):
    st, j = call(t, "GET", f"/api/submissions/{sid}/detail")
    check(f"{sid} bkt 是 []", j["data"]["bkt"] == [], j["data"]["bkt"])

# 5. 404 两种
st, j = call(t, "GET", "/api/submissions/999/detail")
check("999 → 404 提交不存在", (st, j["code"], j["message"]) == (404, 404, "提交不存在"), (st, j))
st, j = call(t, "GET", "/api/submissions/abc/detail")
check("abc → 404 接口不存在", (st, j["code"], j["message"]) == (404, 404, "接口不存在"), (st, j))

# 6. 旧地址必须失效
st, j = call(t, "GET", "/api/homeworks/12/detail")
check("旧地址 /homeworks/12/detail → 404", st == 404 and j["message"] == "接口不存在", (st, j))

# 7. 权限
s = make_opener()
login(s, "stu001", "xiyun@2026")
st, j = call(s, "GET", "/api/submissions/24/detail")
check("学生 → 403", (st, j["code"]) == (403, 403), (st, j))
anon = make_opener()
st, j = call(anon, "GET", "/api/submissions/24/detail")
check("未登录 → 401", (st, j["code"]) == (401, 401), (st, j))

print()
print("PASS", ok_cnt, "FAIL", len(bad), bad)
raise SystemExit(1 if bad else 0)
```

- [ ] **步骤 5.3 跑它**

```bash
cd /tmp/f5check && /Users/meiyazhao/Documents/lianshu/operaAI/.venv/bin/python check.py
```

**预期**：每行都是 `PASS`，末尾 `PASS 27 FAIL 0 []`，退出码 0。（`stu001` 的初始密码同为 `xiyun@2026`。）

- [ ] **步骤 5.4 坏数据兜底（需临时改库）**

**先把 27 那行的三列原值抓到文件**（步骤 5.4.6 要靠它复原，不靠肉眼抄）：

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
mkdir -p /tmp/f5check/orig
for col in ai_detail bkt_before bkt_after; do
  docker exec docker_postgres psql -U xiyun -d xiyun -At -c \
    "SELECT $col::text FROM submissions WHERE id = 27;" > /tmp/f5check/orig/$col.txt
done
wc -c /tmp/f5check/orig/*.txt
```

**预期**：三个文件都在；`ai_detail.txt` 约 400+ 字节，`bkt_before.txt` 与 `bkt_after.txt` 各 0 字节（那两列本来就是 NULL，`-At` 出空行）。

**下面每种情况都只看这一条直查，不用 `check.py`**——`check.py` 里的条数锚点是拿 27 的真实数据写的，改成脏数据后必然 FAIL，那些 FAIL 与本节要验的无关。直查脚本（每次改完库后重跑它）：

```bash
cat > /tmp/f5check/probe.py <<'PY'
# -*- coding: utf-8 -*-
"""直查 27 号提交的四个易碎字段，每次改完库重跑一次。"""
import json, urllib.request, http.cookiejar

BASE = "http://127.0.0.1:8877"
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
req = urllib.request.Request(
    BASE + "/api/auth/login",
    data=json.dumps({"username": "teacher01", "password": "xiyun@2026"}).encode(),
    method="POST")
req.add_header("Content-Type", "application/json")
op.open(req)
with op.open(BASE + "/api/submissions/27/detail") as r:
    body = json.loads(r.read().decode())
d = body["data"]
print("code:", body["code"])
print("cdm_tags:", d["cdm_tags"])
print("feature_matrix:", d["feature_matrix"])
print("overall_confidence:", d["overall_confidence"])
print("bkt:", d["bkt"])
PY
```

下面五种情况都是「改库 → 跑 `python /tmp/f5check/probe.py` → 看预期」。

**情况 A：`ai_detail` 是 dict 但 `defects` 不是 list**

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -c \
  "UPDATE submissions SET ai_detail = '{\"defects\":\"坏数据\"}'::jsonb WHERE id = 27;"
/Users/meiyazhao/Documents/lianshu/operaAI/.venv/bin/python /tmp/f5check/probe.py
```

**预期**：`code: 0`（**不是 500**）、`cdm_tags: []`、`feature_matrix: None`（该键不存在）、`overall_confidence: None`、`bkt: []`。

**情况 A2：`ai_detail` 整个不是 dict**

这一条与情况 A 走的是**不同分支**（`_cdm_tags` 的第一道 `isinstance(ai_detail, dict)` 而非第二道 `isinstance(defects, list)`），必须单独验。

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -c \
  "UPDATE submissions SET ai_detail = '\"坏数据\"'::jsonb WHERE id = 27;"
/Users/meiyazhao/Documents/lianshu/operaAI/.venv/bin/python /tmp/f5check/probe.py
```

**预期**：同情况 A——`code: 0`、`cdm_tags: []`、`feature_matrix: None`、`overall_confidence: None`。

**情况 B：`defects` 里塞坏元素**

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -c \
  "UPDATE submissions SET ai_detail = '{\"defects\":[{\"label\":\"\"},{\"label\":\"X\"}]}'::jsonb WHERE id = 27;"
```

```bash
/Users/meiyazhao/Documents/lianshu/operaAI/.venv/bin/python /tmp/f5check/probe.py
```

**预期**：`cdm_tags` 出 **1 条**——`label` 为空串的那条被丢弃、缺 `confidence` 的 `X` 保留且 `confidence` 为 `None`：

```
cdm_tags: [{'id': None, 'label': 'X', 'severity': 'unknown', 'confidence': None, 'category': None, 'evidence': None, 'features': None}]
```

**情况 C：BKT 一侧坏**

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -c \
  "UPDATE submissions SET bkt_before = '\"坏数据\"'::jsonb, bkt_after = '{\"音准控制\":0.5}'::jsonb WHERE id = 27;"
/Users/meiyazhao/Documents/lianshu/operaAI/.venv/bin/python /tmp/f5check/probe.py
```

**预期**：`bkt: [{'skill': '音准控制', 'before': None, 'after': 0.5, 'delta': None}]`——`before` 与 `delta` 为 `None`、`after` 为 `0.5`。

**情况 D：BKT 两侧都坏**

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -c \
  "UPDATE submissions SET bkt_before = '\"坏数据\"'::jsonb, bkt_after = '\"坏数据\"'::jsonb WHERE id = 27;"
/Users/meiyazhao/Documents/lianshu/operaAI/.venv/bin/python /tmp/f5check/probe.py
```

**预期**：`bkt: []`。

**复原（必做）**：从步骤 5.4 开头抓到的三个文件读回原值，按 **`id = 27`** 逐列写回。**不用手抄 SQL 字面量**——抓下来的那份就是唯一真源：

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && source .venv/bin/activate
python - <<'PY'
from sqlalchemy import text
from app.db import engine

def load(p):
    """psql -At 对 NULL 出空行，返 None；其余原样返回。"""
    s = open(p, encoding="utf-8").read().strip()
    return s or None

vals = {c: load(f"/tmp/f5check/orig/{c}.txt")
        for c in ("ai_detail", "bkt_before", "bkt_after")}
print("将写回:", {k: (v[:40] + "…" if v and len(v) > 40 else v) for k, v in vals.items()})

with engine.begin() as c:
    c.execute(
        text("UPDATE submissions SET ai_detail = CAST(:a AS jsonb), "
             "bkt_before = CAST(:b AS jsonb), bkt_after = CAST(:d AS jsonb) "
             "WHERE id = 27"),
        {"a": vals["ai_detail"], "b": vals["bkt_before"], "d": vals["bkt_after"]},
    )
print("restored id=27")
PY
```

（空串经 `CAST(NULL AS jsonb)` 写回 NULL，与原状一致。）

复原后核对：

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -c \
  "SELECT id, jsonb_array_length(ai_detail->'defects') AS n, bkt_before IS NULL AS bnull, bkt_after IS NULL AS anull FROM submissions WHERE id = 27;"
```

**预期**：`27 | 1 | t | t`（defects 回到 1 条、两个 bkt 列回到 NULL）。再跑一次 `check.py`，应重新回到 `PASS 27 FAIL 0`。

- [ ] **步骤 5.5 库一致性闸门**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && source .venv/bin/activate
python scripts/check_db.py; echo "exit=$?"
```

**预期**：只报**既有漂移**（`demo_versions` 表 + `teacher_demos` 的三列），不新增。本次不动表结构，应与基线一致。既有漂移是 `check_db.py` 在干净 `main` 上就有的，**不要试图在这次修它**。

- [ ] **步骤 5.6 清理临时脚本**

```bash
rm -rf /tmp/f5check
```

（`/tmp` 下的东西本就不进仓库，这一步只是不留垃圾。）

---

## 任务 6：登记 DOC_ISSUES 第 36 条，并更正 §34.3

**Files:**
- Modify: `DOC_ISSUES.md`（在第 1147 行附近、`## 待核实` 之前插入；并改第 1053 行）

**Interfaces:**
- Consumes: 无
- Produces: 无

- [ ] **步骤 6.1 更正 §34.3 结尾的错误断言**

第 1053 行末尾现在是：

```
同一文件里 F3–F7 的另外 5 个桩都挂在 `/homeworks/<id>/...`、`/submissions/<id>/...` 上，地址正确。
```

改成：

```
同一文件里 F3–F7 的另外 5 个桩**并非都正确**：F5 的桩原本挂在 `/homeworks/<id>/detail`，
而《5-接口清单》里 F5 是 `/submissions/<id>/detail`（详见第 36 条）。**「挂在 /homeworks 或
/submissions 前缀下」不等于「地址对」**——本条的原始判断只核了前缀、没逐条核路径。
```

- [ ] **步骤 6.2 在 `## 待核实` 之前插入第 36 条**

````markdown
## 36. 批改详情（F5）的 4.4 与 4.5 在库里没有数据源；桩地址写错

F5 于 2026-10-08 实现（设计 `docs/superpowers/specs/2026-10-08-submission-detail-api-design.md`、计划 `docs/superpowers/plans/2026-10-08-submission-detail-api.md`、代码 `app/api/homeworks.py` / `app/services/homework_service.py` / `app/repositories/homeworks_repo.py` / `app/schemas/homework.py`）。**前端未接入**——`homework.html` 右侧批改面板仍是 mock。

### 36.1 功能 4.4（逐字音分偏差）无数据源

**问题**：《5-接口清单》F5 要求「歌词级偏差对比」，但 `submissions` 表没有逐字列，`ai_detail` 也**没有** `lyrics`/`words` 键——5 行的 `ai_detail` 都只有 `defects` / `featureMatrix` / `overallConfidence` 三个键。

**更麻烦的是列注释与真数据不符**：`schema.sql:127` 对 `ai_detail` 的注释写的是「逐字偏差 + CDM 归因标签」，而真数据里**没有逐字偏差**。注释与数据二者必有一错，目前无从判断是哪一边。

B 组分析确实算得出逐字偏差（`app/services/analyze_service.py::_words`，产出 `{index, word, start, end, deviation_cents, teacher_freq, student_freq, octave_fixed, warning}`），但它**只活在 redis 任务结果里**（TTL 1 小时后消失），且要求 `segments.lyrics_json` 当输入——而解析链路产出的段落该列**恒为 NULL**（第 20 条：没有 ASR 组件，音频给不出汉字）。本次 5 条提交的 `audio_id` **全是 NULL**，等于连分析链路都没挂上。

**当前处理**：F5 的 `lyrics` 出 `[]`（**不编数据**）。元素契约已定死并对齐 B 组 `words[]` 的子集（`{index, word, start, end, deviation_cents, warning}`，字段名用 B 组的 `word` 不用前端 mock 的 `char`），等 F3 把 B 组结果落进 `ai_detail` 时直接读。

**待文档方确认**：逐字数据何时能有源。前提是两件事——(1) 上传时能录入戏词（第 20 条已提，PRD 里本来就是一期做法），(2) B 组分析结果要有地方落库（今天只进 redis）。

**另一件事同样待确认**：本次把 `lyrics` 的元素契约定死为 **B 组 `words[]` 的子集**（`{index, word, start, end, deviation_cents, warning}`，字段名用 B 组的 `word`，不用前端 mock 的 `char`），依据是「同一份逐字偏差在 B4 与 F5 上形状必须一致」。**若文档方希望批改页的逐字数据与 B4 不同形，现在提出**——等 F3 把数据落了库再改就是破坏性变更了。

### 36.2 功能 4.5（多维加权融合评分）无数据源

**问题**：文档要求「40/30/20/10 加权」（《3-功能清单》4.5、《1-PRD》第 204 行），但：

- 库里 `ai_detail.featureMatrix` 是 **9 个原始声学量**（`pitchStd` / `energyStd` / `pitchMean` / `pitchTrend` / `lowPitchBias` / `vibratoDepth` / `highPitchBias` / `rhythmAccuracy` / `durationMeanDiff`），**不是四个维度分**。
- **40/30/20/10 这套权重没有任何映射定义**——文档只给了权重与四个维度的名字（音准/节奏/气息/咬字），没给「每个维度怎么从声学量算出来」。
- **更硬的问题：9 个特征里没有对应「咬字」的量**（5 个属音准、2 个属气息、2 个属节奏）。即使替文档定一套映射，咬字维度也拿不到任何输入。

**当前处理**：F5 出 `ai_score`（库里唯一的总分，融合后的结果）+ `feature_matrix` / `overall_confidence`（原样透传，键名保留 AI 侧的驼峰），`dimensions` 出 **`null`**（显式空位）。**不自造映射**——编一套算法出来的分数会被教师当真，`null` 不会。

**另外不出 `fusion` 键**：前端 mock 的 `fusion.total`（0.72）按 40/30/20/10 加权它自己的 `dimensions`（`{pitch:84, rhythm:84, breath:86, articulation:80}`）算出来是 **0.84**，两个数对不上；文档从未定义融合分的算法。凭空造一个只会把 mock 的错误固化进契约。40/30/20/10 这套权重也不进接口（没有数据能与它相乘）。

**待补充**：四个维度各自的计算口径，尤其是**咬字维度的输入是什么特征**。

**另一件待确认：`feature_matrix` 该不该进对外契约。** 本次选了透传（原样出 `ai_detail.featureMatrix` 的 9 个键，键名保留驼峰）。它是 AI 内部特征包，**固化进对外契约后，AI 侧任何改动都成为破坏性变更**。好处是 9 个声学量足以让后续自行推维度分，不阻塞；代价是这套内部命名从此被外部依赖。**若文档方认为内部特征包不该对外，需现在改为不出**。

### 36.3 `ai_detail` 是手搓种子数据，不是分析产物

5 行的 `ai_detail` 来源是 `/tmp/seed_cdm_report.sql`（第 24 条那批 CDM 假数据），**不是**分析管线写出来的。因此 `defects` 之外的 `featureMatrix` / `overallConfidence` 的语义同样**未经算法验证**——它们的数值看起来合理，但没有任何代码产出过它们，也没法核对。

这不是本接口的问题，但意味着 F5 的 4.6 之外，字段面的「真数据」其实是「看起来像真数据的编造值」。

### 36.4 功能 4.7（BKT 前后对比）数据严重不全

`bkt_before` / `bkt_after` 只有三个技法名（音准控制 / 气息支撑 / 拖腔），且 5 行里 **3 行两侧皆 NULL**（25/26/27）。F5 对这种行出 `bkt: []`。

**待补充**：技法的全集是什么。系统其它地方（知识图谱、能力追踪）的技法维度远多于此，两处对不上时以谁为准，文档没说。

### 36.5 桩地址写错（本次已修）

`app/api/homeworks.py` 的 F5 桩原本是：

```python
@api_bp.route("/homeworks/<id>/detail", methods=["GET"])
```

而《5-接口清单》里 F5 是 `/submissions/<id>/detail`。本次改成正确地址 + `<int:submission_id>` + 接上 service，**未留别名**。

**连带更正第 34.3 条**：该条结尾断言「同一文件里 F3–F7 的另外 5 个桩都挂在 `/homeworks/<id>/...`、`/submissions/<id>/...` 上，地址正确」——**这个判断不成立**，它只核了前缀、没逐条核路径。F5 就是挂在 `/homeworks/<id>/...` 下但路径错的。**F3（`/homeworks/<id>/submit`）与 F6/F7（`/submissions/<id>/review`、`/submissions/<id>/calibration`）在本次已核对地址，是对的。**

### 36.6 F5 自拟口径：批改页的 CDM 列表不套 F4 卡片的 0.7 阈值

**文档从未规定批改页的标签筛选口径。** 本次自拟：F4 的待批卡片只显示 `confidence > 0.7` 的标签（那条阈值是卡片自己的文案，见第 35 条），而 **F5 出全量、不筛**。

理由：卡片是「快速扫一眼批谁」，标签少而准；批改页是「逐条判断 AI 对不对」，**低置信度的标签恰恰是最该被教师质疑、因而最该被看见的那一条**。真库里有三条会因此出现在批改页而不出现在卡片上：23 的 0.45「归韵口型保持不足」、24 的 0.52「气息支撑不足」、26 的 0.65「声带紧张」。把它们藏起来，教师就永远无法通过 F7 校准去纠偏——而那正是 4.10「数据回流」的前提。

**待确认**：批改页是否也该按置信度筛选；若该筛，阈值取多少、以及 4.10 的校准靠什么触发。
````

- [ ] **步骤 6.3 提交**

```bash
git add DOC_ISSUES.md
git commit -m "docs: 登记 F5 落地（DOC_ISSUES 第 36 条）并更正 §34.3 的错误断言"
```

---

## 完成标准

- 任务 5 的 `check.py` 全绿（`PASS 27 FAIL 0`），退出码 0。
- 坏数据五种情况（A / A2 / B / C / D）都按预期出空值而不是 500，且 27 那行已按抓到的文件逐列复原、`check.py` 复跑仍全绿。
- `python scripts/check_db.py` 只报既有漂移。
- `git status` 干净（`/tmp/f5check` 不在仓库内），六个任务的 commit 都在 `main` 上。
- **前端仍未接入**——`homework.html` 右侧面板照旧是 mock，这是本次的既定范围。

---

## 执行记录（2026-10-08）

六个任务全部完成，六个 commit 落在 `main` 上：

| commit | 任务 |
|---|---|
| `60857ef` | 任务 1 仓储 `get_submission_detail` |
| `5a459ad` | 任务 2 出参模型 |
| `8822782` | 任务 3 service 装配 |
| `a58e9eb` | 任务 4 修桩接路由 |
| `5104f3c` | 任务 6 DOC_ISSUES 第 36 条 + §34.3 更正 |

**执行中偏离计划一处**：任务 1 的元组列顺序。计划原写 `(提交, 等级, 头像, 姓名, 标题)`，实做改为 **`(提交, 姓名, 等级, 头像, 标题)`**，前四列对齐同文件 `get_pending_submissions` 的 `(提交, 姓名, 等级, 头像)`（`homeworks_repo.py:184` 的解包就是 `sub, name, level, avatar`）。同一文件里两个同类函数解包顺序不同，一旦抄错就是把头像显示成姓名且不报错——正是计划自己引用的那条警告所指的隐患。计划正文已同步改过。

**验证结果**（超出计划的项标 ⭐）：

- `check.py` **30 PASS / 0 FAIL**（计划写 27 项，实做补了 ⭐「`category`/`evidence`/`features` 非空」——spec §5.1 要求了但计划的脚本漏了）。
- 坏数据五种情况 A / A2 / B / C / D 全部按预期出空值，`code` 恒为 0，无 500；27 号提交已按抓到的文件逐列复原并复跑通过。
- `scripts/check_db.py` 只报既有漂移（`demo_versions` 表 + `teacher_demos` 三列），无新增。
- ⭐ 观察到 **Flask 的 JSON provider 默认 `sort_keys=True`**，所以响应里键是字母序而非模型的声明顺序。这对本次无影响（`check.py` 用集合比对字段面），但**如果将来有接口依赖出参的键序，要另想办法**——现有接口全都受此影响，非本次引入。

**环境备注**：验证时 8877 端口上已有一个旧 Flask 进程在跑，我新起的那个撞端口退出；旧进程的 debug reloader 已自动加载了新代码（新路径回 401、旧路径回 404 可证），因此验证是对当前代码做的。**该旧进程不是我起的，未动它**。

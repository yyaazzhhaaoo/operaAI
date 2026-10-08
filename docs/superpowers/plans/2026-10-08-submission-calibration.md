# F7 评分校准 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现《5-接口清单》F7——教师对一条提交勾选「AI 评分偏差模式」写入 `score_calibrations`，并让 F5 详情回显该校准、`homework.html` 的校准区块从空态变成可勾选可回显。

**Architecture:** 沿用既有四层（route → service → repo → model），F7 与 F6 同住 `app/api/homeworks.py`；写侧按 `(submission_id, teacher_id)` 在应用层 upsert（表上无唯一约束，零 DDL）；读侧给 F5 出参加一个 `calibration` 字段，取最新一条；前端把三个 radio 串在 F6 成功之后提交。

**Tech Stack:** Flask 3.1 + SQLAlchemy 2.x + pydantic v2 + PostgreSQL（Docker `docker_postgres`）；前端是单文件静态 `homework.html`（原生 JS，无构建）。

## Global Constraints

- **零 DDL**：不改 `schema.sql`、不改 `app/models/`、不动 `scripts/check_db.py` 的基线。
- **不引入 pytest**，不加测试目录；验证一律用 `/tmp/f7fe/` 下的临时脚本 + curl + psql。
- **临时脚本与产物一律放 `/tmp/f7fe/`**，不进仓库。
- **临时 DB 改动只能按抓到的 id 改回**；绝不 `DELETE FROM <表> WHERE <别的列>`、绝不整表清空。
- **service 层不碰 `flask.session`**（`app/api/auth.py` 的模块文档把这条列为不变量）；当前用户由路由用 `app.common.decorators.current_user_id()` 取出后作参数传入。
- `/api` 前缀**只**写在 `app/api/__init__.py` 的 `url_prefix` 里，路由一律写相对路径。
- 出参统一信封 `{"code","message","data"}`（`app/response.py` 的 `ok()`）；`code` 与 HTTP 状态码一致（`DOC_ISSUES` 第 9 条）。
- 代码注释、提交信息、文档一律中文；标识符英文。
- **每个任务结束都要 `git add` 明确列出的文件并 commit**，不攒到最后。
- 提交直接落在 `main`，**不开分支、不建 PR**。
- 起后端用 `.venv/bin/python`；验证脚本用 `PYTHONPATH=. .venv/bin/python <脚本>`（脚本在 `/tmp`，`import app` 要靠 `PYTHONPATH`）。

**真库基线（2026-10-08 实测，各任务的期望值以此为准）**

```
users:                teacher01 = id 2 (王老师)    stu001 = id 3    李小燕 = id 50
submissions:          id 23 (hw12, stu 48, ai 82.5,  teacher 82.5,  reviewed)
                      id 24 (hw12, stu 50, ai 75.2,  teacher 75.2,  ai_scored)  ← 种子校准行指向它
                      id 25 (hw12, stu 53, ai 78.9,  teacher NULL,  ai_scored)  ← 本计划的主测试对象
                      id 26 (hw12, stu 55, ai 71.3,  teacher NULL,  ai_scored)
                      id 27 (hw12, stu 52, ai 85.7,  teacher 85.7,  reviewed)
score_calibrations:   全表 1 行 ——
                      id=4, submission_id=24, teacher_id=2, bias_mode='high',
                      ai_score=75.2, teacher_score=75.2,
                      created_at=2026-09-22 17:38:28.746872
```

`score_calibrations` 的索引只有主键 `score_calibrations_pkey`，**没有任何唯一约束**。

---

### Task 1: repo 层三个函数

**Files:**
- Modify: `app/repositories/homeworks_repo.py`（import 行 + 文件末尾追加三个函数）
- Test: `/tmp/f7fe/check_repo.py`（临时，不进仓库）

**Interfaces:**
- Consumes: `app.models.ScoreCalibration`（已存在，`app/models/calibration.py`，已注册进 `app/models/__init__.py`）
- Produces:
  - `get_calibration(db: Session, submission_id: int, teacher_id: int) -> ScoreCalibration | None`
  - `get_latest_calibration(db: Session, submission_id: int) -> ScoreCalibration | None`
  - `add_calibration(db: Session, row: ScoreCalibration) -> None`
  - 三者都在 `app.repositories.homeworks_repo` 下，Task 3 的 service 直接调用。

- [ ] **Step 1: 先写验证脚本，跑一遍确认它现在必然失败**

创建 `/tmp/f7fe/check_repo.py`：

```python
"""Task 1 验证：repo 层三个函数能读到真库那条种子校准行。只读，不改库。"""
from app.db import session_scope
from app.repositories import homeworks_repo

with session_scope() as s:
    got = homeworks_repo.get_calibration(s, 24, 2)
    print("get_calibration(24, 2) ->", None if got is None else
          (got.id, got.bias_mode, got.ai_score, got.teacher_score))
    print("get_calibration(25, 2) ->", homeworks_repo.get_calibration(s, 25, 2))

    latest = homeworks_repo.get_latest_calibration(s, 24)
    print("get_latest_calibration(24) ->", None if latest is None else latest.id)
    print("get_latest_calibration(25) ->", homeworks_repo.get_latest_calibration(s, 25))
```

- [ ] **Step 2: 跑它，确认失败**

Run（在项目根目录）：

```bash
PYTHONPATH=. .venv/bin/python /tmp/f7fe/check_repo.py
```

Expected: `AttributeError: module 'app.repositories.homeworks_repo' has no attribute 'get_calibration'`

- [ ] **Step 3: 改 import 行**

`app/repositories/homeworks_repo.py:3` 现在是：

```python
from app.models import Homework, Student, Submission, TeacherDemo, User
```

改成（加 `ScoreCalibration`，按字母序插在 `Homework` 之后）：

```python
from app.models import Homework, ScoreCalibration, Student, Submission, TeacherDemo, User
```

- [ ] **Step 4: 在文件末尾追加三个函数**

追加到 `app/repositories/homeworks_repo.py` 末尾（`apply_review` 之后）：

```python
def get_calibration(
    db: Session, submission_id: int, teacher_id: int
) -> ScoreCalibration | None:
    """取某教师对某提交的校准行，没有返回 None。供 F7 判「更新还是插入」（spec 3.3）。"""
    return db.scalar(
        select(ScoreCalibration).where(
            ScoreCalibration.submission_id == submission_id,
            ScoreCalibration.teacher_id == teacher_id,
        )
    )


def get_latest_calibration(
    db: Session, submission_id: int
) -> ScoreCalibration | None:
    """取某提交最新的一条校准行，没有返回 None。供 F5 出参（spec 3.6）。

    为什么是「最新一条」而不是「唯一一条」：本表在 (submission_id, teacher_id) 上
    **没有唯一约束**（spec 2.4），历史数据与并发下都可能有多行。id 做第二排序键是为了
    created_at 相同时（同一秒内的两次写）结果稳定。
    """
    return db.scalar(
        select(ScoreCalibration)
        .where(ScoreCalibration.submission_id == submission_id)
        .order_by(ScoreCalibration.created_at.desc(), ScoreCalibration.id.desc())
        .limit(1)
    )


def add_calibration(db: Session, row: ScoreCalibration) -> None:
    """插入一行校准记录。

    不 flush：本次没有自增 id 要拿（`annotations_repo.add` 要 flush 是为了拿 id），
    脏对象由 service 的 commit 一并写回。与 `apply_review` 同一口径。
    """
    db.add(row)
```

- [ ] **Step 5: 再跑验证脚本，确认通过**

Run：`PYTHONPATH=. .venv/bin/python /tmp/f7fe/check_repo.py`

Expected（脚本**不改库**，跑几遍结果都一样）：

```
get_calibration(24, 2) -> (4, 'high', 75.2, 75.2)
get_calibration(25, 2) -> None
get_latest_calibration(24) -> 4
get_latest_calibration(25) -> None
```

- [ ] **Step 6: 提交**

```bash
git add app/repositories/homeworks_repo.py
git commit -m "feat: homeworks_repo 加校准行的查/插三个函数"
```

---

### Task 2: schema 层（两个新模型 + F5 出参加字段）

**Files:**
- Modify: `app/schemas/homework.py`（import 行、`:209` 之前插入两个类、`SubmissionDetailResponse` 的文档字符串与字段）
- Test: `/tmp/f7fe/check_schema.py`（临时）

**Interfaces:**
- Consumes: 无（纯定义）
- Produces:
  - `SubmissionCalibration(bias_mode: str, ai_score: float | None, teacher_score: float | None, created_at: datetime)`，`model_config = ConfigDict(from_attributes=True)`，因此 `SubmissionCalibration.model_validate(<ORM 行>)` 可用。F7 的出参与 F5 的 `calibration` 字段**共用这一个类**。
  - `SubmissionCalibrationIn(bias_mode: Literal["high","low","ok"] | None)`——**无默认值**，字段缺失报 422。
  - `SubmissionDetailResponse.calibration: SubmissionCalibration | None`

- [ ] **Step 1: 先写验证脚本**

创建 `/tmp/f7fe/check_schema.py`：

```python
"""Task 2 验证：入参模型的三条边界（合法值 / 显式 null / 缺失 / 非法值）。不碰数据库。"""
from pydantic import ValidationError

from app.schemas.homework import SubmissionCalibrationIn

print("high ->", SubmissionCalibrationIn.model_validate({"bias_mode": "high"}).bias_mode)
print("null ->", SubmissionCalibrationIn.model_validate({"bias_mode": None}).bias_mode)

for bad in ({}, {"bias_mode": "x"}):
    try:
        SubmissionCalibrationIn.model_validate(bad)
        print("不该通过:", bad)
    except ValidationError as e:
        print(f"{bad} -> {e.errors()[0]['type']} @ {e.errors()[0]['loc']}")
```

- [ ] **Step 2: 跑它，确认失败**

Run：`PYTHONPATH=. .venv/bin/python /tmp/f7fe/check_schema.py`

Expected: `ImportError: cannot import name 'SubmissionCalibrationIn' from 'app.schemas.homework'`

- [ ] **Step 3: 补 `Literal` 的 import**

`app/schemas/homework.py:1` 现在是：

```python
from datetime import date, datetime
```

改成：

```python
from datetime import date, datetime
from typing import Literal
```

- [ ] **Step 4: 在 `SubmissionDetailResponse` 之前插入两个类**

插入位置：`app/schemas/homework.py` 第 209 行 `class SubmissionDetailResponse(BaseModel):` **之前**（必须在前——`SubmissionDetailResponse` 的字段注解引用了 `SubmissionCalibration`）。

```python
class SubmissionCalibration(BaseModel):
    """一条 AI 评分校准记录（功能 4.10）。

    **F7 的响应体与 F5 详情里的 `calibration` 字段共用本类**——两处必须是同一个形状，
    否则页面「刚写完」与「重新打开」会渲染出两种结果。

    from_attributes=True：F7 与 F5 都从 ORM 行直接 `model_validate(row)` 构造，
    不手抄四个字段（抄漏一个不会有任何报错，只会安静地少一个键）。
    """

    model_config = ConfigDict(from_attributes=True)

    bias_mode: str
    ai_score: float | None
    teacher_score: float | None
    created_at: datetime


class SubmissionCalibrationIn(BaseModel):
    """F7 入参（`POST /api/submissions/<id>/calibration`，功能 4.10）。

    只有一项——`ai_score` / `teacher_score` / `teacher_id` 全由服务端取（spec 3.2），
    客户端传不了。

    `bias_mode` **没有默认值**，这是有意的：缺省要报「必填」（422），只有显式传
    `null` 才表示「撤销该校准」（spec 3.4）。写成 `= None` 会让缺省也变成合法，
    两种情形就分不开了。

    取值集合是封闭的三值，用 `Literal` 表达。代价：非法值抛 `literal_error`，
    不在 `app/common/errors.py` 的 `_MSG_CN` 里，message 回退英文原文（spec 3.8）。
    """

    bias_mode: Literal["high", "low", "ok"] | None
```

- [ ] **Step 5: 改 `SubmissionDetailResponse` 的文档字符串**

删除 `app/schemas/homework.py` 现在这两行（原 `:234-235`）：

```
    校准现状（`score_calibrations`）**不出**——那是 F7 的读职责，不把 F7 的回显口径
    提前拉进 F5。
```

替换成：

```
    `calibration` 是**第七个**批改现状字段，但它来自另一张表（`score_calibrations`，
    功能 4.10 / F7）——前六个是 F6 写在 `submissions` 上的列。原来这里写的是「不出校准，
    那是 F7 的读职责」，2026-10-08 推翻：F7 在《5-接口清单》里只有 POST，读职责没有落点，
    不出的话教师打开一条已批改的提交看不到自己勾过什么。取值口径见 F7 spec §3.6
    （同一提交多行时取最新一条）。
```

- [ ] **Step 6: 给 `SubmissionDetailResponse` 加字段**

在 `reviewed_at: datetime | None`（原 `:271`）**之后**加一行：

```python
    # 4.10 AI 评分校准（F7 写入，读侧归本接口）
    calibration: SubmissionCalibration | None
```

- [ ] **Step 7: 再跑验证脚本，确认通过**

Run：`PYTHONPATH=. .venv/bin/python /tmp/f7fe/check_schema.py`

Expected：

```
high -> high
null -> None
{} -> missing @ ('bias_mode',)
{'bias_mode': 'x'} -> literal_error @ ('bias_mode',)
```

- [ ] **Step 8: 确认没把 F5 打坏**

Run：`PYTHONPATH=. .venv/bin/python -c "
from app.schemas.homework import SubmissionDetailResponse
print(SubmissionDetailResponse.model_fields['calibration'].annotation)"`

Expected：`SubmissionCalibration | None`（若模型 import 链断在这里会直接抛异常）

- [ ] **Step 9: 提交**

```bash
git add app/schemas/homework.py
git commit -m "feat: 新增校准入参/出参模型，F5 详情加 calibration 字段"
```

---

### Task 3: service 层（写侧 + F5 装配）

**Files:**
- Modify: `app/services/homework_service.py`（import 两处、新增 `_calibration_of` 与 `calibrate_submission`、`submission_detail` 加一行装配）
- Test: `/tmp/f7fe/check_service.py`（临时，**会写库**）

**Interfaces:**
- Consumes：Task 1 的三个 repo 函数、Task 2 的两个模型。
- Produces:
  - `calibrate_submission(db: Session, submission_id: int, data: SubmissionCalibrationIn, teacher_id: int) -> SubmissionCalibration | None`
    —— 提交不存在抛 `BusinessError(404, "提交不存在")`；`bias_mode is None` 时删除该行并返回 `None`；否则 upsert 并返回新值。
  - `_calibration_of(db: Session, sub: Submission) -> SubmissionCalibration | None`（私有）
  - `submission_detail` 的返回里多一个 `calibration`（签名不变）。

- [ ] **Step 1: 先写验证脚本**

创建 `/tmp/f7fe/check_service.py`：

```python
"""Task 3 验证：upsert / 撤销 / 404 / F5 带出校准。

**会写真库**，全部落在 submission 25（基线里它没有校准行），脚本最后会把造出来的行
按抓到的 id 删掉。基线快照见 /tmp/f7fe/baseline.txt。
"""
from sqlalchemy import func, select

from app.common.errors import BusinessError
from app.db import session_scope
from app.models import ScoreCalibration
from app.repositories import homeworks_repo
from app.schemas.homework import SubmissionCalibrationIn
from app.services import homework_service

IN = lambda v: SubmissionCalibrationIn.model_validate({"bias_mode": v})
created_ids = []


def count(s):
    return s.scalar(select(func.count()).select_from(ScoreCalibration))


with session_scope() as s:
    print("F5(25) 起始校准 ->", homework_service.submission_detail(s, 25).calibration)
    print("F5(24) 种子校准 ->", homework_service.submission_detail(s, 24).calibration)

    base = count(s)
    out = homework_service.calibrate_submission(s, 25, IN("high"), teacher_id=2)
    row = homeworks_repo.get_calibration(s, 25, 2)
    created_ids.append(row.id)
    print("写 high ->", out.bias_mode, out.ai_score, out.teacher_score, "| row id", row.id)
    print("  行数", base, "->", count(s))
    first_created = row.created_at

    # 重发同一个值：必须命中同一行，行数不变
    homework_service.calibrate_submission(s, 25, IN("high"), teacher_id=2)
    print("重发 high 后行数 ->", count(s), "| 同一行 id", homeworks_repo.get_calibration(s, 25, 2).id)

    # 改值：仍是同一行，created_at 刷新
    homework_service.calibrate_submission(s, 25, IN("low"), teacher_id=2)
    row2 = homeworks_repo.get_calibration(s, 25, 2)
    print("改 low -> 同一行 id", row2.id, "| created_at 已刷新",
          row2.created_at != first_created)
    print("F5(25) 带出校准 ->", homework_service.submission_detail(s, 25).calibration)

    # 撤销：行消失，F5 回到 None
    print("撤销 ->", homework_service.calibrate_submission(s, 25, IN(None), teacher_id=2))
    print("撤销后行数 ->", count(s))
    print("F5(25) 撤销后 ->", homework_service.submission_detail(s, 25).calibration)

    # 404
    try:
        homework_service.calibrate_submission(s, 99999, IN("high"), teacher_id=2)
        print("不该通过: 404 用例")
    except BusinessError as e:
        print("不存在 ->", e.code, e.message)

# 兜底清理：只删本脚本自己造出来的那些 id
if created_ids:
    with session_scope() as s:
        for i in created_ids:
            r = s.get(ScoreCalibration, i)
            if r is not None:
                s.delete(r)
                print("清理残留行 id", i)
    print("最终行数 ->", end=" ")
    with session_scope() as s:
        print(count(s))
```

- [ ] **Step 2: 先抓基线快照（改库前必做）**

```bash
mkdir -p /tmp/f7fe
docker exec docker_postgres psql -U xiyun -d xiyun -At -P null='<NULL>' \
  -c "select id,submission_id,teacher_id,bias_mode,ai_score,teacher_score,created_at from score_calibrations order by id;" \
  > /tmp/f7fe/baseline.txt
cat /tmp/f7fe/baseline.txt
```

Expected：一行，`4|24|2|high|75.2|75.2|2026-09-22 17:38:28.746872`

- [ ] **Step 3: 跑验证脚本，确认失败**

Run：`PYTHONPATH=. .venv/bin/python /tmp/f7fe/check_service.py`

Expected: `AttributeError: module 'app.services.homework_service' has no attribute 'calibrate_submission'`（或 `submission_detail` 返回没有 `calibration` 属性）

- [ ] **Step 4: 补 import**

`app/services/homework_service.py:7`：

```python
from app.models import Homework
```

改成：

```python
from app.models import Homework, ScoreCalibration, Submission
```

同文件 `:10` 起的 `from app.schemas.homework import (...)` 元组里，按字母序插入两个名字——加完是：

```python
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
```

- [ ] **Step 5: 加 `_calibration_of`，插在 `submission_detail` 之前**

位置：`app/services/homework_service.py` 里 `def submission_detail(` 的**上一行**之前。

```python
def _calibration_of(db: Session, sub: Submission) -> SubmissionCalibration | None:
    """F5 出参里的校准块（功能 4.10，F7 写入）。

    没校准过返回 None（**不是空对象**）：页面靠 `null` 判「三个 radio 都不选」。
    取最新一条的理由见 spec 3.6——本表没有唯一约束，多行是可能的。
    """
    row = homeworks_repo.get_latest_calibration(db, sub.id)
    return None if row is None else SubmissionCalibration.model_validate(row)
```

- [ ] **Step 6: 把 `calibration` 接进 `submission_detail` 的返回**

在该函数 `return SubmissionDetailResponse(` 里，`reviewed_at=sub.reviewed_at,` 那行**之后**加：

```python
        calibration=_calibration_of(db, sub),
```

（`sub` 已经在该函数解包出来的元组里，`db` 是函数参数，两个都现成。）

- [ ] **Step 7: 在文件末尾加 `calibrate_submission`**

位置：`app/services/homework_service.py` 末尾，`review_submission` 之后。

```python
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
```

- [ ] **Step 8: 再跑验证脚本，确认通过**

Run：`PYTHONPATH=. .venv/bin/python /tmp/f7fe/check_service.py`

Expected（关键几行）：

```
F5(25) 起始校准 -> None
F5(24) 种子校准 -> bias_mode='high' ai_score=75.2 teacher_score=75.2 created_at=...
写 high -> high 78.9 None | row id 5
  行数 1 -> 2
重发 high 后行数 -> 2 | 同一行 id 5
改 low -> 同一行 id 5 | created_at 已刷新 True
F5(25) 带出校准 -> bias_mode='low' ...
撤销 -> None
撤销后行数 -> 1
F5(25) 撤销后 -> None
不存在 -> 404 提交不存在
```

（`row id` 具体是 5 还是别的数取决于序列当前值，只要「写之前 1 行、写之后 2 行、重发仍是 2 行」即可。）

- [ ] **Step 9: 核对真库已复原**

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -At -P null='<NULL>' \
  -c "select id,submission_id,teacher_id,bias_mode,ai_score,teacher_score,created_at from score_calibrations order by id;" \
  | diff /tmp/f7fe/baseline.txt -
```

Expected：**无输出**（与基线逐字符一致）。有差异就停下来查，不要往下走。

- [ ] **Step 10: 提交**

```bash
git add app/services/homework_service.py
git commit -m "feat: F7 service 校准 upsert/撤销，F5 详情装配 calibration"
```

---

### Task 4: 路由（替换 F7 的桩）

**Files:**
- Modify: `app/api/homeworks.py`（import 行 + `:78-82` 的桩）
- Test: `/tmp/f7fe/curl.sh`（临时）

**Interfaces:**
- Consumes：Task 3 的 `homework_service.calibrate_submission`、Task 2 的 `SubmissionCalibrationIn`、`app.common.decorators.current_user_id`
- Produces：`POST /api/submissions/<int:submission_id>/calibration` 可用，成功回 `{"code":0,"message":"ok","data":{...}}`，撤销回 `data: null`。

- [ ] **Step 1: 补 import**

`app/api/homeworks.py:4` 现在是：

```python
from app.common.decorators import login_required, teacher_required, student_required
```

改成（加 `current_user_id`）：

```python
from app.common.decorators import (
    current_user_id,
    login_required,
    student_required,
    teacher_required,
)
```

同文件 `:7` 现在是：

```python
from app.schemas.homework import SubmissionReviewIn
```

改成：

```python
from app.schemas.homework import SubmissionCalibrationIn, SubmissionReviewIn
```

- [ ] **Step 2: 替换桩体**

`app/api/homeworks.py:78-82` 现在是：

```python
@api_bp.route("/submissions/<id>/calibration",methods=["POST"])
@login_required
@teacher_required
def submissions_calibration(id):
    return ok(id)
```

整段替换成：

```python
@api_bp.route("/submissions/<int:submission_id>/calibration",methods=["POST"])
@login_required
@teacher_required
def submissions_calibration(submission_id):
    # 路径参数从原来的 <id> 改成 <int:submission_id>：<id> 是字符串转换器，
    # /submissions/abc/calibration 也会匹配进来再进视图去查库；<int:...> 让 Werkzeug
    # 在路由层就挡掉（IntegerConverter 的正则是 \d+），走 errors.py 的统一 404。同 F1/F4/F5/F6。
    #
    # teacher_id 在路由层从 session 取，service 不碰 flask.session（见 service 的注释）。
    data = SubmissionCalibrationIn.model_validate(_payload())
    out = homework_service.calibrate_submission(
        get_db(), submission_id, data, teacher_id=current_user_id())
    # 撤销（bias_mode = null）时 out 是 None，None.model_dump() 会炸，所以判空。
    return ok(out.model_dump(mode="json") if out else None)
```

- [ ] **Step 3: 起后端**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
source .venv/bin/activate
python app-d.py            # 8877；F7 不需要 celery worker
```

（另开一个终端跑下面的 curl；本步骤的进程留在前台。）

- [ ] **Step 4: 写并跑 curl 脚本**

创建 `/tmp/f7fe/curl.sh`：

```bash
#!/usr/bin/env bash
# Task 4 验证：F7 的状态码与 upsert 行为。会写真库（只碰 submission 25）。
B=http://127.0.0.1:8877
D=/tmp/f7fe
T=$D/teacher.jar
S=$D/student.jar

login() {  # $1=用户名 $2=jar
  curl -s -c "$2" -X POST "$B/api/auth/login" -H 'Content-Type: application/json' \
    -d "{\"username\":\"$1\",\"password\":\"xiyun@2026\"}" -o /dev/null
}
post() {   # $1=body  $2=jar  $3=submission_id
  curl -s -b "$2" -w '\nHTTP %{http_code}\n' -X POST "$B/api/submissions/$3/calibration" \
    -H 'Content-Type: application/json' -d "$1"
}
rows() { docker exec docker_postgres psql -U xiyun -d xiyun -At \
  -c "select count(*) from score_calibrations;"; }

login teacher01 "$T"; login stu001 "$S"
echo "--- 1 首次写 25 high（ai_score=78.9, teacher_score=null）"; post '{"bias_mode":"high"}' "$T" 25; echo "行数 $(rows)"
echo "--- 2 重发同一个值（应命中同一行，行数不变）";        post '{"bias_mode":"high"}' "$T" 25; echo "行数 $(rows)"
echo "--- 3 改值 low";                                      post '{"bias_mode":"low"}'  "$T" 25
echo "--- 4 撤销（data 应为 null，行数回落）";               post '{"bias_mode":null}'   "$T" 25; echo "行数 $(rows)"
echo "--- 5 写种子提交 24（应更新 id=4 那行，行数不变）";     post '{"bias_mode":"ok"}'   "$T" 24; echo "行数 $(rows)"
echo "--- 6 学生调（403）";                                  post '{"bias_mode":"high"}' "$S" 25
echo "--- 7 未登录（401）";                                  post '{"bias_mode":"high"}' "" 25
echo "--- 8 提交不存在（404）";                              post '{"bias_mode":"high"}' "$T" 99999
echo "--- 9 非法值（422，英文 message）";                    post '{"bias_mode":"x"}'    "$T" 25
echo "--- 10 空 body（422 必填）";                           post '{}'                   "$T" 25
echo "--- 11 路径非整数（404 接口不存在）"; \
  curl -s -b "$T" -w '\nHTTP %{http_code}\n' -X POST "$B/api/submissions/abc/calibration" \
    -H 'Content-Type: application/json' -d '{"bias_mode":"high"}'
echo "--- 12 F5 详情 24 带出校准"; \
  curl -s -b "$T" "$B/api/submissions/24/detail" | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["calibration"])'
```

- [ ] **Step 5: 逐条核对输出**

Expected：

| # | 期望 |
|---|---|
| 1 | `"bias_mode":"high"`、`"ai_score":78.9`、`"teacher_score":null`，`HTTP 200`；行数 `1 -> 2` |
| 2 | `HTTP 200`；行数仍是 `2` |
| 3 | `"bias_mode":"low"`，`created_at` 与第 1 步不同 |
| 4 | `"data":null`，`HTTP 200`；行数回 `1` |
| 5 | `HTTP 200`；行数仍 `1`（更新了 id=4 那行，不是新增） |
| 6 | `HTTP 403`，`{"code":403,"message":"无权限"}` |
| 7 | `HTTP 401`，`{"code":401,"message":"未登录"}` |
| 8 | `HTTP 404`，`{"code":404,"message":"提交不存在"}` |
| 9 | `HTTP 422`，message 含 `literal_error` 的英文原文 |
| 10 | `HTTP 422`，message 为 `bias_mode: 必填` |
| 11 | `HTTP 404`，`{"code":404,"message":"接口不存在"}` |
| 12 | 一个 dict，`bias_mode` 为 `ok`（第 5 步写的），`teacher_score` 为 75.2 |

- [ ] **Step 6: 复原种子行（本任务碰了 id=4）**

第 5 步把种子行改成了 `ok`，按**抓到的 id** 改回原值：

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -c \
  "UPDATE score_calibrations SET bias_mode='high', ai_score=75.2, teacher_score=75.2, \
   created_at='2026-09-22 17:38:28.746872' WHERE id = 4;"
docker exec docker_postgres psql -U xiyun -d xiyun -At -P null='<NULL>' \
  -c "select id,submission_id,teacher_id,bias_mode,ai_score,teacher_score,created_at from score_calibrations order by id;" \
  | diff /tmp/f7fe/baseline.txt -
```

Expected：`UPDATE 1`，diff **无输出**。

- [ ] **Step 7: 停掉后端进程，提交**

```bash
git add app/api/homeworks.py
git commit -m "feat: F7 路由接上真实现，路径参数改用 <int:submission_id>"
```

---

### Task 5: 前端 `homework.html` 校准区块

**Files:**
- Modify: `homework.html`（CSS `:397`、区块文案 `:576`、`renderDetailCalib` `:997-1000`、`submitReview` `:1168`）
- Test: 浏览器实走（用 `/browse` 技能）

**Interfaces:**
- Consumes：F5 出参的 `data.calibration`（`{bias_mode, ai_score, teacher_score, created_at} | null`）、F7 的 `POST /api/submissions/<id>/calibration`（body `{"bias_mode": "high"|"low"|"ok"}`，回 `data` 为对象或 null）
- Produces：页面能把教师的勾选写成校准记录，并在重新打开该提交时回显。

- [ ] **Step 1: 改 CSS：让 radio 复用 checkbox 的样式**

`homework.html:397` 现在是：

```css
.calib-item input[type="checkbox"]{width:16px;height:16px;accent-color:var(--primary)}
```

改成：

```css
.calib-item input[type="checkbox"],
.calib-item input[type="radio"]{width:16px;height:16px;accent-color:var(--primary)}
```

- [ ] **Step 2: 改区块提示文案**

`homework.html:576` 现在是：

```html
            <div style="font-size:11px;color:var(--text-muted);margin-bottom:6px">勾选 AI 评分偏差模式，帮助系统学习您的评分偏好：</div>
```

改成（「勾选」→「选择」，因为下面由 checkbox 变成三选一）：

```html
            <div style="font-size:11px;color:var(--text-muted);margin-bottom:6px">选择 AI 评分偏差模式，帮助系统学习您的评分偏好：</div>
```

- [ ] **Step 3: 重写 `renderDetailCalib`**

`homework.html:995-1000`（注释 4 行 + 函数 4 行）现在是：

```js
// 功能 4.10（F7 的地盘）：F5 **不出校准**——那是 F7 的读职责。
// 区块保留（4.10 是正式需求），出空态；要显示得先等 F7 定下校准项的取值集合
// （DOC_ISSUES 第 37 条：校准项文档从未定义，且 score_calibrations 装不下页面的
// 「按维度勾三项」）。
function renderDetailCalib(d) {
  document.getElementById("calibGrid").innerHTML =
    emptyBlock("暂无校准项（数据源待接入）");
}
```

整段（注释 + 函数）替换成：

```js
// 功能 4.10（F7）：取值集合已定为三值整体模式，与 score_calibrations.bias_mode
// 一一对应（F7 spec 3.1）。**不再按维度勾三项**——表里只有一列 bias_mode，
// 「音准偏高」+「气息偏高」同时勾选存不下（DOC_ISSUES 第 37 条）。
// d.calibration 为 null = 没校准过 → 三个都不选。
const CALIB_OPTIONS = [
  { value: "high", label: "AI 评分偏高" },
  { value: "low",  label: "AI 评分偏低" },
  { value: "ok",   label: "AI 评分合适" },
];

function renderDetailCalib(d) {
  // bias_mode 是后端透传的字符串，先按白名单收口再用——直接拿它比 value 的话，
  // 库里若出现第四个值（历史数据/手改），三个 radio 会全不选中，看起来像「没校准过」。
  const cur = (d.calibration && d.calibration.bias_mode) || null;
  document.getElementById("calibGrid").innerHTML = CALIB_OPTIONS.map(o => `
    <label class="calib-item">
      <input type="radio" name="calibBias" value="${o.value}"${o.value === cur ? " checked" : ""}>
      <span>${o.label}</span>
    </label>`).join("");
}
```

- [ ] **Step 4: 在 `submitReview` 里串上 F7**

`homework.html:1168` 起是 `async function submitReview() {`，其中 F6 成功后的分支在 `:1203` 以：

```js
    // 成功。响应体不用（spec 3.11）：两条列表刷新完就是最新的。
    if (currentSubId === id) {
```

开头。在 `// 成功。` 那行（`:1203`）**之前**插入下面这段（即 F6 的 `if (!res.ok)` 块结束、`res` 确认成功后）：

```js
    // 功能 4.10：校准串在终审**之后**发（F7 spec 3.9）。顺序不能反——F7 的
    // teacher_score 是从 submissions 读的，那正是上面这次 F6 刚写进去的值。
    // 一项都没选就不发：不制造「撤销」（F7 的 bias_mode=null 会删行）。
    const bias = document.querySelector('input[name="calibBias"]:checked')?.value;
    if (bias) {
      try {
        const r2 = await fetch(`${API_BASE}/api/submissions/${id}/calibration`, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ bias_mode: bias }),
        });
        if (!r2.ok) throw new Error(String(r2.status));
      } catch (e) {
        // 终审已经落库、列表马上要刷新了，这时报「发布失败」是在说谎；教师会重复
        // 点击，而 F6 是覆盖语义，重复点只会白刷一次 reviewed_at。所以只提示校准
        // 这一半没成，不回滚、不重发（F7 spec 3.9）。
        alert("⚠️ 终审已保存，但校准未保存");
      }
    }
```

- [ ] **Step 5: 起后端 + worker，用 `/browse` 实走**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
source .venv/bin/activate
python app-d.py            # 8877
```

走查（用 `/browse` 技能，**不用** chrome MCP）：

1. 登录 `teacher01` / `xiyun@2026`
2. 打开 `http://127.0.0.1:8877/homework.html`
3. 选一份含待批提交的作业 → 点一条待批卡片（用 **submission 25** 那条：hw12 / 周明轩 / AI 78.9。
   注意是**周明轩**不是刘思琪——刘思琪 75.2 是 submission 24，别点错）
4. 确认「🎯 AI 评分校准」区块出现三个 radio，且**都不选中**（25 起始无校准）
5. 选「AI 评分偏高」→ 点「✅ 通过并发布」
6. 确认出现成功提示、左侧该卡片消失
7. 用 psql 确认库里多了一行：`select * from score_calibrations where submission_id=25;` →
   `bias_mode='high'`、`ai_score=78.9`、`teacher_score` = 刚填的终审分
8. 重新点开同一条提交（若已不在待批列表，直接改 URL 或先把它改回 `ai_scored` 再点），
   确认 radio 回显「AI 评分偏高」被选中

> 步骤 8 需要该提交仍在待批列表里。若它已被批掉、列表不再显示，就改走
> `curl -b teacher.jar http://127.0.0.1:8877/api/submissions/25/detail` 核对
> `data.calibration.bias_mode`，并在浏览器里手工调 `renderDetailCalib({calibration:{bias_mode:"high"}})`
> 确认渲染出选中态——**两条都要做**，接口回参正确不等于渲染正确。

- [ ] **Step 6: 复原（submission 25 上造的行）**

先抓该行的 id，再按 id 删：

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -At -c \
  "select id from score_calibrations where submission_id=25;"
# 若上面有输出（例如 5），按那个 id 删：
docker exec docker_postgres psql -U xiyun -d xiyun -c \
  "DELETE FROM score_calibrations WHERE id = 5;"
```

另外 F6 会把 submission 25 从 `ai_scored` 改成 `reviewed` 并写入 `teacher_score`——
这是**页面正常使用**的副作用，不是脏数据。若要还原演示态：

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -c \
  "UPDATE submissions SET status='ai_scored', teacher_score=NULL, teacher_comment=NULL, reviewed_at=NULL WHERE id = 25;"
```

最后与基线对照：

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -At -P null='<NULL>' \
  -c "select id,submission_id,teacher_id,bias_mode,ai_score,teacher_score,created_at from score_calibrations order by id;" \
  | diff /tmp/f7fe/baseline.txt -
docker exec docker_postgres psql -U xiyun -d xiyun -At -P null='<NULL>' \
  -c "select id,status,teacher_score,teacher_comment,reviewed_at from submissions order by id;"
```

Expected：diff **无输出**；submissions 的 25 行回到 `25|ai_scored|<NULL>|<NULL>|<NULL>`。

- [ ] **Step 7: 提交**

```bash
git add homework.html
git commit -m "feat: homework.html 校准区块由空态改为三选一，随终审提交"
```

---

### Task 6: 文档同步（DOC_ISSUES 第 37 条改写 + F5 spec 标注推翻）

**Files:**
- Modify: `DOC_ISSUES.md`（第 37 条整条改写）
- Modify: `docs/superpowers/specs/2026-10-08-submission-detail-page-design.md`（头部加推翻声明 + §6.1 待确认 ① 改写）
- Modify: `docs/superpowers/specs/2026-10-08-submission-detail-api-design.md`（若其中有「不出校准」的表述，同样标注）

**Interfaces:**
- Consumes: 无（纯文档）
- Produces: `DOC_ISSUES` 第 37 条反映「已自拟落地 + 剩余缺口」，F5 的两份 spec 不再声称「不出校准」。

- [ ] **Step 1: 找出所有需要改的「F5 不出校准」表述**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
grep -n "不出校准\|不做校准写入\|接口不出" DOC_ISSUES.md \
  docs/superpowers/specs/2026-10-08-submission-detail-page-design.md \
  docs/superpowers/specs/2026-10-08-submission-detail-api-design.md
```

把结果记下来——每一处都要处理（改写或加标注），不能只改一处。

- [ ] **Step 2: 改写 `DOC_ISSUES` 第 37 条**

第 37 条现在的小节是「问题一 / 问题二 / 真库现状 / 当前处理 / 待文档方确认」。改成
「**问题一（仍在）** / **问题二（本次以改页面规避）** / 真库现状 / **本次的处置** /
**自拟口径** / **待文档方确认**」，其中：

- 「当前处理：F5 不出校准」整段**删掉**，替换为本次的处置（F7 已实现，F5 出参加字段）。
- 「待文档方确认」原三条保留（校准项集合、DDL、数据回流），再补两条（与 spec §8 的
  后两条对应，共 5 条）：

```
4. 校准该不该与终审绑定（只有 `reviewed` 之后才能勾）？本次**不限制**（spec 3.5）。
5. 学生的校准结果要不要可见？本次只在教师端批改页回显——F5 本身是教师接口。
```

- 另加「本次自拟并落地的口径」七条：

```
**本次自拟并落地的口径（2026-10-08，F7）**：

1. **校准项取值集合**定为 `high` / `low` / `ok` 三值整体模式——依据是 `schema.sql:161`
   的列注释给的就是这三个词，且 4.10 用的词是「偏差**模式**」（单数）、页面提示语是
   「学习**您的评分偏好**」（整体松紧倾向，非某一维度）。文档本身仍无定义。
2. **`(submission_id, teacher_id)` 上无唯一约束**，靠 service 层先查后写做 upsert。
   **确认不加约束**（本次零 DDL）——并发下可能插重，教师单人操作下不会发生。
3. **撤销语义**：请求体显式 `bias_mode: null` = 删除该行。文档未定义。
4. **F5 出参新增 `calibration` 字段**（推翻本条第「当前处理」与 F5 spec §6.1 的
   「F5 不出校准」）。同一提交有多行时**取最新一条**（`created_at DESC, id DESC`），
   文档未定义取法。
5. **校准不与终审绑状态**：可对 `ai_scored` 的提交写校准，此时 `teacher_score` 为
   `null`（读的是 `submissions.teacher_score`，还没被 F6 写过）。文档未把两者绑定。
6. **前端三条口径**：校准随终审**串行提交**（F6 成功后发 F7，顺序不能反）、F7 失败
   **不回滚终审**（只提示「终审已保存，但校准未保存」）、**一项都没选就不发**（不制造
   撤销）。文档对此零定义。
7. **「数据回流」仍无消费方**（原 ③ 维持，本次不消解）：4.10 提到把校准数据回流用于
   模型改进，但今天没有任何代码读 `score_calibrations`——F5 的 `calibration` 字段是
   第一个读点，也只读不消费。谁在什么时候消费这张表，文档未答。
```

这七点与 spec §7 一一对应（spec 的第 6 点是原 ③ 的维持，本条并入第 7 点）。

- [ ] **Step 3: 在 F5 page spec 头部加推翻声明**

在 `docs/superpowers/specs/2026-10-08-submission-detail-page-design.md` 的标题之下、
正文之上插入：

```markdown
> **本文 §6.1 关于「F5 不出校准」的结论已于 2026-10-08 被推翻。** F7 在《5-接口清单》
> 里只有 POST，读职责没有落点，因此改为由 F5 出参加 `calibration` 字段（取最新一条）。
> 新的口径见 `2026-10-08-submission-calibration-design.md` §3.6 与 §4.5。本文其余部分
> （尤其 §3.x 的空态文案与渲染分组）仍然有效，但「🎯 AI 评分校准」那块不再是空态。
```

- [ ] **Step 4: 改写该 spec §6.1 的待确认 ①**

找到 §6.1 里那段以「功能 4.10 / F7 的校准项取值集合没有定义」开头的文字（约 `:383`），
在它末尾追加一句：

```
（2026-10-08 更新：已在 F7 实现中自拟为 `high`/`low`/`ok` 三值整体模式，页面由「按维度
勾三项」改为三选一，F5 出参新增 `calibration`。见 `2026-10-08-submission-calibration-design.md`。
本条从「阻塞」降级为「已自拟、待文档方追认」。）
```

- [ ] **Step 5: 核对没有遗漏**

```bash
grep -rn "不出校准" DOC_ISSUES.md docs/superpowers/specs/ | grep -v "已于 2026-10-08 被推翻\|2026-10-08 更新"
```

Expected：只剩**有意的历史引用**（若还有指向「现在不出校准」的表述，继续改）。

- [ ] **Step 6: 全量一致性闸门**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
PYTHONPATH=. .venv/bin/python scripts/check_db.py
```

Expected：与改动前一致（本计划零 DDL，若出现新的差异说明有人动了 schema 或模型，
停下来查）。**注意**：`demo_versions` 表与 `teacher_demos` 三列是既有漂移，在干净 main
上也会报，不算本次引入。

- [ ] **Step 7: 提交**

```bash
git add DOC_ISSUES.md docs/superpowers/specs/2026-10-08-submission-detail-page-design.md
git commit -m "docs: 第 37 条同步 F7 落地（自拟口径 + 剩余缺口），F5 spec 标注推翻"
```

---

## 收尾核对（全部任务完成后）

- [ ] `git status --short` 为空
- [ ] `git log --oneline -7` 能看到 6 个本次提交
- [ ] 真库 `score_calibrations` 与 `/tmp/f7fe/baseline.txt` 逐字符一致
- [ ] 真库 `submissions` 的 25 行回到 `ai_scored`
- [ ] `homework.html` 全文再 grep 一次 `calib`：只有 CSS、`calibGrid`、`CALIB_OPTIONS`、
      `renderDetailCalib`、`submitReview` 里那一处，**没有残留的 mock 校准数据**
- [ ] 后端进程已停

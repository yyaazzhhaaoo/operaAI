# F6 教师终审批改接口实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 `POST /api/submissions/<id>/review`——教师写终审分/终审评语/语音点评，并把该条提交从「待批改」推进到 `reviewed`。

**Architecture:** 沿用 F1/F4/F5 的四层。路由层只做「取 body → pydantic 校验 → 调 service → 装信封」；service 判 404、校验引用资源、写列、commit；repo 只标脏不 commit。核心语义是 **PATCH**：请求体里**没出现**的字段保持原值，**显式 `null`** 才清空——靠 pydantic v2 的 `model_fields_set` 区分。

**Tech Stack:** Flask 3.1 + SQLAlchemy 2.x + pydantic v2 + PostgreSQL 15；无测试框架（验证靠 `/tmp` 脚本 + curl + psql）。

**依据：** `docs/superpowers/specs/2026-10-08-submission-review-api-design.md`（下称 spec，本文所有 §x.y 都指它）。

## Global Constraints

- 所有交流、注释、文档、commit message 用**简体中文**；代码标识符保持英文。
- `/api` 前缀**只在** `app/api/__init__.py` 的 `url_prefix` 里写一次；路由一律写相对路径。
- `app.register_blueprint(api_bp)` 已在 `app-d.py` 末尾，本计划**不动** `app-d.py`。
- 用 `.venv/bin/python`；Python 3.11。
- 事务边界：**repo 只 `db.flush()`，`db.commit()` 只在 service**。
- 出参含 `datetime` 时路由层**必须** `.model_dump(mode="json")`（默认 dump 出 RFC-822）。
- 失败一律由 service 抛 `BusinessError(code, message)`，路由层**不写** `try/except`、不写 `fail(...)`。
- 错误码与 HTTP 状态码一致：401 未登录 / 403 需要教师权限 / 404 提交不存在、接口不存在 / 422 参数错误。
- **不引入 pytest**（项目无测试框架），验证脚本写在 `/tmp/f6/`，**不提交**。
- **临时改库只能按抓到的 id 改回**，绝不 `DELETE FROM <表> WHERE <别的列>`、绝不整表清空。
- 提交直接落在 `main`，不开分支、不发 PR。
- **不改** `app/common/errors.py` 的 `_MSG_CN`（spec §3.7）；**不改** `schema.sql`；**不抽** 公共 `_payload()`。
- 真库基线（spec §2.3，已实测）：`submissions` 只有 id **23–27** 五行，全为 `ai_scored`；`audio_files` 的 id **从 74 起**（`min(id)=74`），`1` 不存在。

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `app/repositories/homeworks_repo.py` | 末尾追加两个函数 | `get_submission`（一条主键查询取行）、`apply_review`（把变更写到 ORM 行上） |
| `app/schemas/homework.py` | 第 3 行改 import，末尾追加两个模型 | `SubmissionReviewIn`（本文件第一个**请求体**模型）、`SubmissionReviewResponse` |
| `app/services/homework_service.py` | 改 import，末尾追加一个函数 | `review_submission`——判 404、校验音频、写列、组装出参、commit |
| `app/api/homeworks.py` | 第 1–5 行改 import，第 49–53 行换实现 | 路由 + `_payload()` |
| `DOC_ISSUES.md` | 新增第 38 条、更正第 25/34 条 | 登记自拟口径与待确认项 |

**不改的相邻桩**：`app/api/homeworks.py:55-59` 的 `submissions_calibration`（F7）与 `:23-27` 的 `homeworks_submit`（F3）保持原样。

**验证脚本（不提交）**：`/tmp/f6/t1.py`、`/tmp/f6/t3.py`、`/tmp/f6/e2e.sh`、`/tmp/f6/t5.sh`。

---

### Task 1: repo 两个函数

**Files:**
- Modify: `app/repositories/homeworks_repo.py`（在末尾追加，文件现 181 行）
- Test: `/tmp/f6/t1.py`（新建，不提交）

**Interfaces:**
- Consumes: `app.models.Submission`（该文件第 4 行**已经** import 了，不用改 import）
- Produces:
  - `get_submission(db: Session, submission_id: int) -> Submission | None`
  - `apply_review(db: Session, row: Submission, changes: dict) -> None`

- [ ] **Step 1: 追加两个函数**

在 `app/repositories/homeworks_repo.py` **末尾**追加（`get_submission_detail` 的 `return` 之后，保持文件末尾的空行风格）：

```python


def get_submission(db: Session, submission_id: int) -> Submission | None:
    """按 id 取一条提交，不存在返回 None。供 F6 判 404 与标脏。

    **不复用上面的 get_submission_detail**：那个为 F5 一次取四张表的字段、走三段
    LEFT JOIN，而且返回的是**元组**——元组改不了 ORM 属性。F6 只要 Submission 本身
    （要往它的列上写值），单独 get 是一条主键查询，比复用那条 join 更省。
    """
    return db.get(Submission, submission_id)


def apply_review(db: Session, row: Submission, changes: dict) -> None:
    """把 changes 里的列写到 row 上。只标脏，commit 交给 service 层。

    `changes` 的 key 必须是**调用方已判定为「显式给出过」**的字段名——本函数不做
    「缺省 vs 显式 null」的区分，给什么写什么（那个判定在 service 里靠
    `model_fields_set` 做，见 spec 3.2）。

    `db` 本次没用到，保留它是为了守住本层「第一个参数永远是 db」的约定
    （见 app/repositories/__init__.py 开头的三条约定）。

    不 flush：本次没有自增 id 要拿（`annotations_repo.add` 要 flush 是为了拿 id），
    脏对象由 service 的 commit 一并写回。
    """
    for field, value in changes.items():
        setattr(row, field, value)
```

- [ ] **Step 2: 写验证脚本**

```bash
mkdir -p /tmp/f6
```

写 `/tmp/f6/t1.py`：

```python
"""F6 Task 1：repo 两个函数。**完全不碰库**——apply_review 用游离对象验，
get_submission 只读。"""
import sys

sys.path.insert(0, "/Users/meiyazhao/Documents/lianshu/operaAI")

from app.db import session_scope
from app.models import Submission
from app.repositories import homeworks_repo

ok = True

with session_scope() as db:
    # 1) 取真行
    row = homeworks_repo.get_submission(db, 25)
    print("1) get_submission(25) ->", row.id, row.status, row.teacher_score)
    if row is None or row.id != 25:
        print("   FAIL"); ok = False

    # 2) 不存在返回 None（不是抛异常）
    miss = homeworks_repo.get_submission(db, 99999)
    print("2) get_submission(99999) ->", miss)
    if miss is not None:
        print("   FAIL 应返回 None"); ok = False

    # 3) apply_review 在**游离对象**上验：根本不进 session，无落库风险
    ghost = Submission()
    homeworks_repo.apply_review(db, ghost, {"teacher_score": 66.5,
                                           "teacher_comment": "只标脏"})
    print("3) apply_review ->", ghost.teacher_score, repr(ghost.teacher_comment),
          "| status 未被碰:", ghost.status)
    if ghost.teacher_score != 66.5 or ghost.teacher_comment != "只标脏":
        print("   FAIL"); ok = False
    if ghost.status is not None:
        print("   FAIL apply_review 不该写 changes 以外的列"); ok = False

    # 4) 空 changes 是合法的（空 body 会走到这条）
    homeworks_repo.apply_review(db, ghost, {})
    print("4) 空 changes ->", ghost.teacher_score, "（不变）")
    if ghost.teacher_score != 66.5:
        print("   FAIL"); ok = False

print("\n结果:", "PASS" if ok else "FAIL")
```

- [ ] **Step 3: 跑脚本**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python /tmp/f6/t1.py
```

Expected（4 条 `1)`–`4)` 无 FAIL，末行 `结果: PASS`）：

```
1) get_submission(25) -> 25 ai_scored None
2) get_submission(99999) -> None
3) apply_review -> 66.5 '只标脏' | status 未被碰: None
4) 空 changes -> 66.5 （不变）

结果: PASS
```

- [ ] **Step 4: 确认没碰库**

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -tAc \
  "SELECT count(*) FROM submissions WHERE status <> 'ai_scored';"
```

Expected: `0`（脚本只读，一行都没改）。

- [ ] **Step 5: Commit**

```bash
git add app/repositories/homeworks_repo.py
git commit -m "feat: F6 repo 加 get_submission 与 apply_review

get_submission 走主键查询，明示不复用 get_submission_detail（那个走三段
LEFT JOIN 且返回元组，元组改不了 ORM 属性）。apply_review 只 setattr 标脏，
commit 留给 service 层，守住本层「只 flush 不 commit」的约定。"
```

---

### Task 2: 入参/出参模型

**Files:**
- Modify: `app/schemas/homework.py`（第 3 行改 import；末尾追加两个类，文件现 270 行）
- Test: `/tmp/f6/t2.py`（新建，不提交）

**Interfaces:**
- Consumes: 无（纯 pydantic，不碰库）
- Produces:
  - `SubmissionReviewIn`，字段 `teacher_score: float|None`、`teacher_comment: str|None`、`voice_comment_text: str|None`、`voice_comment_audio_id: int|None`，四个都有默认 `None`
  - `SubmissionReviewResponse`，字段 `submission_id: int`、`status: str|None`、`reviewed_at: datetime|None`、`teacher_score: float|None`、`teacher_comment: str|None`、`voice_comment_text: str|None`、`voice_comment_audio_id: int|None`

- [ ] **Step 1: 改 import**

`app/schemas/homework.py` 第 3 行现在是：

```python
from pydantic import BaseModel, ConfigDict
```

改成：

```python
from pydantic import BaseModel, ConfigDict, field_validator
```

（`datetime` 已在第 1 行 `from datetime import date, datetime` 里，不用补。）

- [ ] **Step 2: 追加两个模型**

在 `app/schemas/homework.py` **末尾**追加：

```python


class SubmissionReviewIn(BaseModel):
    """F6 入参（`POST /api/submissions/<id>/review`，功能 4.8/4.9/4.11）。

    四个字段全部可选，且**「字段不出现」与「显式给 null」是两件不同的事**：
      - 字段不出现 → 该列保持原值
      - 字段显式 null → 该列清空
    service 靠 `model_fields_set` 判，**不能**写成 `if v is not None`——那会把两者
    混成一种，「清空某个字段」就永远做不到（spec 3.2）。

    四个字段都不出现（`{}`）也合法，语义是「一键通过」：只推进状态，一个内容列都
    不动（spec 3.5，对应 mobile 文档的「一键通过（终审保留）」）。
    """

    teacher_score: float | None = None
    teacher_comment: str | None = None
    voice_comment_text: str | None = None
    voice_comment_audio_id: int | None = None

    @field_validator("teacher_score")
    @classmethod
    def _score_in_range(cls, v: float | None) -> float | None:
        """终审分限 0–100（前端 `#finalScore` 的 min/max 就是这个范围）。

        不用 `Field(ge=0, le=100)`：`app/common/errors.py` 的 `_MSG_CN` 只有
        missing / string_too_short / string_too_long / int_parsing 四条，**没有**
        `greater_than_equal` / `less_than_equal`，用 Field 越界时回的是 pydantic 的
        英文原文。这里抛中文，`_format_validation_error` 会去掉 "Value error, "
        前缀后原样展示（同 app/schemas/demo.py 的 `AnnotationIn._known_tag`）。

        另：给非数字（如 `"abc"`）时会在到达这里之前就被 pydantic 挡下，报的是
        英文的 `float_parsing`——`_MSG_CN` 同样没有这个键。照实接受，理由见 spec 3.7。
        """
        if v is not None and not 0 <= v <= 100:
            raise ValueError("终审评分必须在 0 到 100 之间")
        return v


class SubmissionReviewResponse(BaseModel):
    """F6 出参：**只回本接口写下去的那几个字段**，不是 F5 的全量详情。

    不复用 F5 的 `SubmissionDetailResponse`：那个带着 lyrics / cdm_tags / bkt /
    feature_matrix 等一堆本接口用不上的形状，复用它会让 F6 的契约跟着 F5 一起变。
    前端写完要拿全量详情，再调一次 F5（spec 4.4）。
    """

    # from_attributes 在本模型上其实**用不到**——service 是用关键字参数构造的
    # （submission_id 与 ORM 的 row.id 不同名，`model_validate(row)` 走不通）。
    # 留着是为了与本文件另外 8 个响应模型一致：9 个里 8 个有它，独缺这个才是会
    # 被挑出来的不一致。
    model_config = ConfigDict(from_attributes=True)

    submission_id: int
    status: str | None
    reviewed_at: datetime | None
    teacher_score: float | None
    teacher_comment: str | None
    voice_comment_text: str | None
    voice_comment_audio_id: int | None
```

- [ ] **Step 3: 写验证脚本**

写 `/tmp/f6/t2.py`——**PATCH 语义的判定全在这里，这是本任务真正的测试点**：

```python
"""F6 Task 2：两个模型。纯 pydantic，不碰库。重点是 model_fields_set 的三态。"""
import sys

sys.path.insert(0, "/Users/meiyazhao/Documents/lianshu/operaAI")

from pydantic import ValidationError

from app.schemas.homework import SubmissionReviewIn, SubmissionReviewResponse

FIELDS = ("teacher_score", "teacher_comment", "voice_comment_text",
          "voice_comment_audio_id")
ok = True


def show(label, payload):
    m = SubmissionReviewIn.model_validate(payload)
    present = [f for f in FIELDS if f in m.model_fields_set]
    print(f"{label:28} fields_set={present}")
    return m, present


# 1) 空 body：一个字段都不出现 -> 四个列全不动（一键通过）
_, p = show("1) {}", {})
if p != []:
    print("   FAIL 空 body 不该有 fields_set"); ok = False

# 2) 只给一个字段：只有它进 fields_set
_, p = show("2) {teacher_score: 88}", {"teacher_score": 88})
if p != ["teacher_score"]:
    print("   FAIL"); ok = False

# 3) **显式 null 与缺省必须可区分**——本任务的核心
m_absent, _ = show("3a) 未给 comment", {})
m_null, p = show("3b) comment: null", {"teacher_comment": None})
if "teacher_comment" not in m_null.model_fields_set:
    print("   FAIL 显式 null 必须进 fields_set，否则清空做不到"); ok = False
if m_null.teacher_comment is not None or m_absent.teacher_comment is not None:
    print("   FAIL 两者值都该是 None"); ok = False
if len(p) != 1:
    print("   FAIL"); ok = False

# 4) 范围：0 / 100 合法，越界报中文
for v in (0, 100, 82.5):
    m = SubmissionReviewIn.model_validate({"teacher_score": v})
    print(f"4) score={v} -> ok ({m.teacher_score})")
for v in (-0.5, 100.1, 101):
    try:
        SubmissionReviewIn.model_validate({"teacher_score": v})
        print(f"4) score={v} FAIL 该报错"); ok = False
    except ValidationError as e:
        msg = e.errors()[0]["msg"]
        print(f"4) score={v} -> {msg}")
        if "终审评分必须在 0 到 100 之间" not in msg:
            print("   FAIL 应是中文文案"); ok = False

# 5) 非数字：英文 float_parsing（**已知残留**，spec 3.7），只记录不断言通过
try:
    SubmissionReviewIn.model_validate({"teacher_score": "abc"})
except ValidationError as e:
    print("5) score='abc' ->", e.errors()[0]["type"],
          "|", e.errors()[0]["msg"], "（英文，已知）")

# 6) 各类合法形态
for payload in ({}, {"teacher_comment": ""}, {"voice_comment_audio_id": 74},
                {"teacher_comment": None, "voice_comment_text": "拖腔再稳一点"}):
    SubmissionReviewIn.model_validate(payload)
print("6) 四种合法体都通过")

# 7) 出参模型：datetime 走 mode="json" 出 ISO-8601 而不是 RFC-822
from datetime import datetime

r = SubmissionReviewResponse(submission_id=25, status="reviewed",
                             reviewed_at=datetime(2026, 10, 8, 12, 0, 0),
                             teacher_score=None, teacher_comment=None,
                             voice_comment_text=None, voice_comment_audio_id=None)
j = r.model_dump(mode="json")["reviewed_at"]
d = r.model_dump()["reviewed_at"]
print("7) mode=json ->", j)
print("   默认 dump ->", d)
if j != "2026-10-08T12:00:00":
    print("   FAIL 应是 ISO-8601"); ok = False
if isinstance(d, str):
    print("   FAIL 默认 dump 应仍是 datetime 对象（所以路由层必须传 mode=json）")
    ok = False

print("\n结果:", "PASS" if ok else "FAIL")
```

- [ ] **Step 4: 跑脚本**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python /tmp/f6/t2.py
```

Expected（无 FAIL，末行 `结果: PASS`）：

```
1) {}                         fields_set=[]
2) {teacher_score: 88}        fields_set=['teacher_score']
3a) 未给 comment              fields_set=[]
3b) comment: null             fields_set=['teacher_comment']
4) score=0 -> ok (0.0)
4) score=100 -> ok (100.0)
4) score=82.5 -> ok (82.5)
4) score=-0.5 -> Value error, 终审评分必须在 0 到 100 之间
4) score=100.1 -> Value error, 终审评分必须在 0 到 100 之间
4) score=101 -> Value error, 终审评分必须在 0 到 100 之间
5) score='abc' -> float_parsing | Input should be a valid number, unable to parse string as a number （英文，已知）
6) 四种合法体都通过
7) mode=json -> 2026-10-08T12:00:00
   默认 dump -> 2026-10-08 12:00:00
```

> 第 5 行是**已知残留**（`_MSG_CN` 没有 `float_parsing`），不算 FAIL。要在 spec §3.7 与 DOC_ISSUES 第 38 条里都留着这条记录。

- [ ] **Step 5: Commit**

```bash
git add app/schemas/homework.py
git commit -m "feat: F6 加 SubmissionReviewIn / SubmissionReviewResponse

入参四个字段全可选，靠 model_fields_set 区分「缺省」与「显式 null」，
清空字段才做得出来。范围校验用局部 field_validator 抛中文，没动共享的
_MSG_CN（那会顺带改掉 C5 等接口现在的越界文案）。

副作用：非数字走 pydantic 的 float_parsing，仍是英文——已知残留，
_MSG_CN 无此键，记进 DOC_ISSUES。"
```

---

### Task 3: service `review_submission`

**Files:**
- Modify: `app/services/homework_service.py`（改 import；末尾追加，文件现 356 行）
- Test: `/tmp/f6/t3.py`（新建，不提交）

**Interfaces:**
- Consumes: `homeworks_repo.get_submission`、`homeworks_repo.apply_review`（Task 1）、`SubmissionReviewIn`、`SubmissionReviewResponse`（Task 2）、`audio_repo.get_by_id`（**已存在**，`app/repositories/audio_repo.py:36`）、`BusinessError`
- Produces: `review_submission(db: Session, submission_id: int, data: SubmissionReviewIn) -> SubmissionReviewResponse`

- [ ] **Step 1: 改 import**

`app/services/homework_service.py` 现在第 7 行是：

```python
from app.repositories import homeworks_repo, user_repo
```

改成：

```python
from app.repositories import audio_repo, homeworks_repo, user_repo
```

再在文件里那段 `from app.schemas.homework import (...)` 的括号里，按字母序补两个名字：

```python
    SubmissionDetailResponse,
    SubmissionReviewIn,
    SubmissionReviewResponse,
    SubmissionTag,
```

（`datetime` 与 `BusinessError` **已经在**第 1、5 行 import 过，不用补。）

- [ ] **Step 2: 追加常量与函数**

在 `app/services/homework_service.py` **末尾**追加：

```python


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
```

- [ ] **Step 3: 写验证脚本（自带快照与复原）**

写 `/tmp/f6/t3.py`。**这个脚本会真 commit**，所以第一步先按 id 抓快照、最后按 id 改回并断言复原一致：

```python
"""F6 Task 3：service review_submission。会**真 commit**，所以自带快照+复原+断言。"""
import sys
import time

sys.path.insert(0, "/Users/meiyazhao/Documents/lianshu/operaAI")

from sqlalchemy import event, select

from app.common.errors import BusinessError
from app.db import SessionLocal, engine
from app.models import Submission
from app.schemas.homework import SubmissionReviewIn
from app.services import homework_service

COLS = ("teacher_score", "teacher_comment", "voice_comment_audio_id",
        "voice_comment_text", "status", "reviewed_at")
IDS = (23, 24, 25, 26, 27)
SEL = []


@event.listens_for(engine, "before_cursor_execute")
def _rec(conn, cur, stmt, params, ctx, many):
    if stmt.lstrip().upper().startswith("SELECT") and "submissions" in stmt:
        SEL.append(stmt)


def snap():
    with SessionLocal() as s:
        rows = s.scalars(select(Submission).where(Submission.id.in_(IDS))).all()
        return {r.id: {c: getattr(r, c) for c in COLS} for r in rows}


def restore(base):
    with SessionLocal() as s:
        for sid, vals in base.items():
            r = s.get(Submission, sid)
            for c, v in vals.items():
                setattr(r, c, v)
        s.commit()


ok = True


def run(label, sid, body, expect=None):
    """调 service。expect 为 (code, message) 时要求抛该错。"""
    global ok
    with SessionLocal() as s:          # 每次新 session：identity map 干净，SELECT 可计数
        try:
            out = homework_service.review_submission(s, sid, body)
        except BusinessError as e:
            got = (e.code, e.message)
            if got == expect:
                print(f"OK   {label}: {got[0]} {got[1]}")
            else:
                print(f"FAIL {label}: 期望 {expect}，实得 {got}"); ok = False
            return None
        if expect is not None:
            print(f"FAIL {label}: 期望抛 {expect}，实际成功 {out.model_dump()}")
            ok = False
            return None
        print(f"OK   {label}: {out.model_dump()}")
        return out


before = snap()

# 1) 提交不存在 -> 404
run("1) 提交不存在", 99999, SubmissionReviewIn(), (404, "提交不存在"))

# 2) 语音音频不存在 -> 422，且此时一行都不该被改
run("2) 音频不存在", 25, SubmissionReviewIn(voice_comment_audio_id=999999),
    (422, "语音点评音频不存在"))
if snap()[25]["status"] != before[25]["status"]:
    print("FAIL 2) 抛错前就写了列（事务没有回滚干净）"); ok = False

# 3) 空 body -> 一键通过；同时数 SELECT
SEL.clear()
out = run("3) 空 body（25 号）", 25, SubmissionReviewIn())
print(f"     status={out.status} reviewed_at={out.reviewed_at} "
      f"teacher_score={out.teacher_score}")
print(f"     submissions 上的 SELECT 条数 = {len(SEL)}（期望 1）")
if len(SEL) != 1:
    print("     FAIL：多出的 SELECT 说明出参是在 commit 之后读属性拼的")
    ok = False
if not (out.status == "reviewed" and out.reviewed_at and out.teacher_score is None):
    print("     FAIL：空 body 只该推进状态，teacher_score 保持 NULL"); ok = False

# 4) PATCH：只给 score，24 号原有的评语必须留着
c_before = before[24]["teacher_comment"]
out = run("4) 只给 score（24 号）", 24, SubmissionReviewIn(teacher_score=90.0))
if out.teacher_comment != c_before:
    print("     FAIL 评语被清掉了（说明用了 is not None 判字段）"); ok = False
else:
    print(f"     评语保留: {out.teacher_comment[:18]}...")

# 5) PATCH：显式 null 清空评语，分不动
out = run("5) 评语显式 null（24 号）", 24, SubmissionReviewIn(teacher_comment=None))
if out.teacher_comment is not None or out.teacher_score != 90.0:
    print("     FAIL 显式 null 应清空评语且不动分数"); ok = False

# 6) 覆盖：已 reviewed 再调，reviewed_at 刷新
a = run("6a) 第一次（25 号）", 25, SubmissionReviewIn(teacher_score=70.0))
time.sleep(0.02)
b = run("6b) 覆盖一次（25 号）", 25, SubmissionReviewIn(teacher_score=71.0))
if not b.reviewed_at > a.reviewed_at:
    print("     FAIL 覆盖时 reviewed_at 应刷新"); ok = False
else:
    print(f"     reviewed_at 刷新: {a.reviewed_at} -> {b.reviewed_at}")

# 7) 音频存在时走通（真库最小 id 是 74）
run("7) 音频 74 存在（25 号）", 25, SubmissionReviewIn(voice_comment_audio_id=74))

# 复原
restore(before)
after = snap()
print(f"\n复原一致: {after == before}")
if after != before:
    ok = False
    for sid in IDS:
        if after[sid] != before[sid]:
            print(f"  差异 {sid}\n    快照 {before[sid]}\n    实况 {after[sid]}")

print("\n结果:", "PASS" if ok else "FAIL")
```

- [ ] **Step 4: 跑脚本**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python /tmp/f6/t3.py
```

Expected（全部 `OK`，`SELECT 条数 = 1`，末两行 `复原一致: True` 与 `结果: PASS`）：

```
OK   1) 提交不存在: 404 提交不存在
OK   2) 音频不存在: 422 语音点评音频不存在
OK   3) 空 body（25 号）: {...'status': 'reviewed', 'reviewed_at': '...', 'teacher_score': None...}
     status=reviewed reviewed_at=2026-10-08 ... teacher_score=None
     submissions 上的 SELECT 条数 = 1（期望 1）
OK   4) 只给 score（24 号）: {...'teacher_score': 90.0, 'teacher_comment': "音准偏差较大，建议先进行单音模唱训练。"...}
     评语保留: 音准偏差较大，建议先进行单音模唱训练。...
OK   5) 评语显式 null（24 号）: {...'teacher_comment': None, 'teacher_score': 90.0...}
OK   6a) 第一次（25 号）: {...}
OK   6b) 覆盖一次（25 号）: {...}
     reviewed_at 刷新: 2026-10-08 ... -> 2026-10-08 ...
OK   7) 音频 74 存在（25 号）: {...'voice_comment_audio_id': 74...}

复原一致: True

结果: PASS
```

- [ ] **Step 5: 独立确认真库已复原（不信脚本自己的断言）**

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -c \
  "SELECT id, teacher_score, status, reviewed_at FROM submissions ORDER BY id;"
```

Expected（与 spec §2.3 基线逐字一致：23/24 有分、全 5 行 `ai_scored`、`reviewed_at` 全空）：

```
 id | teacher_score |  status   | reviewed_at
----+---------------+-----------+-------------
 23 |          82.5 | ai_scored |
 24 |          75.2 | ai_scored |
 25 |               | ai_scored |
 26 |               | ai_scored |
 27 |               | ai_scored |
```

- [ ] **Step 6: Commit**

```bash
git add app/services/homework_service.py
git commit -m "feat: F6 service 实现 review_submission

全项目第一处把 submissions.status 写成 reviewed 的代码。PATCH 语义靠
model_fields_set，出参在 commit 之前组装（避免属性过期后多发 SELECT）。
音频不存在回 422 而不是 404——404 留给 URL 里的具名资源。"
```

---

### Task 4: 路由换掉桩

**Files:**
- Modify: `app/api/homeworks.py`（改第 1–5 行 import；第 49–53 行整段替换）
- Test: `/tmp/f6/e2e.sh`（新建，不提交）

**Interfaces:**
- Consumes: `homework_service.review_submission`（Task 3）、`SubmissionReviewIn`（Task 2）
- Produces: `POST /api/submissions/<int:submission_id>/review` 的视图函数 `submissions_review`

- [ ] **Step 1: 改 import**

`app/api/homeworks.py` 第 1–5 行现在是：

```python
from app.api import api_bp
from app.common.decorators import login_required, teacher_required, student_required
from app.db import get_db
from app.response import ok
from app.services import homework_service
```

改成（`request` 与 schemas 都是新加的；`student_required` 仍被 F3 的桩用着，**不要删**）：

```python
from flask import request

from app.api import api_bp
from app.common.decorators import login_required, teacher_required, student_required
from app.db import get_db
from app.response import ok
from app.schemas.homework import SubmissionReviewIn
from app.services import homework_service
```

- [ ] **Step 2: 换掉第 49–53 行的桩**

**注意**：第 55–59 行的 F7 桩（`/submissions/<id>/calibration`）**不要动**。

现在：

```python
@api_bp.route("/submissions/<id>/review",methods=["POST"])
@login_required
@teacher_required
def submissions_review(id):
    return ok(id)
```

整段替换成：

```python
def _payload() -> dict:
    """取 JSON 请求体。

    客户端没带 Content-Type: application/json 时 get_json() 会抛 415；
    silent=True 把它压成 None，这里再兜成 {}，让 pydantic 报「字段必填」
    而不是让 Flask 抛一个前端看不懂的 415。
    """
    return request.get_json(silent=True) or {}


@api_bp.route("/submissions/<int:submission_id>/review",methods=["POST"])
@login_required
@teacher_required
def submissions_review(submission_id):
    # 路径参数用 <int:...> 而不是 <id>：<id> 是字符串转换器，会把
    # /submissions/abc/review 也匹配进来再进视图去查库；<int:...> 让 Werkzeug 在
    # 路由层就挡掉（IntegerConverter 的正则是 \d+，连负数都不收），走 errors.py
    # 的统一 404「接口不存在」。同文件 F1/F4/F5。
    #
    # mode="json"：出参里有 datetime（reviewed_at）。默认 model_dump() 会给 Flask
    # 一个 datetime 对象，它按 RFC-822 序列化成 "Thu, 08 Oct 2026 00:00:00 GMT"；
    # mode="json" 出的是 ISO-8601。同 F1/F4/F5。
    data = SubmissionReviewIn.model_validate(_payload())
    return ok(homework_service.review_submission(
        get_db(), submission_id, data).model_dump(mode="json"))
```

`_payload()` 是**第三份逐字复制**（另两份在 `app/api/auth.py:27-34` 与
`app/api/demos_segments_annotations.py:18-25`）——这是本项目的既有形态，抽到
`app/common/` 属无关重构，**不做**。**`silent=True` 不能省**。

- [ ] **Step 3: 起服务**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
mkdir -p /tmp/f6
nohup .venv/bin/python app-d.py > /tmp/f6/server.log 2>&1 &
sleep 3 && tail -5 /tmp/f6/server.log
```

Expected: 日志里出现 `Running on http://127.0.0.1:8877`，**没有** `Traceback`。
（F6 不走 redis、不走 celery，**不需要 worker**。）

- [ ] **Step 4: 登录取两个 session**

```bash
T=/tmp/f6/t.jar; S=/tmp/f6/s.jar
curl -s -c $T -X POST http://127.0.0.1:8877/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"teacher01","password":"xiyun@2026"}'; echo
curl -s -c $S -X POST http://127.0.0.1:8877/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"stu001","password":"xiyun@2026"}'; echo
```

Expected: 两条都是 `{"code":0,"message":"ok","data":{...}}`，教师那条 `data.role` 是 `teacher`，学生那条是 `student`。若返回 401，检查密码是否是 `xiyun@2026`。

- [ ] **Step 5: 写 e2e 脚本**

写 `/tmp/f6/e2e.sh`：

```bash
#!/bin/bash
# F6 Task 4：契约验证。用例 8/10/14/15 会真改库，跑完必须跑 Task 5 的复原。
set -u
B=http://127.0.0.1:8877
T=/tmp/f6/t.jar
S=/tmp/f6/s.jar

hit() {  # hit <名字> <cookie|-> <路径> <body|-> [额外 curl 参数...]
  local name=$1 ck=$2 path=$3 body=$4; shift 4
  local args=(-s -o /tmp/f6/out.json -w '%{http_code}' -X POST "$B$path")
  [ "$ck" != "-" ] && args+=(-b "$ck")
  [ "$body" != "-" ] && args+=(-H 'Content-Type: application/json' -d "$body")
  local code
  code=$(curl "${args[@]}" "$@")
  printf '%-30s HTTP %s  %s\n' "$name" "$code" "$(cat /tmp/f6/out.json)"
}

echo "--- 鉴权 ---"
hit "1 未登录"          -  /api/submissions/24/review '{}'
hit "2 学生登录"        $S /api/submissions/24/review '{}'

echo "--- 资源不存在 ---"
hit "3 提交不存在"      $T /api/submissions/99999/review '{}'
hit "4 非数字 id"       $T /api/submissions/abc/review   '{}'
hit "5 负数 id"         $T /api/submissions/-1/review    '{}'

echo "--- 校验 ---"
hit "6 score=101"       $T /api/submissions/26/review '{"teacher_score":101}'
hit "7 score=-0.5"      $T /api/submissions/26/review '{"teacher_score":-0.5}'
hit "8 score=88.25"     $T /api/submissions/26/review '{"teacher_score":88.25}'
hit "9 音频不存在"      $T /api/submissions/26/review '{"voice_comment_audio_id":999999}'
hit "10 音频 74 存在"   $T /api/submissions/26/review '{"voice_comment_audio_id":74}'
hit "11 score='abc'"    $T /api/submissions/26/review '{"teacher_score":"abc"}'
hit "12 body 是数组"    $T /api/submissions/26/review '[1,2]'

echo "--- Content-Type ---"
hit "13 非 JSON CT"     $T /api/submissions/27/review '{}' -H 'Content-Type: text/plain'

echo "--- 一键通过 / 覆盖 ---"
hit "14 空 body（27）"  $T /api/submissions/27/review '{}'
hit "15 再来一次（27）" $T /api/submissions/27/review '{}'
```

- [ ] **Step 6: 跑 e2e**

```bash
chmod +x /tmp/f6/e2e.sh && /tmp/f6/e2e.sh
```

Expected（逐行核对 HTTP 码与 `code`；`data` 我只摘要关键字段）：

| # | 期望 |
|---|---|
| 1 | HTTP 401 `{"code":401,"message":"未登录","data":null}` |
| 2 | HTTP 403 `{"code":403,"message":"需要教师权限","data":null}` |
| 3 | HTTP 404 `{"code":404,"message":"提交不存在","data":null}` |
| 4 | HTTP 404 `{"code":404,"message":"接口不存在","data":null}` |
| 5 | HTTP 404 `{"code":404,"message":"接口不存在","data":null}` |
| 6 | HTTP 422 `{"code":422,"message":"teacher_score: Value error, 终审评分必须在 0 到 100 之间",...}` |
| 7 | HTTP 422 同 6 |
| 8 | HTTP 200 `"teacher_score":88.25`，`"status":"reviewed"` |
| 9 | HTTP 422 `{"code":422,"message":"语音点评音频不存在","data":null}` |
| 10 | HTTP 200 `"voice_comment_audio_id":74` |
| 11 | HTTP 422，message 是**英文** `teacher_score: Input should be a valid number...`（已知残留） |
| 12 | HTTP 422 |
| 13 | HTTP 200（**不是 415**）。`-H 'Content-Type: text/plain'` 让 Flask 拿不到 JSON；`silent=True` 把本该抛的 415 压成 `None`、兜成 `{}`，于是等同空 body。**去掉 `silent=True` 这条就会变 415** |
| 14 | HTTP 200 `"status":"reviewed"`，`reviewed_at` 非空，`teacher_score` 为 `null` |
| 15 | HTTP 200，`reviewed_at` 比 14 的**晚** |

> 用例 6 的 message 前缀 `teacher_score: ` 来自 `_format_validation_error` 的 `"{loc}: {msg}"` 拼接，`Value error, ` 被它 strip 掉——这正是 Task 2 里 validator 抛 `ValueError` 而非 `Field` 约束的效果。

- [ ] **Step 7: Commit**

```bash
git add app/api/homeworks.py
git commit -m "feat: F6 路由接上 review_submission

桩换成真实现。路径参数从 <id> 改成 <int:submission_id>，让 /submissions/abc/review
在路由层就 404，而不是进视图查库。_payload() 按既有两份逐字复制第三份，
不抽公共模块（那是无关重构）。"
```

---

### Task 5: PATCH 语义与跨接口副作用

**Files:**
- Test: `/tmp/f6/t5.sh`（新建，不提交）
- 不改任何生产代码

**Interfaces:**
- Consumes: Task 4 起好的服务；F1 `GET /api/homeworks`、F4 `GET /api/homeworks/<id>/submissions`、F5 `GET /api/submissions/<id>/detail`
- Produces: 无（验证任务）

**为什么单独一个任务**：Task 4 验的是**本接口自己的契约**，本任务验的是**它对别人的影响**——F6 是全项目第一处写 `reviewed` 的代码，会改掉 F4 的列表长度和 F1 的「批改中」，这是 DOC_ISSUES 第 25/34 条预告过的连带效果，值得实测一次。

- [ ] **Step 1: 先复原到基线（Task 4 改过 26/27）**

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -c "
UPDATE submissions SET
  teacher_score = CASE id WHEN 23 THEN 82.5 WHEN 24 THEN 75.2 ELSE NULL END,
  teacher_comment = CASE id
    WHEN 23 THEN '音准整体良好，拖腔处理有进步。建议在''雷''字拖腔时加强气息支撑，保持音高稳定。继续练习！'
    WHEN 24 THEN '音准偏差较大，建议先进行单音模唱训练。' ELSE NULL END,
  voice_comment_audio_id = NULL,
  voice_comment_text = NULL,
  status = 'ai_scored',
  reviewed_at = NULL
WHERE id IN (23,24,25,26,27);"
```

> **`WHERE id IN (...)` 这五个 id 是本期真库的固定值**，不是按条件筛出来的。`''雷''` 是 SQL 里对单引号的转义（原文是 `'雷'`）。**绝不改成 `DELETE`、绝不整表清空。**

- [ ] **Step 2: 确认基线两个派生量**

```bash
curl -s -b /tmp/f6/t.jar http://127.0.0.1:8877/api/homeworks/12/submissions \
  | .venv/bin/python -c "import sys,json; print('F4 待批条数 =', len(json.load(sys.stdin)['data']['submissions']))"
curl -s -b /tmp/f6/t.jar http://127.0.0.1:8877/api/homeworks \
  | .venv/bin/python -c "
import sys,json
for h in json.load(sys.stdin)['data']['homeworks']:
    if h['homework_id']==12:
        print('F1 hw12: status =', h['status'], '| pending_review_count =', h['pending_review_count'])"
```

Expected:

```
F4 待批条数 = 5
F1 hw12: status = grading | pending_review_count = 5
```

（这就是 spec §2.3 的基线。两处数字**必须相等**——F4 的 `PendingSubmissionItem` 文档里写着两者逐字同源。）

- [ ] **Step 3: 写 PATCH 与副作用脚本**

写 `/tmp/f6/t5.sh`：

```bash
#!/bin/bash
# F6 Task 5：PATCH 语义 + 跨接口副作用。**跑完必须执行 Step 5 的复原。**
set -u
B=http://127.0.0.1:8877
T=/tmp/f6/t.jar
py=/Users/meiyazhao/Documents/lianshu/operaAI/.venv/bin/python

post() { curl -s -b $T -X POST "$B/api/submissions/$1/review" \
           -H 'Content-Type: application/json' -d "$2"; }

detail() { curl -s -b $T "$B/api/submissions/$1/detail" \
           | $py -c "
import sys,json
d=json.load(sys.stdin)['data']
print('   F5: score=%r comment=%r voice_text=%r voice_id=%r status=%r'
      % (d['teacher_score'], d['teacher_comment'], d['voice_comment_text'],
         d['voice_comment_audio_id'], d['status']))"; }

f4() { curl -s -b $T "$B/api/homeworks/12/submissions" \
       | $py -c "import sys,json; print('   F4 待批条数 =', len(json.load(sys.stdin)['data']['submissions']))"; }

f1() { curl -s -b $T "$B/api/homeworks" | $py -c "
import sys,json
for h in json.load(sys.stdin)['data']['homeworks']:
    if h['homework_id']==12:
        print('   F1 hw12: status =', h['status'], '| pending =', h['pending_review_count'])"; }

echo '=== 步骤 1：现状（24 号有分有评语，基线 5 条待批）==='
detail 24; f4; f1

echo
echo '=== 步骤 2：只给分数，评语必须保留（PATCH 关键点）==='
post 24 '{"teacher_score":90}' > /dev/null; detail 24
echo '   期望：score=90.0 comment=音准偏差较大，建议先进行单音模唱训练。'

echo
echo '=== 步骤 3：评语显式 null，分数不动 ==='
post 24 '{"teacher_comment":null}' > /dev/null; detail 24
echo '   期望：comment=None score=90.0'

echo
echo '=== 步骤 4：只给语音文字，前两项都不动 ==='
post 24 '{"voice_comment_text":"拖腔再稳一点"}' > /dev/null; detail 24
echo '   期望：voice_text=拖腔再稳一点 score=90.0 comment=None'

echo
echo '=== 步骤 5：24 号离开待批列表（5 -> 4）==='
f4; f1

echo
echo '=== 步骤 6：把 5 条全批完，hw12 不再「批改中」==='
for i in 23 24 25 26 27; do post $i '{}' > /dev/null; done
f4; f1
echo '   期望：F4 = 0；F1 status != grading、pending = 0'
echo '   （这正是 DOC_ISSUES 第 25/34 条说的「等 F6 落地即自动恢复」）'
```

- [ ] **Step 4: 跑脚本**

```bash
chmod +x /tmp/f6/t5.sh && /tmp/f6/t5.sh
```

Expected（逐条与自己上面的「期望」行核对）：

```
=== 步骤 1：现状（24 号有分有评语，基线 5 条待批）===
   F5: score=75.2 comment='音准偏差较大，建议先进行单音模唱训练。' voice_text=None voice_id=None status='ai_scored'
   F4 待批条数 = 5
   F1 hw12: status = grading | pending = 5

=== 步骤 2：只给分数，评语必须保留（PATCH 关键点）===
   F5: score=90.0 comment='音准偏差较大，建议先进行单音模唱训练。' voice_text=None voice_id=None status='reviewed'
   期望：score=90.0 comment=音准偏差较大，建议先进行单音模唱训练。

=== 步骤 3：评语显式 null，分数不动 ===
   F5: score=90.0 comment=None voice_text=None voice_id=None status='reviewed'
   期望：comment=None score=90.0

=== 步骤 4：只给语音文字，前两项都不动 ===
   F5: score=90.0 comment=None voice_text='拖腔再稳一点' voice_id=None status='reviewed'
   期望：voice_text=拖腔再稳一点 score=90.0 comment=None

=== 步骤 5：24 号离开待批列表（5 -> 4）===
   F4 待批条数 = 4
   F1 hw12: status = grading | pending = 4

=== 步骤 6：把 5 条全批完，hw12 不再「批改中」===
   F4 待批条数 = 0
   F1 hw12: status = closed | pending = 0
```

> 步骤 6 的 `status` 具体是 `closed` 还是 `ongoing` 取决于 hw12 的截止日与 `homeworks.status`（DOC_ISSUES 第 25 条记着 hw12 是 `status='open'` + 截止日 2026-08-02，早过今天）→ 预期 `closed`。**只要不是 `grading` 就算这条验过**；若不是 `closed`，照实记录实得值，别改代码去凑。

- [ ] **Step 5: 复原（必做）**

重跑 Step 1 那条 `UPDATE`，然后重跑 Step 2 的两条 curl。

Expected：`F4 待批条数 = 5`、`F1 hw12: status = grading | pending_review_count = 5`——与 Step 2 基线逐字一致。

- [ ] **Step 6: 再核一次全表**

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -c "
SELECT id, homework_id, student_id, ai_score, teacher_score, voice_comment_audio_id,
       voice_comment_text, status, reviewed_at FROM submissions ORDER BY id;"
```

Expected（与 spec §2.3 那张表逐列一致；`teacher_comment` 用 `\x` 或单独查一次确认原文没被改坏）：

```
 id | homework_id | student_id | ai_score | teacher_score | voice_comment_audio_id | voice_comment_text |  status   | reviewed_at
----+-------------+------------+----------+---------------+------------------------+--------------------+-----------+-------------
 23 |          12 |         48 |     82.5 |          82.5 |                        |                    | ai_scored |
 24 |          12 |         50 |     75.2 |          75.2 |                        |                    | ai_scored |
 25 |          12 |         53 |     78.9 |               |                        |                    | ai_scored |
 26 |          12 |         55 |     71.3 |               |                        |                    | ai_scored |
 27 |          12 |         52 |     85.7 |               |                        |                    | ai_scored |
```

- [ ] **Step 7: 停服务**

```bash
pkill -f "app-d.py" || true
```

本任务不改生产代码，**没有 commit**。

---

### Task 6: 登记 DOC_ISSUES 并收尾

**Files:**
- Modify: `DOC_ISSUES.md`（新增第 38 条，插在 `## 待核实` 之前；并更正第 25、34 条）

**Interfaces:**
- Consumes: Task 1–5 的全部结论
- Produces: 交付文档

- [ ] **Step 1: 确认插入点与现有最大编号**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
grep -n "^## 待核实" DOC_ISSUES.md
grep -n "^## 3[0-9]\." DOC_ISSUES.md | tail -3
```

Expected: `1233:## 待核实`；最大编号是 `## 37.`（`doc-superpowers` 那节之前）。若行号已变，**以实际为准**，不要照抄 1233。

- [ ] **Step 2: 插入第 38 条**

在 `## 待核实` 那**一行之前**插入（保持文件末尾原有的空行风格）：

````markdown
## 38. 教师终审批改（F6）只有一行描述，PATCH 语义/状态流转/错误码全自拟；4.11 的语音转文字无组件

《5-接口清单》2.6 里 F6 的全部内容是「`POST /api/submissions/<id>/review` ｜ 教师 ｜ 终审评分/点评/语音点评（audio_id + text）（功能 4.8/4.9/4.11）」。请求体字段名、字段可空性、状态流转、幂等语义、错误码**一个字都没写**。以下口径本次自拟，设计见 `docs/superpowers/specs/2026-10-08-submission-review-api-design.md`。

**自拟口径**（逐条对应 spec §3）：

| 项 | 口径 | 理由 |
|---|---|---|
| 只做终审 | 一调就写 `status='reviewed'`，**没有草稿态** | 文档只定义了终审；前端虽有「💾 保存草稿」按钮，但把草稿收进来要自造一套状态机 |
| PATCH 语义 | 字段**不出现** = 保持原值；**显式 `null`** = 清空 | 教师只补一条语音点评时不该抹掉已填的分数与评语，但又必须能清空；靠 pydantic 的 `model_fields_set` 区分 |
| 覆盖 | 已 `reviewed` 再调 = 覆盖更新，`reviewed_at` 刷新 | 库里没有退回/撤销接口，覆盖是唯一的修改途径 |
| 空 body | `{}` 合法 = 「一键通过」，只推进状态 | 对应 mobile 文档的「一键通过（终审保留）》 |
| `teacher_score` | 限 0–100，越界 422 | 前端 `#finalScore` 的 `min/max` 就是这个范围 |
| 音频不存在 | 回 **422**，不回 404 | 404 在本项目里留给「URL 里那个具名资源不存在」（F4/F5 的「作业不存在」「提交不存在」）；这是请求体引用了不存在的资源 |
| 权限 | 教师即可，**不校验归属** | 库里没有师生归属边，见下第 4 点 |

**六处文档/库表缺口**：

1. **4.11「语音识别转文字」在本项目没有实现组件。** 项目里没有任何 ASR——同第 20 条与本文档第 439 行记的「要从音频得到汉字需要语音识别，而解析链路没有这一环」（那也是 `segments.lyrics_json` 恒为 NULL 的原因）。所以 **`voice_comment_text` 服务端造不出来**，本接口只能把它当客户端给的普通字符串收下，既不生成、也不校验它与音频是否对得上。教师只传音频不传文字时，结果是「有音频、无文字」的一条语音点评——这是当前唯一可实现的形态。
2. **`submissions` 没有 `reviewer_id`，也没有任何指向 `users(id)` 的外键**，本接口**无法记录「是谁批的」**。终审在库里只留下「被批过」与「什么时候」，没有「谁」。**这不是全项目惯例，是一处不对称**：同一批批改功能里的 `score_calibrations` 就**有** `teacher_id`（真库那唯一一行是 `teacher_id=2`，见第 37 条）。「教师身份该不该落在批改结果上」，同一个 DDL 里已经给了两种答案。
3. **`status` 没有 CHECK 约束，也没有枚举类型。** `submitted / ai_scored / reviewed` 三个取值只活在 DDL 的行尾注释里，写错值不会报错。全文唯二的 `CHECK` 在 `users.role` 与 `annotations.tolerance` 上。另：`submitted` 这一档**全项目没有任何代码写它**（F3 提交接口仍是空桩），本接口也不写。
4. **没有教师归属模型。** `schema.sql` 里没有 `classes` 表，`students` 只有 `user_id/level/avatar/enrolled_at`，`users` 只有 `role`——任何教师与任何学生之间**没有任何归属边**。所以「这位教师能不能批这条提交」在库里无据可查，本接口与 F4/F5 一样不按教师过滤：**任何教师登录后都能批任何学生的任何提交**。
5. **覆盖语义下 `reviewed_at` ≠ 首次终审时间**，它会随每次覆盖刷新。库里没有 `updated_at`，也没有第二列可以存「首次终审时间」。
6. **「终审 = `status='reviewed'`」是本项目的推断**（承第 35 条已记的同一推断），F6 落地后这个推断第一次被执行。

**已落地的连带效果（更正第 25 条与第 34 条）**：第 25 条（`DOC_ISSUES.md:622`）与第 34 条（`:1039`）都记着同一条连带表现——「`grading` 的判据是 `submissions.status != 'reviewed'`，而当前全项目没有任何代码会把该列写成 `reviewed`……等 F6 落地即自动恢复」。**2026-10-08 F6 已落地，该表现消失**：真库 12 号作业的 5 条提交批完后，「批改中」随之下线（F4 待批条数 5 → 0，F1 的 `pending_review_count` 5 → 0、`status` 从 `grading` 变为 `closed`）。

**一处已知的英文报错（本次照实接受）**：`teacher_score` 给非数字（如 `"abc"`）时，pydantic 抛 `float_parsing`，而 `app/common/errors.py` 的 `_MSG_CN` 只有 missing / string_too_short / string_too_long / int_parsing 四条，**没有** `float_parsing`，于是回退成英文原文（`teacher_score: Input should be a valid number...`）。同理越界报中文是靠 F6 **自己**的 `field_validator` 抛 `ValueError` 实现的，而不是靠 `Field(ge=, le=)`——`_MSG_CN` 也缺 `greater_than_equal` / `less_than_equal`（C5 的 `AnnotationIn.tolerance` 今天就是英文）。**没有改这个共享 dict**：加键会顺带改掉 C5 等接口现在的越界文案，属本任务范围外的行为变更。要不要统一补齐，见待确认项。

**待文档方确认**：① 4.11 的「语音识别转文字」由谁实现——服务端没有 ASR，若将来要服务端转写，本接口的入参形态要改；② 要不要加 `reviewer_id` 列（加列要改 `schema.sql`，且历史数据只能为 NULL）；③ 4.8 的终审分与 `ai_score` 是否该有相对约束（本接口只设 0–100 的绝对范围，不限制教师把 75.2 改成 10 或 100）；④ 草稿态要不要做（前端已有按钮）；⑤ 退回/撤销终审要不要做（现在终审后无法改回待批改）；⑥ `status` 该不该加 CHECK 约束；⑦ 教师与学生的归属关系何时进库；⑧ `_MSG_CN` 要不要补齐 pydantic 的其余错误类型（含 `float_parsing`）。
````

- [ ] **Step 3: 更正第 25 条与第 34 条**

在第 25 条那段「另一处硬依赖」（`:622`）**之后**、第 26 条之前，追加一段（按 DOC_ISSUES 既有体例：追加更新行、保留原判断）：

```markdown

**2026-10-08 更新**：F6（`POST /api/submissions/<id>/review`）已落地，全项目第一处把 `submissions.status` 写成 `'reviewed'` 的代码。上段的连带表现至此消失——教师批完一份作业的全部提交后，「批改中」会正常下线。详见第 38 条。
```

第 34 条那段「一处连带表现」（`:1039`）**之后**、`### 34.3` 之前，追加：

```markdown

**2026-10-08 更新**：F6 已落地（见第 38 条），上段「全项目没有任何代码会把该列写成 `reviewed`」不再成立。真库 12 号作业的 5 条提交批完后，`grading` 如期退出、`pending_review_count` 归 0。
```

- [ ] **Step 4: 核对编号与锚点**

```bash
grep -n "^## 3[5-9]\." DOC_ISSUES.md
grep -c "^## 38\." DOC_ISSUES.md
grep -n "2026-10-08 更新" DOC_ISSUES.md
```

Expected: 出现 `## 35. / ## 36. / ## 37. / ## 38.` 四条且顺序递增；`grep -c` 输出 `1`（第 38 条只插了一次）；`2026-10-08 更新` 命中 **2** 处。

- [ ] **Step 5: 跑模型-真库一致性闸门**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python scripts/check_db.py; echo "退出码=$?"
```

Expected: **退出码 1**，且差异明细与本次改动**无关**——应恰好是既有的两处漂移（`demo_versions` 表、`teacher_demos` 的三个列，见记忆 `check-db-pre-existing-drift`）。F6 **没有**新增/修改任何列，所以**不许出现** `submissions` 相关的差异行。若出现了，说明改错了地方。

- [ ] **Step 6: Commit**

```bash
git add DOC_ISSUES.md
git commit -m "docs: 登记 DOC_ISSUES 第 38 条（F6 终审批改），并更正第 25/34 条

第 38 条记 F6 的自拟口径七项与六处文档/库表缺口（无 ASR、无 reviewer_id、
status 无 CHECK、无师生归属模型、reviewed_at 会被覆盖刷新、审=reviewed 是推断），
另记一处已知英文报错（_MSG_CN 缺 float_parsing）。

第 25/34 条原先都写着「全项目没有代码会写 reviewed，等 F6 落地即自动恢复」——
F6 已落地，按体例追加更新行、保留原判断。"
```

- [ ] **Step 7: 收尾检查**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git status --short
git log --oneline -6
```

Expected: `git status --short` **为空**（`/tmp/f6/` 不在仓库内）；`git log` 顶上 5 条是 Task 1–6 的 5 个 commit（Task 5 无 commit），加 spec 那条 `c2a67b4`。

---

## 自审

**1. spec 覆盖**——逐节对：

| spec 节 | 落在哪个 Task |
|---|---|
| §3.1 只做终审 | Task 3（恒写 `reviewed`，`submissions_review` 无第二个状态） |
| §3.2 PATCH 语义 | Task 2 Step 3 用例 3a/3b（判定本身）+ Task 3 用例 4/5 + Task 5 步骤 2–4 |
| §3.3 允许覆盖 | Task 3 用例 6a/6b + Task 4 用例 15 |
| §3.4 `voice_comment_text` 由客户端给 | Task 2 用例 6 + Task 3 用例 7 + Task 5 步骤 4 |
| §3.5 空 body 一键通过 | Task 3 用例 3 + Task 4 用例 14 |
| §3.6 权限 | Task 4 用例 1/2（401 + 403） |
| §3.7 范围用局部 validator | Task 2 Step 3 用例 4/5 + Task 4 用例 6/7/11 |
| §3.8 音频存在性 → 422 | Task 3 用例 2/7 + Task 4 用例 9/10 |
| §3.9 不做退回 | §6「明确不做」，无代码 |
| §3.10 不写 `score_calibrations` | §6「明确不做」；Task 3 的 SELECT 计数顺带证明只碰了 `submissions` |
| §3.11 不设长度上限 | Task 2（模型里确实没有 `max_length`） |
| §3.12 不写 `submitted` | Task 3（只出现 `"reviewed"` 一个字面量） |
| §4.5 `get_submission` 不复用 detail | Task 1 Step 1 的文档字符串 |
| §4.6 出参在 commit 前组装 | Task 3 Step 3 的 SELECT 计数断言（=1，多一条即 FAIL） |
| §5.6 复原纪律 | Task 3 Step 3 脚本自带 + Task 3 Step 5 独立复核 + Task 5 Step 1/5/6 |
| §7 第 38 条 + 更正第 25/34 条 | Task 6 |
| §8 待确认项 | Task 6 Step 2 结尾的 8 条（spec 的 7 条 + `_MSG_CN` 那条） |

**2. 占位符扫描**——无 TBD/TODO；每个改代码的步骤都给了完整代码；每个"跑一下"的步骤都给了命令与期望输出。

**3. 类型/命名一致性**——逐个核过：
- `get_submission(db, submission_id) -> Submission | None`（Task 1 定义 → Task 3 调用）
- `apply_review(db, row, changes: dict) -> None`（Task 1 定义 → Task 3 调用）
- `SubmissionReviewIn` / `SubmissionReviewResponse`（Task 2 定义 → Task 3、Task 4 调用）
- `review_submission(db, submission_id, data) -> SubmissionReviewResponse`（Task 3 定义 → Task 4 调用）
- `_REVIEW_FIELDS` 四个名字与模型的四个字段名**逐字相同**，与 `SubmissionsResponse` 的七个字段名也逐字相同——Task 3 的 `**{f: getattr(row, f) ...}` 展开后必须命中 `teacher_score`/`teacher_comment`/`voice_comment_text`/`voice_comment_audio_id` 四个关键字，已核。
- `audio_repo.get_by_id(db, audio_id)`（既有函数，未改名）
- 路由 `submissions_review(submission_id)` 的参数名与 `<int:submission_id>` 一致（Flask 要求同名，否则 500）

**4. 已知的两处不测**（照实登记，不假装覆盖）：
- `float_parsing` 的英文文案是**预期行为**，Task 2 用例 5 只打印不断言通过。
- `db.commit()` 的真实提交路径由 Task 3（真 commit）与 Task 4/5（走 HTTP）覆盖；Task 3 的 SELECT 计数断言是「出参在 commit 前组装」这条**性能**规则的唯一守卫，规则被违反时是**多一条 SELECT**，不会返回错值——所以它不测"数据对不对"，只测"有没有多发 SQL"。

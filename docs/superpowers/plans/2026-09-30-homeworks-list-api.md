# 作业列表接口（F1 `GET /api/homeworks`）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 F1——教师端的作业列表，每行含标题 / 截止日 / 曲目 / 提交人数 / 进度 / 状态，把 `app/api/homeworks.py:6-10` 的 `return ok()` 空桩换成真实现。

**Architecture:** 自下而上三层——**仓储层完全复用**（`homeworks_repo.get_progress_rows` 一个字不改），新增出参 schema 与 service（判档 + 排序），只改 `app/api/homeworks.py` 里 F1 那一个函数。与已上线的 G7 保持同口径但各自持有 service/schema，互不 import（理由见 spec 2.2）。

**Tech Stack:** Python 3.11 / Flask / SQLAlchemy 2.x / PostgreSQL / pydantic v2

**依据 spec:** `docs/superpowers/specs/2026-09-30-homeworks-list-api-design.md`

## Global Constraints

- **不新增测试框架。** 本仓库没有 `tests/`、`requirements.txt` 里也没有 pytest。验证一律用**对真接口跑的 curl**、`.venv/bin/python` 脚本与 psql。不要 `pip install pytest`。
- **Python 解释器用 `.venv/bin/python`**，先 `cd /Users/meiyazhao/Documents/lianshu/operaAI`。
- **`/api` 前缀只在 `app/api/__init__.py` 的 `url_prefix` 里写一次**，路由写相对路径 `/homeworks`。
- **响应一律用 `app/response.py` 的 `ok()`**，回 `200`。
- **权限是教师**：`@login_required` **加** `@teacher_required`，`login_required` 在外层（同 G7）。
- **`model_dump(mode="json")` 不能省**：出参里有 `date`（`deadline`），默认 dump 会按 RFC-822 序列化成 `"Sun, 02 Aug 2026 00:00:00 GMT"`。
- **不改 `app/repositories/homeworks_repo.py`**：`get_progress_rows` 是 F1 与 G7 的公共底层，F1 只消费不修改。
- **不改 `app/services/dashboard_service.py`**：G7 已上线并在跑班级看板，本次一行都不动。
- **不改 `schema.sql` / `app/models/*` / `app-d.py` / 任何 `.html`**，不引 Alembic，不加依赖。
- **只做 F1。** 同文件里其余 6 个空桩（`post_homeworks`、`homeworks_submit`、`homeworks_submissions`、`homeworks_detail`、`submissions_review`、`submissions_calibration`）**一个字都不要动**——包括 `:12-16` 那个挂错地址的 F2 桩（详见下方「已知地雷」）。
- **数据库时区是 `Asia/Shanghai`**。`_beijing_now()` 的写法从 `dashboard_service` 抄（`zoneinfo.ZoneInfo`），不要用 `datetime.now()`。
- **后端是 `debug=True` 跑的，Werkzeug reloader 会自动重载**。改完 `.py` 不用手工重启，但**要 curl 一次确认改动真生效**（reloader 遇到语法错会留在旧代码上继续服务，症状是「改了没反应」）。

### 已知地雷：`app/api/homeworks.py:12-16` 的地址挂错了

```python
@api_bp.route("/coach/annotations",methods=["POST"])   # ← 函数名是 post_homeworks
@login_required
@teacher_required
def post_homeworks():
    return ok()
```

函数名 `post_homeworks` 说明它本意是 **F2 `POST /api/homeworks`**，却挂到了 `POST /api/coach/annotations`。**本次不动它**（F2 单独立项），但下次实现 F2 时不要照着这个地址抄。已登记进 DOC_ISSUES 第 34 条。

### 当前真库基线（2026-09-30 实测，**验证时的对照基准**）

```
homeworks：3 行
 id |  title                       | demo_id |  deadline  | status | teacher_id
 12 | 《穆桂英挂帅》· 辕门外三声炮 |   16    | 2026-08-02 | open   |     2
 13 | 《贵妃醉酒》· 海岛冰轮初转腾 |   17    | 2026-08-05 | open   |     2
 14 | 《霸王别姬》· 看大王在帐中   |   18    | 2026-07-28 | closed |     2

submissions：共 5 行，全部挂在 12 号上（学生 48/50/52/53/55，状态全为 ai_scored）
在册学生（分母）：9 人
```

**期望的接口输出（顺序 12 → 13 → 14）：**

| id | submitted_count | total | pending_review_count | status |
|---|---|---|---|---|
| 12 | 5 | 9 | 5 | `grading` |
| 13 | 0 | 9 | 0 | `closed` |
| 14 | 0 | 9 | 0 | `closed` |

对不上就是实现有问题。

- **分母 9 不是 10**：`users` 里 `role='student'` 有 10 行、`students` 也有 10 行，但 `students.id=1` 挂的是 teacher01（`user_id=2`，role 非 student），而 `users.id=4` 的李四在 `students` 里没有行。`get_student_roster` 两头各掉一个，得 9（既有口径不一致，DOC_ISSUES 第 24 条已登记）。
- **12 号是 `grading` 而不是 `closed`**：三份作业截止日全过了，但 13/14 号零提交（`pending=0`），够不上 grading 判据。这不是 bug，是 G7 定下的「批改中优先于已截止」。
- 账号 `teacher01` / `stu001`，密码 `xiyun@2026`。登录：`POST /api/auth/login`，body `{"username":"...","password":"..."}`。

### 验证数据的清理纪律

本轮**不需要往库里插任何行**（F1 是纯读接口，现有 3 行作业 + 5 行提交足够覆盖 grading/closed 两档）。若为测边界改了某行的值（如把 `deadline` 置 NULL），**只能按抓到的 id 改回原值**：

- 绝不 `DELETE FROM submissions;` / `DELETE FROM homeworks;`——表里有真数据，不可恢复
- 绝不 `UPDATE ... WHERE title LIKE ...` 这种按别的列批量改
- 每轮边界测完，`SELECT id,deadline,status FROM homeworks ORDER BY id;` 必须回到上面基线表的样子

---

## Task 1: 出参 schema——`app/schemas/homework.py`

**Files:**
- Create: `app/schemas/homework.py`

**Interfaces:**
- Consumes: 无（纯 pydantic 模型）
- Produces:
  - `HomeworkListItem`（字段见下）
  - `HomeworkListResponse(homeworks: list[HomeworkListItem])`

- [ ] **Step 1: 写文件**

```python
from datetime import date

from pydantic import BaseModel, ConfigDict


class HomeworkListItem(BaseModel):
    """作业列表的一行（功能 4.1）。

    文档（《1-PRD》4.1、《3-功能清单》4.1、《5-接口清单》F1）的全部描述是
    「作业列表展示 — 进度/截止/提交人数」，**没有定义状态有哪些档、怎么判、
    分母放哪、怎么排序**。以下口径是本次实现定死的，与看板 G7
    （`app/schemas/dashboard.py::HomeworkProgressItem`）**逐字同源**——同一份数据
    在两条接口上必须是同一个档位，否则教师会在看板和作业页看到两个状态：

    - grading 批改中：有提交且存在未终审的提交（`submissions.status != 'reviewed'`）。
      优先级最高——截止没截止都要批；
    - closed 已截止：`homeworks.status == 'closed'` **或**截止日已过；
      截止当天算最后一天，仍可提交，不判已过；
    - ongoing 进行中：其余。

    **与 G7 的差别只有分母的位置**：G7 把分母放在响应级的一个 `student_count`，
    这里放在**每行**（`total`）。两个理由——(1) 页面每行就要渲染 `5/9` 与
    `submitted/total*100` 的进度条，行内拿到自己的分母最直接；(2) `homeworks`
    表目前没有班级/名单字段，所有作业共用同一个分母，但真实教学里作业是按班级
    布置的（`DOC_ISSUES.md` 第 25 条第 2 点），一旦补上班级维度每份作业的分母就会
    真的不同——那时响应级的一个数立刻作废，行内的不用改。所以这里**不再另给**
    响应级 `student_count`：那是同一个数字的第二个来源，漂移了就是线上事故。
    """

    model_config = ConfigDict(from_attributes=True)
    homework_id: int
    title: str
    deadline: date | None                 # 档案没填为 None，页面不显示截止
    demo_title: str | None                # 曲目名；作业没挂曲目（demo_id 为 NULL）为 None
    demo_role: str | None                 # 行当（青衣…）
    demo_banshi: str | None               # 板式（西皮流水…）
    submitted_count: int                  # 已提交**人数**（按学生去重）
    total: int                            # 分母：应提交人数（在册学生数）
    progress: float                       # submitted_count / total，0-1；total 为 0 时给 0
    pending_review_count: int             # 待批（未终审）条数，为 0 说明不用批
    status: str                           # grading / ongoing / closed


class HomeworkListResponse(BaseModel):
    """作业列表（功能 4.1）。

    不过滤、不截断、不分页：返回**全部**作业，由页面自己决定展示几条。
    库里没有作业时 `homeworks` 是 `[]`，**不是 404**。
    """

    model_config = ConfigDict(from_attributes=True)
    homeworks: list[HomeworkListItem]
```

- [ ] **Step 2: 确认文件能被导入**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
.venv/bin/python -c "from app.schemas.homework import HomeworkListResponse; print(HomeworkListResponse(homeworks=[]).model_dump(mode='json'))"
```

预期输出：`{'homeworks': []}`

**注意**：`app/schemas/__init__.py` 只有一句文档字符串、不做出参导出（各 service 一律 `from app.schemas.xxx import ...` 直取模块），**不要**去动它。

---

## Task 2: 服务层——`app/services/homework_service.py`

**Files:**
- Create: `app/services/homework_service.py`

**Interfaces:**
- Consumes: `homeworks_repo.get_progress_rows(db, student_ids)`（已有，**不改**）、`user_repo.get_student_roster(db)`（已有）、`app.schemas.homework.HomeworkListItem` / `HomeworkListResponse`（Task 1）
- Produces: `list_homeworks(db: Session) -> HomeworkListResponse`

- [ ] **Step 1: 写文件**

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.repositories import homeworks_repo, user_repo
from app.schemas.homework import HomeworkListItem, HomeworkListResponse

# 北京日期。容器里 PostgreSQL 的时区是 Asia/Shanghai，但这里判的是**今天的日期**，
# 与库无关——用 datetime.now() 会拿到宿主机本地时区，跨机器跑出不同结果。
# 与 dashboard_service._beijing_now 同一份实现（那边是私有函数，不跨模块 import）。
_BEIJING = ZoneInfo("Asia/Shanghai")

# 判档与排序的口径**与看板 G7 逐字同源**（app/services/dashboard_service.py:536
# 的 homework_progress）。同一份作业在两条接口上必须是同一个档位与同一个顺序，
# 否则教师会在看板和作业页看到两个状态。改动这里时那边要一起改。
_STATUS_ORDER = {"grading": 0, "ongoing": 1, "closed": 2}


def _beijing_now() -> datetime:
    return datetime.now(_BEIJING)


def _status_of(hw, pending: int, today) -> str:
    """三档判定，判据见 HomeworkListItem 的注释。

    `pending`（待批条数）不为 0 时**优先判 grading**——截止没截止都要批，
    这是唯一需要教师动手的一档，漏看会让学生一直拿不到成绩。
    """
    if pending:
        return "grading"
    if hw.status == "closed" or (hw.deadline is not None and hw.deadline < today):
        return "closed"
    return "ongoing"


def _sort_key(it: HomeworkListItem):
    """待办优先：grading → ongoing → closed；同档按截止日**降序**（最近的在前），
    没填截止日的沉底，次键 id 降序让同一天截止的几份顺序稳定。

    与仓储层 `order_by(deadline desc nulls_last, id desc)` 同一方向，两层不打架。
    """
    return (
        _STATUS_ORDER[it.status],
        it.deadline is None,
        -(it.deadline.toordinal() if it.deadline else 0),
        -it.homework_id,
    )


def list_homeworks(db: Session) -> HomeworkListResponse:
    """教师端作业列表（功能 4.1）：每份作业的提交人数、截止日与状态。

    排序与判档口径见模块顶部常量区的注释。分母是**在册学生数**，见
    HomeworkListItem 的文档字符串（为什么放在行内而不是响应级）。
    """
    student_ids = [row[0] for row in user_repo.get_student_roster(db)]
    today = _beijing_now().date()
    # 在册 0 人时 total 给 0 而不是让 ZeroDivisionError 冒成 500，同 G7。
    # 这里只是避免除零，**不替调用方把 0 人粉饰成 1 人**——出参里的 total 仍是真实的 0。
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
```

- [ ] **Step 2: 直连库跑一遍 service，对照基线**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
.venv/bin/python -c "
from app.db import session_scope
from app.services import homework_service
with session_scope() as s:
    r = homework_service.list_homeworks(s)
    print(r.model_dump(mode='json'))
"
```

预期：三行，顺序 **12 / 13 / 14**，且

- 12 号：`submitted_count=5, total=9, pending_review_count=5, status='grading'`
- 13 号：`0, 9, 0, 'closed'`
- 14 号：`0, 9, 0, 'closed'`

**数字对不上就停下来查，不要继续。** 常见偏差与成因：

| 症状 | 成因 |
|---|---|
| `total=10` | 名单用了 `users` 而不是 `students` join（见基线说明，正确值是 9） |
| 13/14 号判成 `grading` | `pending` 用了 `count(*)` 或没做 `status IS NULL OR != 'reviewed'` 的兜底 |
| 顺序是 13/14/12 | 排序键漏了 `_STATUS_ORDER`，只按截止日排了 |
| `deadline` 是 `"Sun, 02 Aug 2026 00:00:00 GMT"` | 忘了 `mode="json"`（这只在 Task 3 的 HTTP 层才会暴露） |

---

## Task 3: 路由层——把 F1 空桩换成真实现

**Files:**
- Modify: `app/api/homeworks.py`（**只改 `:6-10`**，其余 6 个函数不动）

**Interfaces:**
- Consumes: `homework_service.list_homeworks`（Task 2）、`app.db.get_db`
- Produces: `GET /api/homeworks` → `{"code":0,"message":"ok","data":{"homeworks":[...]}}`

- [ ] **Step 1: 改 import 与 F1 函数**

文件顶部 import 改成（新增三行，其余不动）：

```python
from app.api import api_bp
from app.common.decorators import login_required, teacher_required, student_required
from app.db import get_db
from app.response import ok
from app.services import homework_service
```

把 `:6-10` 的桩：

```python
@api_bp.route("/homeworks",methods=["GET"])
@login_required
@teacher_required
def get_homeworks():
    return ok()
```

改成：

```python
@api_bp.route("/homeworks",methods=["GET"])
@login_required
@teacher_required
def get_homeworks():
    # mode="json"：出参里有 date（deadline）。默认 model_dump() 会给 Flask 一个
    # date 对象，而它按 RFC-822 序列化成 "Sun, 02 Aug 2026 00:00:00 GMT"；
    # mode="json" 出的是 ISO-8601（"2026-08-02"）。同 dashboard_homework_progress。
    return ok(homework_service.list_homeworks(get_db()).model_dump(mode="json"))
```

**其余 6 个桩（含 `:12-16` 挂错地址的 F2 桩）保持原样，一个字都不要动。**

- [ ] **Step 2: 确认后端在跑**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8877/login.html
```

- 回 `200` → 后端已在跑，跳到 Step 3
- 回 `000` / 连接被拒 → 起后端（**不需要 Celery worker**，F1 不碰队列）：
  ```bash
  cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python app-d.py
  ```
  起完再 curl 一次确认。`.` 前的 `.venv/bin/python` 不能省——PATH 上的 `python3` 是 pyenv 3.12，没装本项目依赖。

- [ ] **Step 3: 三种身份打接口**

```bash
cd /tmp
# 1) 未登录 → 401
curl -s -w '\nHTTP %{http_code}\n' http://127.0.0.1:8877/api/homeworks

# 2) 教师 → 200 + 全量列表
curl -s -c /tmp/f1_teacher.jar -X POST http://127.0.0.1:8877/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"teacher01","password":"xiyun@2026"}'
curl -s -b /tmp/f1_teacher.jar -w '\nHTTP %{http_code}\n' http://127.0.0.1:8877/api/homeworks

# 3) 学生 → 403
curl -s -c /tmp/f1_stu.jar -X POST http://127.0.0.1:8877/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"stu001","password":"xiyun@2026"}'
curl -s -b /tmp/f1_stu.jar -w '\nHTTP %{http_code}\n' http://127.0.0.1:8877/api/homeworks
```

预期：

| 请求 | HTTP | body |
|---|---|---|
| 未登录 | `401` | `{"code":401,...}` |
| student | `403` | `{"code":403,...}` |
| teacher | `200` | `{"code":0,"message":"ok","data":{"homeworks":[...3 行...]}}` |

教师那次的 `data.homeworks` 必须与 Task 2 Step 2 的输出**逐字段一致**，且 `deadline` 是 `"2026-08-02"` 这样的 ISO 串。

- [ ] **Step 4: 边界——`deadline` 为 NULL 的作业沉底且不判已截止**

先抓 id 与当前值（**这一行的 id 后面清理时要按它改回**）：

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -c \
  "UPDATE homeworks SET deadline = NULL WHERE id = 13 RETURNING id, deadline, status;"
```

再 curl 一次（带教师 cookie），预期 13 号：

- `deadline: null`（页面据此不显示截止日）
- `status` 从 `closed` 变成 **`ongoing`**——截止日缺失就判不了「已过」，不猜（`hw.status` 是 `'open'`，两条判据都不成立）
- 顺序仍是 **12 → 13 → 14**：`_STATUS_ORDER` 是 `grading`(0) → `ongoing`(1) → `closed`(2)，12 号 `grading` 在前，13 号 `ongoing` 次之，14 号 `closed` 在后

> **13 号若掉到 14 号后面**，说明排序键漏了 `_STATUS_ORDER`、变成只按截止日排——`deadline is None` 那一位把它压到底了。这正是这条边界要抓的东西。

改回：

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -c \
  "UPDATE homeworks SET deadline = '2026-08-05' WHERE id = 13 RETURNING id, deadline;"
```

- [ ] **Step 5: 回基线**

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -c \
  "SELECT id, title, deadline, status FROM homeworks ORDER BY id;" \
  -c "SELECT count(*) FROM submissions;"
```

预期：homeworks 三行与基线表逐字一致（13 号 `deadline` 回到 `2026-08-05`），`submissions` 仍是 **5**。

**不是就停下来查，不要继续。** 本轮全程不该新增或删除任何行。

- [ ] **Step 6: 跑一致性闸门**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python scripts/check_db.py
```

本次不动 schema 与模型，预期与改动前**完全一致**（注意：该脚本在干净 main 上本来就有 `demo_versions` 表 + `teacher_demos` 三列的既有漂移，**别当成自己改坏了**）。

---

## 完成标准

- [ ] `GET /api/homeworks` 返回 3 行，字段与 spec 第 4.2 节一致
- [ ] 教师 200 / 学生 403 / 未登录 401
- [ ] 库回到基线（3 行作业、5 行提交），`check_db.py` 无新增差异
- [ ] `app/api/homeworks.py` 其余 6 个桩未被触碰
- [ ] `DOC_ISSUES.md` 新增第 34 条（F1 与 G7 重叠、自拟口径、待确认项、F2 桩挂错地址）

## 前端接入（同日追加，见 spec 2.3.1）

接口验证通过后追加，改动只在 `homework.html`，两个 `<script>` 块都要动：

- [ ] 首段 `<script>`：加 `API_BASE = ""`（**空串，不能改成跨源地址**）、`currentUser`、`esc()`、`HW_STATUS` / `HW_STATUS_TEXT`、`fetchHomeworks()`；`renderHwList(items)` 改为吃接口数组；新增 `renderHwSummary(items)`
- [ ] `:497` 的 `3项进行中` 换成 `<span id="hwSummary">加载中…</span>`
- [ ] **删掉**首段 `<script>` 末尾的同步 `renderHwList()`（那时 `currentUser` 还是 null，教师会被误判成学生）
- [ ] 第二段 `<script>`：`currentUser = user;` 之后调 `fetchHomeworks()`
- [ ] `HOMEWORKS` mock **保留**（`selectSubmission` 仍读 `HOMEWORKS[0].title`），加注释说明等 F4 落地一并删
- [ ] 语法：抽出两段内联脚本跑 `node --check`
- [ ] 浏览器（走 **nginx 80 端口**，不是直连 8877——`/static/` 由 nginx 直供，直连 8877 会看到 echarts 的假 404）：
  - 教师 → 3 张卡与 curl 结果逐字一致，`#hwSummary` 显示「暂无进行中」，无 console error
  - 学生 → 「作业列表仅教师可见」，且 `network` 里**零次** `/api/homeworks` 请求（只发 `/api/auth/me`）
  - 纯 JS 验三个分支：`renderHwSummary` 计数、`renderHwList` 的 null 占位、空列表文案
  - 转义：塞一个 `<img src=x onerror=alert(1)>` 当 title，页面里 `querySelectorAll('#hwList img').length` 必须是 **0**

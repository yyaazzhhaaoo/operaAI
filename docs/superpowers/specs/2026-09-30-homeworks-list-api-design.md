# 作业列表接口（F1 `GET /api/homeworks`）实现设计

日期：2026-09-30 ｜ 状态：已评审待实现 ｜ 关联：《5-接口清单》2.6 节 F1、《3-功能清单》4.1；`DOC_ISSUES.md` 第 25 条（同源口径）

## 1. 背景与目标

模块 4「作业布置与批改」的 F1–F7 在 `app/api/homeworks.py` 里目前**全是空桩**（`return ok()` / `return ok(id)`），没有任何一条走过真实查询。本轮只做 **F1**——作业列表，对应 `homework.html` 左侧的「作业列表」卡片。

**目标**：

1. `GET /api/homeworks` 返回作业列表，每行含标题 / 截止日 / 曲目 / 提交人数 / 进度 / 状态
2. 字段足以渲染 `homework.html:683-703` 的 `renderHwList`，不必再要第二个请求
3. 把 `app/api/homeworks.py:6-10` 的 `ok()` 空桩换成真实现

**非目标（明确不做）**：

- **不做前端**。`homework.html` 的作业列表本轮仍读它自己的 `HOMEWORKS` mock（见 2.3），本次只交付接口
- **不做 F2–F7**（布置作业 / 提交 / 待批改列表 / 批改详情 / 终审 / 校准全是空桩，各自单独立项）
- **不做分页**（同 C1–C4、G7，仓库无先例；当前库只有 3 份作业）
- **不做筛选、不做排序参数**（文档没给任何入参，见 2.1）
- 不改 `schema.sql` / `app/models/*`，不引 Alembic，不引新依赖，不动任何 `.html`
- **不改 `dashboard_service.homework_progress`**（G7 已上线并在跑班级看板，本次一行都不动）

## 2. 文档给的 vs 库里有的

### 2.1 文档只有一行

| 编号 | 接口 | 权限 | 说明 |
|---|---|---|---|
| F1 | `GET /api/homeworks` | **教师** | 列表：进度/截止/提交人数（功能 4.1） |

《3-功能清单》4.1 的全文是「作业列表展示 ｜ 进度/截止/提交人数」。**响应体、排序、分页、筛选参数一概没有**——与第 25（G7）、26（C1）、27（C2/C3）、28（C4）、30（C5）、31（C6）、32（C7）条同源：接口清单的表格只给了一句「说明」。

「进度/截止/提交人数」这九个字是**唯一的出参依据**，本次三个字段就是按它拆的。

### 2.2 与 G7 的重叠：本次最重要的判断

`GET /api/dashboard/homework-progress`（G7，功能 5.9）**已经实现了同一份查询**：

| | G7（已上线） | F1（本次） |
|---|---|---|
| 底层查询 | `homeworks_repo.get_progress_rows(db, student_ids)` | **同一个函数，不改** |
| 算出的东西 | 提交人数（按学生去重）、待批条数、截止日、曲目 | 同 |
| 状态档位 | `grading` / `ongoing` / `closed` | **同口径，必须一致** |
| 排序 | 待办优先（grading → ongoing → closed） | **同** |
| 分母位置 | 响应级 `student_count` 一个 | **每行 `total`**（差异所在，见 3.2） |
| 出参 schema | `app/schemas/dashboard.py::HomeworkProgressItem` | 新建 `app/schemas/homework.py::HomeworkListItem` |

**两条接口算的是同一件事，出参却各写一套**——这是文档层面的重复（功能 4.1 与 5.9 描述几乎一样），已作为 DOC_ISSUES 第 34 条的待确认项登记，而不是自己删掉一条。

代码上按「**独立 service + 共用 repo**」落地：`homeworks_repo.get_progress_rows` 是两者唯一的公共底层，不动；两个 feature 各自持有自己的 service 与 schema，互不 import。代价是状态判定那约 10 行在两个 service 里各有一份——这处重复是**有意的**，理由见表下方。

> **为什么不在两端之间抽一个公共 service**：抽了就要改 `dashboard_service`（已上线、有页面在跑），回归面白送；而两处的差异（分母位置）是真实的语义差异，不是纯粹的复制粘贴。真要让口径单点维护，应该在文档层先把 4.1 与 5.9 合并成一条接口，那是 DOC_ISSUES 第 34 条要问的事。

### 2.3 前端要什么

`homework.html:606-610` 的 mock：

```js
{ id: "h01", title: "…辕门外三声炮", deadline: "2026-08-02",
  demo: "王老师标准版", submitted: 18, total: 24, status: "grading" }
```

`renderHwList`（`:683-703`）用到的字段与渲染方式：

| mock 字段 | 渲染处 | 本接口对应 |
|---|---|---|
| `title` | 卡片标题 | `title` |
| `status` | `class="status ${status}"` + 文案映射 `grading→批改中 / ongoing→进行中 / closed→已截止`（`:685`） | `status`，**取值必须逐字对齐** |
| `deadline` | `📅 ${deadline}` 原样打印 | `deadline`，ISO-8601 字符串 |
| `demo` | `🎵 ${demo}` | `demo_title` + `demo_role` + `demo_banshi`（DB 里拆成了三列，见 3.4） |
| `submitted` / `total` | `👥 ${submitted}/${total}` 与 `pct = round(submitted/total*100)` 进度条 | `submitted_count` / `total` |

**mock 的排序正好是 `grading → ongoing → closed`**（h01/h02/h03），与本接口采用的「待办优先」排序一致（见 3.3）——说明这套排序不是本次硬套的，页面 mock 本来就是这个顺序。

「作业列表」卡片标题右侧原本写死 `3项进行中`（`:497`）。接口不返回聚合计数，已改为由页面自己数 `status === "ongoing"` 的条数（见下方「前端落地」）。

### 2.3.1 前端落地（2026-09-30 同日）

前端接入与接口同批交付，改动只在 `homework.html`：

| 位置 | 改动 |
|---|---|
| `:497` | `3项进行中` → `<span id="hwSummary">加载中…</span>`，由 `renderHwSummary` 填「N项进行中」/「暂无进行中」 |
| `:683-703` | `renderHwList` 从读 `HOMEWORKS` mock 改为接收接口返回的数组；新增 `esc()` 转义（标题来自数据库，走 `innerHTML` 拼接有注入风险） |
| 数据层 | 新增 `API_BASE = ""`、`currentUser`、`fetchHomeworks()`、`HW_STATUS` / `HW_STATUS_TEXT` |
| 第二段 `<script>` | `currentUser = user` 之后调 `fetchHomeworks()` |
| 首段 `<script>` 末尾 | **删掉**同步的 `renderHwList()` 调用——那时 `currentUser` 还是 null |

两个必须照抄 `demo_library.html` 的点：

1. **`API_BASE` 是空串**（同源，走 nginx 的 `/api` 代理）。改成 `location.host + ':8877'` 就是跨源请求，跨源 fetch 默认不带 Cookie，后端 `login_required` 只看到空 session 回 401。
2. **拉取必须在 `currentUser` 就绪之后**。首段 `<script>` 在页面加载时同步执行，那时 `currentUser` 是 null，教师会被误判成学生、列表永不加载。

**空值显示**：`deadline` / `demo_*` 为 null 时显示占位文案「未设截止」「未挂曲目」，而不是整格消失——两种空值都是真实存在的状态（两列在 DDL 上均可空），明说比默默消失好。

**`HOMEWORKS` mock 保留**：`selectSubmission`（`:737`）还在读 `HOMEWORKS[0].title` 填批改详情页的标题，而「待批改提交」那一块仍是 mock（F4/F5 未实现）。等 F4 落地、`SUBMISSIONS` 一起换掉时，两个常量一并删除。已在常量定义处写了这条注释。

### 2.4 真库基线（2026-09-30 实测）

```
homeworks：3 行
 id |  title                       | demo_id |  deadline  | status | teacher_id
 12 | 《穆桂英挂帅》· 辕门外三声炮 |   16    | 2026-08-02 | open   |     2
 13 | 《贵妃醉酒》· 海岛冰轮初转腾 |   17    | 2026-08-05 | open   |     2
 14 | 《霸王别姬》· 看大王在帐中   |   18    | 2026-07-28 | closed |     2

submissions：**共 5 行，全部挂在 12 号上**（学生 48/50/52/53/55，状态全为 ai_scored）；
              13、14 号**一行都没有**

在册学生（分母）：**9 人**，不是 10
```

两条要注意的地方：

1. **分母是 9 不是 10**。`users` 里 `role='student'` 有 10 行、`students` 表也有 10 行，但两边对不上：`students.id=1` 挂的 `user_id=2` 是 **teacher01**（role 不是 student），而 `users.id=4` 的**李四**在 `students` 表里**没有行**。`get_student_roster` 是从 `students` 出发 join `users` 且要求 `role='student'`，所以两头各掉一个，得 9。这是既有的口径不一致（DOC_ISSUES 第 24 条已登记，本次不改）。
2. **12 号会判成 `grading`，13/14 号判成 `closed`**。今天 2026-09-30，三份作业的截止日**全部已过**，但 13/14 号一行提交都没有（`pending=0`），够不上 `grading` 的判据，落到「已截止」；12 号有 5 条未终审的提交，`grading` 优先。最终顺序 12 → 13 → 14。

> 上面这张表是**验证时的对照基准**：接口跑出来必须是 12 号 `5/9 grading`、13 号 `0/9 closed`、14 号 `0/9 closed`，顺序一致。对不上就是实现有问题。

## 3. 自拟口径（文档未定义项）

### 3.1 状态三档的判定

**直接沿用 G7 的口径**（`HomeworkProgressItem` 的注释、DOC_ISSUES 第 25 条），一个字不改：

| 档位 | 判据 |
|---|---|
| `grading` 批改中 | 有提交**且**存在未终审的提交（`submissions.status IS NULL OR != 'reviewed'`）。**优先级最高**——截止没截止都要批 |
| `closed` 已截止 | `homeworks.status = 'closed'` **或**截止日已过（截止当天仍算进行中） |
| `ongoing` 进行中 | 其余 |

同一份数据在两条接口上必须是同一个档位，否则教师会在看板和作业页看到两个不同的状态，所以这里没有自拟空间。

### 3.2 分母：每行一个 `total`，不放响应级

G7 把分母放在响应级（一个 `student_count`），F1 放在**每行**（`total`）。理由：

1. **页面就是这么用的**：`renderHwList` 每行渲染 `${submitted}/${total}` 与 `submitted/total*100`，每行拿到自己的分母最直接。
2. **为「按班级布置作业」留位**：`homeworks` 表目前只有 `teacher_id`，没有班级/名单字段，所以今天所有作业的分母都是同一个「全体在册学生数」。但真实教学里作业是按班级布置的（DOC_ISSUES 第 25 条第 2 点已登记），一旦补上班级维度，**每份作业的分母就真的会不同**——那时响应级的一个数立刻作废，行内的不用改。
3. 不再另给一份响应级 `student_count`：那是同一个数字的第二个来源，两处一旦漂移就是线上事故。

### 3.3 排序：待办优先

沿用 G7：`grading → ongoing → closed`，**同档按截止日降序**（最近的在前），无截止日的沉底，次键 `id` 降序保证稳定。与仓储层 `order_by(deadline desc nulls_last, id desc)` 同一方向，两层不打架。

### 3.4 曲目：拆三列返回，不合成一个「版本名」

mock 里 `demo` 是一个字符串「王老师标准版」，但**库里没有这个字段**：`teacher_demos` 的列是 `title` / `role` / `banshi`（`app/models/demo.py:16-24`），「版本名」是演示页自拟的概念。

本次按 DB 的真实结构返回三列（`demo_title` / `demo_role` / `demo_banshi`，与 G7 逐字一致），**不替前端把它们拼成一个字符串**——拼接是展示层的事，且 `demo_id` 允许为 NULL（作业可以不挂曲目），三列都可以是 `null` 这件事比一个空字符串更好判。

**2026-09-30 前端接入时定**：`🎵` 一格显示 **`demo_role · demo_banshi`**（如「青衣 · 西皮流水」）。理由是种子数据里 `homeworks.title` 与 `demo_title` 逐字相同，再显示曲目名会与卡片标题重复；行当与板式是新增信息，且短。三列都照旧返回，页面只挑了后两列——换显示口径不需要改接口。

### 3.5 权限与隔离

- `login_required` + `teacher_required`（对齐接口清单「教师」；装饰器顺序同 G7 与其它教师接口）
- **不按 `teacher_id` 过滤**：`homeworks.teacher_id` 存在，但《6-登录与数据隔离方案》的三条规则里**没有**「教师只看自己的作业」这一条（只有学生按 `student_id` 强制过滤）。G7 同样不过滤，两条接口口径一致。已列为待确认项（第 34 条）。
- 学生访问 → 403（`teacher_required` 既有行为）；未登录 → 401。

### 3.6 序列化

`model_dump(mode="json")`——响应里有 `date`（`deadline`）。默认 `model_dump()` 会给 Flask 一个 `date` 对象，按 RFC-822 序列化成 `"Sun, 02 Aug 2026 00:00:00 GMT"`；`mode="json"` 出的是 ISO-8601 `"2026-08-02"`。同 G7 与 `dashboard_students`，三处注释都写过这个坑。

### 3.7 边界

| 场景 | 行为 |
|---|---|
| 库里没有作业 | `homeworks: []`，**不是** 404 |
| 在册学生数为 0 | `total` 全为 0，`progress` 全为 0（分母取 `len(student_ids) or 1` 兜住 `ZeroDivisionError`，同 G7） |
| `demo_id` 为 NULL | 三个 demo 字段全为 `null` |
| `deadline` 为 NULL | `deadline: null`，排序沉底，不判已截止（判不了就按未截止，同 G7） |
| 同一学生重复提交 | 提交人数按 `count(distinct student_id)` 去重，不会出现「6/5 人已提交」 |

## 4. 实现设计

### 4.1 分层与文件清单

| 文件 | 动作 |
|---|---|
| `app/repositories/homeworks_repo.py` | **不动**。`get_progress_rows` 已是 F1 与 G7 的公共底层 |
| `app/schemas/homework.py` | **新增**：`HomeworkListItem` / `HomeworkListResponse` |
| `app/services/homework_service.py` | **新增**：`list_homeworks(db) -> HomeworkListResponse` |
| `app/api/homeworks.py` | **改**：`GET /homeworks` 换成真实现；其余 6 个空桩不动 |

`app/schemas/__init__.py` 与 `app/services/__init__.py` 都只有一句文档字符串、不做出参导出（各 service 一律 `from app.schemas.xxx import ...` 直取模块），所以**两个 `__init__.py` 都不用动**。

**注意**：`app/api/homeworks.py:12-16` 那个桩函数名是 `post_homeworks`，但挂的路由是 `POST /api/coach/annotations`——**F2 的桩挂错了地址**。它在本次改动范围之外（F2 单独立项），本次**保持原样不动**，一并登记进 DOC_ISSUES 第 34 条，避免下次实现 F2 时照着这个错地址写。

### 4.2 schema（`app/schemas/homework.py`）

```python
class HomeworkListItem(BaseModel):
    homework_id: int
    title: str
    deadline: date | None
    demo_title: str | None
    demo_role: str | None
    demo_banshi: str | None
    submitted_count: int     # 已提交人数（按学生去重）
    total: int               # 分母：应提交人数
    progress: float          # submitted_count / total，0-1
    pending_review_count: int
    status: str              # grading / ongoing / closed
```

```python
class HomeworkListResponse(BaseModel):
    homeworks: list[HomeworkListItem]
```

### 4.3 service（`app/services/homework_service.py`）

`list_homeworks(db)`：取在册名单 → `get_progress_rows` → 判档 → 排序 → 返回。判档与排序各抽一个 `_status_of` / `_sort_key` 私有函数，与 `dashboard_service` 里那两份同构并互相注明「与 G7 同口径，改动需两处同步」。

### 4.4 api（`app/api/homeworks.py`）

```python
@api_bp.route("/homeworks", methods=["GET"])
@login_required
@teacher_required
def get_homeworks():
    return ok(homework_service.list_homeworks(get_db()).model_dump(mode="json"))
```

## 5. 验证

无测试框架（仓库无 `tests/`，`requirements.txt` 无 pytest），按既有做法：

1. **起后端**：`.venv/bin/python app-d.py`（8877），**不需要 Celery worker**（F1 不碰队列）
2. **临时脚本** `/tmp/check_f1.py` 用 `session_scope()` 直连库，独立算一遍「每份作业的提交人数 / 待批 / 应判档位」，与接口返回逐行对比
3. **curl 三种身份**：
   - 未登录 → 401
   - `stu001` → 403
   - `teacher01` → 200 + 全量列表
4. **边界**：临时把某作业的 `deadline` 置 NULL / 把 `submissions.status` 改成 `reviewed` 观察档位翻转，**按抓到的 id 改回**（清理纪律：绝不整表删改）
5. **`python scripts/check_db.py`**：本次不动 schema 与模型，应保持既有状态（注意该脚本在干净 main 上本来就有 `demo_versions` 表的既有漂移，别当成改坏了）

## 6. 待文档方确认

1. **功能 4.1 与 5.9 是不是同一件事？** 两条接口（F1 / G7）算的是同一份数据，只有分母位置不同。若确认重复，应删掉一条；若确认不重复，请补上 F1 与 G7 各自的响应契约差异。
2. **教师是否只看自己布置的作业？** 当前不过滤（`teacher_id` 列存在但未用于隔离，《6-登录与数据隔离方案》也没这条规则）。若要隔离，G7 需一起改。
3. **`homework.html` 的 `🎵` 一格显示什么？** 库里拆成「曲目名 / 行当 / 板式」三列，mock 里却是一个「王老师标准版」。是否需要 `teacher_demos` 补一个版本名字段？
4. **作业列表是否需要分页或按状态/曲目筛选？** 功能 4.1 只写了「列表」，当前不分页不筛选（同 C1–C4）。

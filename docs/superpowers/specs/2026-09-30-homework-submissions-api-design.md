# F4 `GET /api/homeworks/<id>/submissions` 设计（待批改提交列表）

日期：2026-09-30
接口编号：《5-接口清单》F4
功能编号：《3-功能清单》4.3「待批改提交列表 — AI 初评待终审」
对应页面：`homework.html` → 右侧「待批改提交」卡片（`#submitList`）与其上的 `#hwSummary` 汇总
前置：F1 `GET /api/homeworks` 已实现（见 `2026-09-30-homeworks-list-api-design.md`）

---

## 1 背景、目标与非目标

### 1.1 目标

给教师端「待批改提交」卡片提供真实数据：某一份作业下**还没有被教师终审**的那些提交，含学生、AI 分数、提交时间、AI 归因标签。

### 1.2 非目标

- **不做批改动作**。评分/评语/校准标签的落库是 F5 `GET /api/homeworks/<id>/detail`、F6 `POST /api/submissions/<id>/review`、F7 `POST /api/submissions/<id>/calibration`。
- **不返回批改详情页要的明细**（逐字偏差 `lyrics`、BKT 前后对比 `bkt_before/bkt_after`、`calib`、`comment`）。那些是 F5 的内容；本接口只出**列表卡片**渲染所需的字段。
- **不分页**。见 3.8。
- **本次不含前端接入**。按 F1 的节奏，先出后台接口（用户明确「先实现后台接口」）。前端接入时 `SUBMISSIONS` 与 `HOMEWORKS` 两个 mock 常量才能删，见 3.9。

---

## 2 文档真源与现状

### 2.1 文档只给了一行

《1-PRD》《3-功能清单》4.3、《5-接口清单》F4 的全部描述是：

> 待批改提交列表（AI 初评待终审）

**没有定义**：什么样算「待批改」、有没有名单过滤、按什么排、标签从哪来、标签怎么分级、标签显示几个、单条提交返回哪些字段。以下口径全部是本次自拟，逐条列在 §3，并同步登记 `DOC_ISSUES.md` 第 35 条。

### 2.2 与 F1 的关系（口径必须对齐的地方）

F1 与 F4 共享「待批」这个词，但**算的是两件事**：

| | F1 `GET /api/homeworks`（列表） | F4 `GET /api/homeworks/<id>/submissions`（本接口） |
|---|---|---|
| 粒度 | 每份作业一行 | 每条提交一行 |
| 「待批」的用法 | 只出**条数** → 决定该作业是不是 `grading` 档 | 出**每条提交本身** |
| `status != 'reviewed'` 判定 | 有（`homeworks_repo.get_progress_rows` 的 `pending`） | 有（同一条口径，见 3.1） |
| 是否过滤在册名单 | **过滤**（分子分母同一份名单） | **不过滤**，见 3.2 |

**F1 的 `pending_review_count` 与本接口的 `len(submissions)` 应当相等**（同一份库、同一套判定下）。这是刻意留的一致性锚点：两处不一致就说明 `student_ids` 过滤或 NULL 兜底写岔了。验证时按这条对一遍（见 §5 步骤 4）。

两处判定写成同一段逻辑的复制（而非抽公共函数）的理由同 F1：一处是聚合成一个数、一处是取行本身，SQL 形状不同；抽出来只能抽「条件表达式」，那点收益抵不过多一层间接。**但两处的注释互相指认**（`homeworks_repo` 与本文件都写明「与另一处同口径」），改一处必须改另一处。

### 2.3 前端要什么

页面 `renderSubmitList()`（`homework.html:782`）对每条提交读这些字段：

| mock 字段（`SUBMISSIONS[i]`） | 用途 | 本接口出参 |
|---|---|---|
| `id` | `selectSubmission(id)` 的选中标记 `currentSubId` | `submission_id` |
| `student.avatar` | 卡片头像 | `student_avatar` |
| `student.name` | 卡片姓名 | `student_name` |
| `student.level` | mock 里有，卡片**没渲染**；详情页将来可能用 | `student_level` |
| `time` | 卡片副标题「提交时间」 | `submitted_at` |
| `tags[].text` / `tags[].cls` | 卡片底部两三个标签胶囊 | `tags[].label` / `tags[].severity` |
| `ai_score` | 卡片右侧分数 | `ai_score` |

另外 `selectSubmission` 目前用 `HOMEWORKS[0].title`（`homework.html:813`）填详情页标题，所以响应里带一个响应级的 `homework_title`，前端接入时不必再查一次列表（见 3.7）。

**mock 的 `tags` 与 `cdm` 是两份不同的标签**（`sub01` 的 `cdm` 是「气息支撑不足 / 拖腔时值偏短」，`tags` 却是「拖腔偏低 / 时值偏短」）。本接口只出**一份**，前端接入时 `tags` 由本接口给、`cdm` 等 F5。据此 `sub01` 的卡片文案会从「拖腔偏低」变成「气息支撑不足」，属于 mock 与真数据对齐时的正常变化，不是回归。

### 2.4 真库基线（验证时对照）

```
homeworks: 12(穆桂英挂帅, deadline 2026-08-02, open), 13, 14
submissions: 5 条，全部 homework_id=12、status='ai_scored'（均未终审）
             → hw12 待批 5 条；hw13/hw14 待批 0 条
```

5 条提交的 `ai_detail->'defects'` 中 `confidence > 0.7` 的条数：李小燕 2、刘思琪 **3**、周明轩 2、孙志远 2、赵雨桐 1。

注意刘思琪是 **3 个**——mock 里她只有 2 个标签。真数据的 `defects` 一共 4 条（0.85/0.76/0.71/0.52），砍掉 0.52 那条还剩 3 条。这印证了 3.6「不截断」的取舍：一旦截断到 2，卡片上少掉的正是 0.71 的「拖腔不足」，而它并不比 0.72 的「收尾偏急」（赵雨桐那条，会被显示）更不该出现。

在册学生 9 人（`students`⋈`users` 且 `role='student'`），提交的 5 人（48/50/52/53/55）**全部在名单内**。`students.id=2`（张三）的 `avatar` 是**空串不是 NULL**。

---

## 3 自拟口径

### 3.1 什么算「待批改」

`status IS NULL OR status != 'reviewed'`。

与 `homeworks_repo.get_progress_rows` 的 `pending` 逐字同源。**NULL 必须显式兜**：`submissions.status` 有 `server_default 'ai_scored'` 但**没有 NOT NULL**，而 SQL 里 `NULL != 'reviewed'` 求值为 NULL 而不是 true，只写 `!= 'reviewed'` 会把 status 为 NULL 的提交悄悄漏掉。

判定用的是 `'reviewed'` 这个字面量，与 F1 一致；`submissions.status` 是 `VARCHAR(10)` 没有枚举约束（`DOC_ISSUES.md` 第 9 条同类问题的兄弟），值域只有代码知道。

### 3.2 不过滤在册名单（与 F1 的刻意差异）

F4 **不做** `student_id IN (在册名单)` 过滤。

理由：F1 过滤是为了让**分子不超过分母**（`DOC_ISSUES.md` 第 24 条：`students` 表里有 teacher01 自己的行，不过滤会出「6/5 人已提交」）。F4 没有分母，过滤失去动机，反而会**藏掉真实存在的提交**——一条真提交若因为提交人不在名单里就不出现在待批列表里，教师永远批不到它，这是比「数目对不上」严重得多的事故。

当前库 5 条提交全部在名单内，两种写法结果相同；这条差异只在脏数据下才显形，所以写进这里备查。

副作用：脏数据下 F4 的条数会**大于** F1 的 `pending_review_count`。这是预期行为，不是 bug。

### 3.3 排序：最早提交在前（FIFO）

`submitted_at ASC, id ASC`。

- `submitted_at` **为 NULL 的排最后**（`nulls_last`）。NULL 说明入库时没写时间，不该插队到真实时间前面。
- `id ASC` 是**必要的兜底**，不是装饰：真库里 24/26/27 三条的 `submitted_at` 完全相同（都是 `2026-08-01 00:00:00`），只按时间排则这 3 条的相对顺序由 PG 的执行计划决定，同一次部署的两次请求都可能给出不同顺序，前端选中的 `currentSubId` 会在刷新后跳到别人身上。
- 与 F1 的「待办优先」排序**无关**：F1 排的是作业，这里排的是同一份作业下的提交，不存在「哪份更急」。

### 3.4 标签来源：`ai_detail->'defects'`

每条提交的 `ai_detail.defects` 是一个数组，元素形如：

```json
{"id":"d1","label":"气息支撑不足","status":"high","category":"气息",
 "evidence":"长音能量波动大…","features":{…},"confidence":0.82}
```

本接口只取 `label` 与 `status` 两个字段。`evidence`/`features`/`category` 是 F5 详情页的内容。

### 3.5 只取 `confidence > 0.7`，按置信度降序

页面自己声明的口径就是「只展示置信度 > 0.7 的标签」（`homework.html` 待批改卡片区）。**用严格大于**，0.7 本身不算。

排序按 `confidence` **降序**——`defects` 数组在库里**不是**按置信度排的（李小燕那条是 0.82 / 0.45 / 0.78），不重排的话卡片上第一个标签会是「归韵口型保持不足」这种 0.45 被滤掉之后、顺序看起来随机的组合。

### 3.6 不截断条数

不做 `[:N]`。理由见 2.4：真数据里刘思琪就有 3 条过线，截断到 2 会砍掉一条 0.71 的「拖腔不足」，而 0.72 的「收尾偏急」却在显示——同一量级的标签留下哪个纯看运气。

代价是卡片可能被撑高（mock 里只有 2 个标签、真标签还更长：「气息支撑不足」6 字 vs mock「拖腔偏低」4 字）。**这是前端接入时要一起看的**，届时若真的撑破布局，正确做法是前端 CSS 截断或折叠，而不是让后端悄悄丢数据。

### 3.7 响应级带 `homework_id` 与 `homework_title`

`homework_id` 是路径参数的**回显**（异步请求回来时确认是不是当前选中的那份作业，避免竞态）。

`homework_title` 是因为页面详情区现在要显示「这是哪份作业的提交」（mock 用 `HOMEWORKS[0].title` 硬编码，`homework.html:813`）。本来前端也能从 F1 的列表里查到，但那是又一次请求和一份额外的前端状态；这里一个字符串就够。

### 3.8 不分页，空列表返回 200 + `[]`

与 F1 同：一份作业的待批提交是教师一次批完的工作量（真库 5 条），分页的复杂度（`page`/`size`/`total` 三个参数与前端翻页状态）远超收益。真要分页是文档该先定的事。

作业存在但没有待批提交时返回 `200` + `submissions: []`，**不是 404**——「这份作业没有东西要批」是正常结果。

### 3.9 学生字段平铺，不做嵌套对象

`student_id` / `student_name` / `student_avatar` / `student_level`，与 F1 的 `demo_title` / `demo_role` / `demo_banshi` 前缀风格一致，同一个模块内保持一种风格。

mock 里 `student` 是嵌套对象，嵌套更好看但会引出「F5 要不要复用同一个 `StudentBrief` 模型」的跨接口耦合——现在各接口的 schema 是彼此独立的，不为一个四字段对象破例。

### 3.10 `ai_detail` 缺失或结构异常时 `tags: []`，不抛错

`ai_detail` 可空（列为 `JSONB` 无 NOT NULL），且它的结构由 AI 侧写入、不受本服务约束。取值路径上一律防御：`ai_detail` 为 None → `[]`；`defects` 不是 list → `[]`；元素不是 dict → 跳过该元素；`confidence` 不是数（缺字段/`None`/字符串）或 `label` 为空 → 跳过该元素。

**一条坏数据不该让整个待批列表 500**：教师打开页面看不到任何待批提交，比少看一个标签严重得多。

`status` 同理：取值不在 `high`/`medium`/`low` 三者之内时原样透传（见 3.11），后端不做白名单过滤——滤掉一个未预期的分级会让标签凭空消失，而透传至少前端能按未知档渲染成中性色。

### 3.11 `severity` 透传语义值，不映射 CSS 类

出参是 `high` / `medium` / `low`（即 `defects[].status` 原文），**不是** `danger` / `warn` / `info`。

后者是页面的 CSS 类名（`homework.html:270-272` 的 `.tag.danger/.warn/.info`），属于表现层。后端出表现层词汇，等于把「这个页面用这套配色」写进接口契约，换一版设计就要改后端。

前端的映射（high→danger、medium→warn、low→info、未知→info）留到接入时写。

> 顺带记一笔：mock 是**自相矛盾**的——`sub01` 的两条 `cdm` 都是 `status:"high"`，对应的 `tags` 却都是 `cls:"warn"`；`sub02` 也是 `high`，`tags` 却是 `danger`。两个都「对」不了，本接口按 3.11 的确定性映射走，接入后这两条卡片的颜色会统一。

### 3.12 作业不存在 → 404

`db.get(Homework, homework_id)` 取不到就 `BusinessError(404, "作业不存在")`，由 `app/common/errors.py` 的处理器转成统一信封。

与 F1「库里没有作业返回 `[]` 而非 404」不矛盾：F1 查的是**集合**（空集合是合法结果），F4 查的是**一个具名资源**（不存在就是不存在）。

路径用 `<int:homework_id>` 转换器：`/api/homeworks/abc/submissions` 在路由层就 404，不进业务代码。这是本项目的既定约定（见 `app/api/` 其它路由）。

---

## 4 实现设计

### 4.1 分层

```
app/api/homeworks.py          homeworks_submissions(homework_id)   ← 换掉现有桩
app/services/homework_service.py   list_pending_submissions(db, homework_id)
app/repositories/homeworks_repo.py get_pending_submissions(db, homework_id)
app/schemas/homework.py       SubmissionTag / PendingSubmissionItem / PendingSubmissionListResponse
```

`homework_service.list_homeworks` 与 `list_pending_submissions` 同在一个文件：两者是同一份作业数据的两种投影，共用一个模块比拆两个文件更贴近调用方的认知。

### 4.2 出参

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "homework_id": 12,
    "homework_title": "《穆桂英挂帅》· 辕门外三声炮",
    "submissions": [
      {
        "submission_id": 24,
        "student_id": 50,
        "student_name": "刘思琪",
        "student_avatar": "🎵",
        "student_level": "初学",
        "ai_score": 75.2,
        "submitted_at": "2026-08-01T00:00:00",
        "tags": [
          {"label": "音准偏差随机", "severity": "high"},
          {"label": "听辨能力弱",   "severity": "high"},
          {"label": "拖腔不足",     "severity": "medium"}
        ]
      }
    ]
  }
}
```

- `submitted_at` 是 ISO-8601（`mode="json"`），前端负责显示成 mock 那种「07-29 06:30」。**必须 `model_dump(mode="json")`**，同 F1 的理由；F4 里没有 `date` 但有 `datetime`，不转换同样会走 RFC-822。
- `ai_score` / `submitted_at` 可空（列都没 NOT NULL），出 `null`。
- `student_avatar` 可能是**空串**（张三），前端要兜（`avatar || "🎭"` 之类），不能直接当有值用。
- `student_name` / `student_level` 可空：`students.user_id` 若指向不存在的 user（`DOC_ISSUES.md` 第 24 条描述的那类脏数据）就是 `null`。

### 4.3 SQL

一条 join 取完，不在 Python 里逐条回查学生（5 条提交 5 次查询，虽小但没必要）：

```sql
SELECT submissions.*, students.*, users.display_name
FROM submissions
LEFT JOIN students ON students.id = submissions.student_id
LEFT JOIN users    ON users.id    = students.user_id
WHERE submissions.homework_id = :id
  AND (submissions.status IS NULL OR submissions.status != 'reviewed')
ORDER BY submissions.submitted_at ASC NULLS LAST, submissions.id ASC
```

**两个 join 都必须是 LEFT**：`submissions.student_id` 可空，INNER JOIN 会把 `student_id` 为 NULL 的提交直接从待批列表里删掉——又一条教师永远批不到的提交。

`students.user_id` 那层也用 LEFT：`students` 有行但 `users` 侧缺失时，至少还能出 `student_id`，不该整条提交消失。

---

## 5 验证方案

无测试框架（`requirements.txt` 里没有 pytest，不引入），按既定做法用 `/tmp` 临时脚本 + curl + psql。

1. **教师（teacher01）** `GET /api/homeworks/12/submissions` → 200，5 条。顺序应为 `24, 26, 27, 23, 25`——24/26/27 的 `submitted_at` 同为 `2026-08-01`、23/25 同为 `2026-08-02`，两组内部都靠 `id ASC` 定序，这正好把 3.3 的兜底排序验到。逐条核 `tags` 条数与 2.4 一致：李小燕 2、刘思琪 3、周明轩 2、孙志远 2、赵雨桐 1。
2. **hw13 / hw14** → 200 + `[]`（不是 404）。
3. **`/api/homeworks/999/submissions`** → 404，`{"code":404,"message":"作业不存在"}`。
4. **`/api/homeworks/abc/submissions`** → 404。与 3 的差别**在 message 上**：路由层没匹配上，走的是 `errors.py` 里那条把 Werkzeug HTML 404 包成统一信封的处理器，message 是「接口不存在」；3 是业务 404，message 是「作业不存在」。两者都是 `code:404`，只能靠 message 区分。
5. **一致性锚点**：`GET /api/homeworks` 里 hw12 的 `pending_review_count` 必须等于本接口的 `len(submissions)`（都是 5）。
6. **学生（stu001）** → 403；**未登录** → 401。
7. **兜底**：临时给一条提交置 `status = NULL`（按抓到的 id 改），确认它仍出现在列表里；再临时把某条 `ai_detail` 改成 `{"defects": "坏数据"}` 与 `{"defects":[{"label":"X"}]}`（缺 confidence），确认前者出 `[]`、后者跳过该元素且**整个请求仍是 200**。**改完按 id 复原**。
8. **清理**：`check_db.py` 只应报既有漂移（`demo_versions` + `teacher_demos`），不引入新的。

---

## 6 待文档方确认

1. **「待批改」是否等于 `status != 'reviewed'`**。文档只写「AI 初评待终审」。「终审」落到 `submissions.status = 'reviewed'` 是本项目的推断；若将来 `status` 增加「教师已退回」之类的档，本接口的判定要跟着改（这条判定同时存在于 F1 与本接口两处）。
2. **标签的置信度阈值 0.7** 来自页面自己的文案，不是文档。文档从未规定 `defects` 要按置信度筛选，也没规定阈值取多少。
3. **标签条数无上限**。若文档方希望卡片固定显示 2-3 个，需要定「按什么规则取前 N 个」——按置信度取前 N 会在同分时出现不稳定顺序。
4. **`severity` 的分档语义**（high/medium/low 分别意味着什么、是否对应「必须纠正/建议改进/可选」）文档未定义，现在只是把 AI 写进 `defects[].status` 的值透传。
5. **是否要过滤在册名单**（§3.2 选了不过滤）。若文档方认为「名单外的人不该出现在教师的待批列表里」，需要先定义脏数据下这条提交由谁批。
6. **排序**：文档未规定。选了 FIFO（最早提交先批），若教学上更希望「AI 分数低的先看」或「最新的先看」，改 `ORDER BY` 一行即可。

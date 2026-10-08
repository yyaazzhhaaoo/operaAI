# 待批改提交列表（F4）前端接入设计

日期：2026-10-08
接口 spec：`docs/superpowers/specs/2026-09-30-homework-submissions-api-design.md`
接口：`GET /api/homeworks/<int:homework_id>/submissions`（已上线，见 commit `ee986ae`）
页面：`homework.html`
DOC_ISSUES：第 35 条（尤其 §35.3 的 severity 分档、§35.4 的三点待处理）

---

## 1 背景、目标与非目标

### 1.1 目标

把 `homework.html` 左侧「待批改提交」卡片从 mock 常量 `SUBMISSIONS` 换成 F4 真接口，并补上接口必需的**作业选择**交互（F4 是单作业接口，页面当前没有选定作业的概念）。

### 1.2 非目标

- **不改任何后端文件。** F4 已上线，本次是纯前端接入。
- **不做批改详情页（右侧面板）。** 逐字偏差 `lyrics`、加权融合、CDM、BKT、校准、评语都是 **F5** 的内容，F4 一个字段都不出。右侧面板本次**保持 mock 不动**。
- **不删 `HOMEWORKS` / `SUBMISSIONS` 两个 mock 常量。** 理由是同上——`selectSubmission` 仍靠它们渲染右侧面板。这与 F4 接口 spec §1.2 里「前端接入时两个 mock 常量才能删」的预期**不一致**，原因就是那次预设 F5 会一起落地；F5 没落地，所以常量留着。见 3.8。
- **不做多作业聚合。** 一次只拉一份作业的待批列表（F4 的契约就是单作业）。
- **不做「布置新作业」（F2）、终审提交（F6）、校准（F7）。** 相关按钮维持 alert 桩。

---

## 2 现状与真源

### 2.1 F4 出参（真库实测）

```json
{
  "code": 0, "message": "ok",
  "data": {
    "homework_id": 12,
    "homework_title": "《穆桂英挂帅》· 辕门外三声炮",
    "submissions": [
      {
        "submission_id": 24, "student_id": 50,
        "student_name": "刘思琪", "student_avatar": "🎵", "student_level": "初学",
        "ai_score": 75.2, "submitted_at": "2026-08-01T00:00:00",
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

真库基线：`homeworks` 12/13/14，只有 **hw12 有 5 条待批**（24 刘思琪 / 26 孙志远 / 27 赵雨桐 / 23 李小燕 / 25 周明轩，按 `submitted_at ASC, id ASC` 排序）；hw13、hw14 待批 0 条。标签条数依次 3/2/1/2/2。

### 2.2 页面现状（改动锚点）

| 锚点 | 现状 |
|---|---|
| `:504-515` | 「待批改提交」卡片，`#submitList` 容器，右上角只有一个静态文案「AI已初评」 |
| `:610-660` | `HOMEWORKS` / `SUBMISSIONS` 两个 mock 常量 |
| `:682` | `API_BASE = ""`（同源，走 nginx `/api` 代理） |
| `:707` | `renderHwList(items)` 读 F1 真数据；`hw-item` **没有 onclick**，但 CSS 里 `cursor:pointer` 与 `.hw-item.active` 都已写好（`:228`、`:233`）——本来就是照可点击设计的，只是没接线 |
| `:757` | `fetchHomeworks()`，按 `currentUser.role` 分支 |
| `:782` | `renderSubmitList()` 读 `SUBMISSIONS`，无参数 |
| `:800` | `selectSubmission(id)` 先从 `SUBMISSIONS` find，再填右侧面板；`:813` 读 `HOMEWORKS[0].title` 当详情标题 |
| `:929-933` | 首段脚本末尾同步调 `renderSubmitList()` + `selectSubmission("sub01")` |
| `:965-970` | 第二段脚本 `currentUser = user` 之后调 `fetchHomeworks()` |
| `:270-272` | `.tag` 只有 `danger` / `warn` / `info` 三档，无中性档 |

### 2.3 与 F1 前端落地的关系（先例）

F1 的前端接入与接口同批交付，口径记在同一份 spec 的 §2.3.1。本次与它**同构**：新增 `fetch*()` 函数、按角色分支、拉取必须等 `currentUser` 就绪、`API_BASE` 保持空串。两点**不同**：

1. F1 只换了一个列表；本次多一层「作业 → 该作业的待批提交」的联动。
2. F1 落地时两个 mock 常量都还有用（详情页在读）；本次两个常量**仍然有用**，所以依旧不删。

---

## 3 自拟口径

以下都是 F4 接口 spec 与《5-接口清单》未定义、由本次前端落地自定的。

### 3.1 作业选择：默认第一份，`hw-item` 可点切换

页面此前没有「当前作业」这个概念，`selectSubmission` 直接写死 `HOMEWORKS[0].title`。F4 必须传 `homework_id`，所以本次引入 `currentHwId`：

- 页面加载后取 F1 列表的**第一份**作业作为默认值。
- 点击任一 `hw-item` 切换 `currentHwId`，待批列表随即重拉。

**「第一份」正好是 hw12 是排序的副产品，不是刻意去找「有待批的那份」。** F1 的排序是待办优先（`grading → ongoing → closed`，见 `homework_service._sort_key`），而 hw12 有 5 条未终审 → `grading` → 排最前。**不要在页面里另写一段「找出第一份 `pending_review_count > 0` 的作业」**：那等于把 F1 的排序口径在前端复制一份，两边漂移时教师看到的默认作业会不一致。教师想批哪份就点哪份。

选中态用已有的 `.hw-item.active`（`:233`），无需新增 CSS。

### 3.2 点击一个真提交：**不做任何事**

`SUBMISSIONS` 里的 id 是 `sub01`/`sub02`，F4 出的是 `23/24/…`，两者不可能相交。点击真提交时：

- **不设置 `currentSubId`、不重渲染列表、不动右侧面板**——即先 `find`、找不到立即 `return`。

**不能写成「先设 `currentSubId = id` 再 return」。** 那是页面现在的写法（`:801-805`），后果是卡片高亮跟着移动到真提交上，而右侧面板还停在上一次的 mock 内容——教师会以为自己看到的就是刚点的那名学生。宁可完全不动。

代价：`currentSubId` 永远是 `null`，**没有任何卡片会高亮**（真 id 不在 mock 里，mock id 不在真列表里）。这是「保留 mock 详情 + 点击无反应」的必然结果。

### 3.3 右侧面板：加载后停在空状态

**不在页面初始化时调 `selectSubmission("sub01")`**（现状 `:933` 要删）。右侧显示自己的空状态（「选择左侧提交进行批改」，`#emptyState`，`:525`），直到 F5 落地。

比「常驻显示李小燕的 mock 详情」好的地方：真列表有 5 名学生，面板却永远只显示其中一名的**假**数据，是这一页最容易误导人的状态。空状态不撒谎。

`selectSubmission` 函数体、`SUBMISSIONS`、`HOMEWORKS` **一行不删**，只是不再主动调用——F5 落地时它们是要被替换的对象，留着比删掉再抄回来省事。评审时不要把它们当死代码清掉。

### 3.4 `severity` → CSS 类

接口透传语义值（`high`/`medium`/`low`），配色是前端的事（接口 spec §3.11）。映射：

| `severity` | CSS 类 | 现成颜色 |
|---|---|---|
| `high` | `danger` | 朱砂 |
| `medium` | `warn` | 赭黄 |
| `low` | `info` | 景泰蓝 |
| 其它（含后端在取不到 `status` 时给的 `"unknown"`） | `neutral` | **本次新增** |

`neutral` 是本次唯一新增的 CSS（一行）：`.submit-item .tags .tag.neutral{background:var(--bg-secondary);color:var(--text-muted)}`。现有三档里没有中性色，直接复用 `info` 会把「未知档」和「low」混成一色。**若评审认为不值得加这一行，可改为未知档回落 `info`**——那行 CSS 删掉、映射表最后一行改成 `info` 即可。

**不做白名单过滤**：取到不认识的档照渲，不能让它凭空消失（接口 spec §3.11 同理）。

### 3.5 时间格式

`submitted_at` 是 ISO-8601 `"2026-08-01T00:00:00"`，卡片副标题照 mock 的观感显示成 `"08-01 00:00"`。

**用字符串切片，不要 `new Date()`。** 串里没有时区后缀，而库里存的本来就是北京时间（PostgreSQL server timezone = `Asia/Shanghai`）。`new Date("2026-08-01T00:00:00")` 会按**浏览器本地时区**解析，再 `toLocaleString` 又按本地时区输出——在非 +08:00 的机器上显示会漂。切片没有这个问题：`s.slice(5,16).replace("T"," ")`。

`submitted_at` 为 `null` 时显示 `"—"`（列可空）。

### 3.6 空值兜底

| 字段 | 可能的值 | 兜法 |
|---|---|---|
| `student_avatar` | **空串**（`students.avatar` 是空串不是 NULL，如张三那个种子） | `\|\| "🎭"`。**必须 `\|\|`，不能 `??`**——`??` 只兜 `null`/`undefined`，兜不到空串 |
| `student_name` | `null`（`students.user_id` 指向不存在的 user） | `"未知学生"` |
| `ai_score` | `null`（列可空） | `"—"` |
| `tags` | `[]`（`ai_detail` 缺失或结构异常，接口 spec §3.10） | 不渲染标签行，卡片其余部分照常 |

**标签不截断**：接口按置信度降序给全量（刘思琪 3 条）。`.submit-item .tags` 本就是 `flex-wrap`，让它换行，不要 `slice(0,2)`。

所有进 `innerHTML` 的字段一律过 `esc()`（标题、姓名、标签文字都来自数据库）。

### 3.7 权限与各态文案

F4 挂 `@teacher_required`。照 `fetchHomeworks` 的做法，**学生端不发请求**（明知会 403 就不发），直接渲染文案：

| 情形 | `#submitList` 内容 |
|---|---|
| 学生登录 | 「待批改提交仅教师可见」 |
| 请求进行中 | 「加载中…」 |
| 教师、该作业待批为 0 | 「暂无待批改提交」 |
| 请求失败 | 「加载失败，请刷新重试」 |

卡片右上角新增 `#subSummary`（与作业列表的 `#hwSummary` 对称）：有数据时「N条待批」，无数据/加载中时留空——**不要写「暂无待批」**，那会和「仅教师可见」并排出现，读起来像「确实一条都没有」，而实际是「没权限看」。这条与 F1 落地时 `hwSummary` 的处理逐字同源。

### 3.8 两个 mock 常量保留

`HOMEWORKS`、`SUBMISSIONS` 都不删。`:606-609` 现有的注释要改写：保留理由从「F4/F5 未实现」改成「**F5 未实现**」——F4 已经上线了，旧注释已过时。

`HOMEWORKS[0].title`（`:813`）在本次之后**没有任何调用点会走到**（`selectSubmission` 只可能被 mock id 触发，而 mock id 不在真列表里）。仍然保留，同上。

---

## 4 实现设计

改动全部在 `homework.html` 一个文件内。

### 4.1 状态

```js
let hwItems      = [];     // F1 列表的最近一次结果，selectHomework 改高亮时复渲用
let currentHwId  = null;   // 当前选中的作业 id（F1 的 homework_id）
let submitItems  = null;   // 当前作业的待批提交；null=加载中，[]=空，数组=有数据
let currentSubId = null;   // 右侧 mock 详情的选中项；F5 落地前恒为 null
```

`submitItems` 用 `null` / `[]` 两态区分「还没拉回来」与「拉回来了但是空的」，否则加载中会先闪一下「暂无待批改提交」。

### 4.2 函数

| 函数 | 职责 |
|---|---|
| `fetchSubmissions(hwId)` | 新增。按角色分支 → `GET ${API_BASE}/api/homeworks/${hwId}/submissions` → 填 `submitItems` → `renderSubmitList()`。失败置失败态 |
| `selectHomework(hwId)` | 新增。设 `currentHwId` → `renderHwList(hwItems)`（刷高亮）→ `submitItems = null; renderSubmitList()`（进加载态）→ `fetchSubmissions(hwId)` |
| `renderSubmitList()` | 改。不再读 `SUBMISSIONS`，改读 `submitItems`；四态渲染；`esc()` + §3.6 兜底 |
| `renderHwList(items)` | 改。`hw-item` 加 `onclick="selectHomework(${hw.homework_id})"` 与 `active` 类（`hw.homework_id === currentHwId`）；把 `items` 存进 `hwItems` 供 `selectHomework` 复渲 |
| `selectSubmission(id)` | 改。**先 `find`、找不到立即 return**；其余（填右侧面板）不动 |
| `fetchHomeworks()` | 改。成功后若 `items.length` 则 `selectHomework(items[0].homework_id)` |

### 4.3 时序

```
页面加载
  └ 首段 <script>：renderSubmitList()          // submitItems=null → 「加载中…」
                    （不再调 selectSubmission("sub01")）
  └ 第二段 <script>：/api/auth/me → currentUser = user
                     → fetchHomeworks()        // 学生在此内部 return
                        → renderHwList(items)
                        → selectHomework(items[0].homework_id)   // 仅教师且有作业时
                           → renderSubmitList()  // 加载态
                           → fetchSubmissions()  // 拉真数据
```

`fetchHomeworks` 已有的「学生端直接 return」保证了后面不分支也行，但 `items` 为空（教师一份作业都没布置）时不要调 `selectHomework`——那会发一个 `homework_id=undefined` 的请求。

### 4.4 HTML / CSS

- `:511` 卡片右上角：静态文案「AI已初评」→ `<span id="subSummary">`。
- CSS 新增一行 `.tag.neutral`（§3.4）。

---

## 5 验证

本仓库无测试框架（无 `tests/`、`requirements.txt` 无 pytest），验证靠对真接口的 curl + 浏览器实操 + `check_db.py`。

1. **接口侧（回归，确认没被前端改动影响）**：起 `python app-d.py`，`teacher01` 登录后 curl `GET /api/homeworks/12/submissions` 得 5 条、顺序 24/26/27/23/25；`/13/submissions` 得 `[]`；`/999/submissions` 得 404。
2. **教师端页面**：登录 `teacher01` 打开 `homework.html` → 作业列表出 3 份、**第一份高亮**（hw12）；待批列表出 5 条、每条标签颜色按 §3.4 映射；点 hw13 → 待批列表变「暂无待批改提交」、右上角计数清空；点回 hw12 → 5 条回来。
3. **点击提交无反应**：点任一条待批提交 → 卡片不高亮、右侧面板仍是空状态、控制台无报错。
4. **学生端**：登录 `stu001` → 作业列表「作业列表仅教师可见」、待批列表「待批改提交仅教师可见」、右上角无计数，**Network 面板里没有 `/api/homeworks` 与 `/submissions` 两个请求**。
5. **失败态**：停掉 Flask 后刷新 → 待批列表出「加载失败，请刷新重试」。
6. **兜底（可选，需临时改库）**：按 DOC_ISSUES 第 35.5 条记录的纪律——临时改动**只能按抓到的 id 改回**，绝不 `DELETE FROM <表> WHERE <别的列>`。本次前端接入不改库，默认跳过这一项。
7. `python scripts/check_db.py` 无新增漂移（本次不动库，应与基线一致）。

---

## 6 待文档方确认

1. **`severity` 三档的语义**（DOC_ISSUES §35.3）：`high`/`medium`/`low` 分别意味着什么？本次前端的配色映射（high→danger、medium→warn、low→info）是自拟的。
2. **详情页（F5）的交付时点**：右侧批改面板在 F5 落地前对真数据完全不可用，教师只能看到待批名单，点不开任何一份。
3. **作业选择交互是否符合预期**：默认第一份 + 点击切换，是本次自拟；文档未规定教师端如何选定作业。

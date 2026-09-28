# 曲目列表接口（C1 `GET /api/demos`）实现设计

日期：2026-09-28 ｜ 状态：已评审待实现 ｜ 关联：《5-接口清单》2.3 节 C1；`DOC_ISSUES.md` 第 26 条

## 1. 背景与目标

`annotation.html`（歌词级标注页，模块 9）目前完全不调后端：歌词网格读 `LYRICS`、已有标注读 `EXISTING_ANNS`，全是页面内 mock。页面里 `.piece-selector`/`.piece-btn` 的 CSS 与一个没人调用的 `switchPiece()` 函数是预留过的曲目选择器位置，但 HTML 里那 3 个按钮仍是写死的。

本轮**只做 C1**：把 `GET /api/demos` 从占位（`demos()` 直接 `return ok()` 回空）换成真实查询，再把 `annotation.html` 的曲目选择器接到它上面。

**目标**：

1. `GET /api/demos` 返回库中全部曲目及其分段数
2. `annotation.html` 加载后拉该接口，渲染曲目选择器；无分段的曲目置灰禁用

**非目标（明确不做）**：

- **不实现 C2–C7**（`/demos/<id>/segments`、`/segments/<id>`、标注的增删查）。`app/api/demos_segments_annotations.py` 里那 6 个占位路由原样留着
- **不换歌词网格**。`switchPiece()` 只切高亮 + 提示，`LYRICS`/`EXISTING_ANNS` 仍是 mock——换歌词要等 C2/C3，那两轮再做
- 不改 `schema.sql`、不改 `app/models/`、不改 `app-d.py`、不引入新依赖
- 不给 `/api/demos` 加教师限制（见 4.3）
- 不做分页、不做筛选/搜索（文档未要求，库里当前 5 条）

## 2. 文档给的 vs 库里有的

《5-接口清单》2.3 节 C1 的**全部**内容是一行：

| 编号 | 接口 | 权限 | 说明 |
|---|---|---|---|
| C1 | `GET /api/demos` | 登录 | 曲目列表（陪练选曲 + 作业布置用） |

**响应体字段、排序、分页、过滤口径全部未定义**——与第 22 条（G5 推荐）、第 24 条（G6 过程指标）、第 25 条（G7 作业进度）同类。本文第 3、4 节的口径是**实现时定的**（用户逐条确认），登记为 `DOC_ISSUES.md` 第 26 条。

可依据的库表（`schema.sql`）：

- `teacher_demos(id, title NOT NULL, role, banshi, audio_id, elo_difficulty DEFAULT 1000, created_at)`
- `segments(id, demo_id, seq, title, lyrics_json, duration)`
- `audio_files.duration_sec` —— 曲目时长挂在这里，`teacher_demos` 自己没有时长列

库里当前 6 条曲目：id 16/17/18 有分段（5/3/2）且有音频，id 15/19 分段为 0，id 1 是种子数据、无音频、1 个分段。

## 3. 接口契约

```
GET /api/demos        权限：登录（@login_required）
```

统一信封（`app/response.py` 的 `ok`），`data` 是数组：

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "id": 16,
      "title": "《穆桂英挂帅》· 辕门外三声炮",
      "role": "青衣",
      "banshi": "西皮流水",
      "duration": 23.5,
      "elo_difficulty": 0.72,
      "segment_count": 5
    }
  ]
}
```

### 3.1 字段口径

| 字段 | 来源 | 可空 | 说明 |
|---|---|---|---|
| `id` | `teacher_demos.id` | 否 | |
| `title` | `teacher_demos.title` | 否 | 库里是 NOT NULL |
| `role` | `teacher_demos.role` | **是** | 行当 |
| `banshi` | `teacher_demos.banshi` | **是** | 板式 |
| `duration` | `audio_files.duration_sec`（经 `teacher_demos.audio_id`） | **是** | 曲目无音频、或音频未回填时长时为 `null` |
| `elo_difficulty` | `teacher_demos.elo_difficulty` | **是** | **如实返回，不在后端做 0–1 兜底**，见 3.2 |
| `segment_count` | `count(segments.id)` | 否 | 无分段时是 `0`，不是 `null` |

可空列必须写成 `| None`：`teacher_demos` 与 `audio_files` 这几列在 DDL 上均可空，库里只要有一行空值，写成非空就会整片 500——`DemoLibraryListOut` 的注释记着上一版正是栽在这个错上。

**不返回** `created_at` 与解析 `status`：前者选曲用不上；后者是示范库管理（`/api/demo/library/list`）的概念，泄漏给陪练选曲/作业布置只会让这两个场景平白依赖 redis。

### 3.2 `elo_difficulty` 不做后端兜底

库里有 2 条是列默认值 **1000**（未标定），而前端按 0–1 渲染（`DOC_ISSUES.md` 第 19 条）。接口**如实返回 1000**，判定留给前端：取不到有效值（`null` / 非有限数 / 超出 0–1）就显示「待校准」。

理由：这是「数据没标定」，不是「接口取不到值」。后端悄悄把它改成 `null` 或夹到 1.0，都会让调用方**分不清「没标定」和「标定成了边界值」**，而标注页要显示的恰恰是前者。

### 3.3 排序与过滤

- **排序**：`ORDER BY teacher_demos.id ASC`。文档未定，取主键升序——稳定、可预期，且与 `demo_library` 列表的默认顺序一致
- **不过滤**：`segment_count = 0` 的曲目（库里 15/19 号）**照样返回**。过滤是调用方的事：标注页要置灰展示「还没解析」，陪练选曲要直接跳过，两个场景诉求不同，接口保持中立
- 无分页。曲目是「剧目级」量级（真实使用是几十条），加 `LIMIT` 只会让前端多一层翻页逻辑

## 4. 实现

### 4.1 分层

沿用 `demo_library` 那套 api → service → repo（各层职责见 `app/api/demo_library.py` 的模块注释：api 层只校验入参、调 service、组装响应，不写 SQL）。

| 文件 | 改动 |
|---|---|
| `app/repositories/library_repo.py` | 新增 `get_demo_list(db)`，一条 SQL 取曲目 + 分段数 |
| `app/services/library_service.py` | 新增 `demo_list(db)`，摊平 `duration` |
| `app/schemas/demo.py` | **新建**，只放 `DemoListOut` |
| `app/api/demos_segments_annotations.py` | `demos()` 填实现，其余 6 个占位路由不动 |
| `DOC_ISSUES.md` | 新增第 26 条 |

### 4.2 查询

```python
select(TeacherDemo, func.count(Segment.id))
    .outerjoin(Segment, Segment.demo_id == TeacherDemo.id)
    .group_by(TeacherDemo.id)
    .order_by(TeacherDemo.id)
```

- 用 `outerjoin` 而非 `join`：没分段的曲目也要出现（3.3），`join` 会把它们整条丢掉
- 计数写 `count(Segment.id)` 而非 `count(*)`：`outerjoin` 未命中时 `segments` 侧全是 NULL，`count(*)` 会数成 **1**，`count(Segment.id)` 才是 **0**
- 一条 SQL 查完，不用 N+1（`demo_library_list` 逐行查 redis 是因为状态在 redis 里，这里没有那个约束）
- `duration` 走 `demo.audio.duration_sec`，靠 `TeacherDemo.audio` 关系**惰性加载**——会退化成每行一次查询。曲目量级是几十条，与 `demo_library_list` 的取舍一致（那里也是逐行读 `demo.audio`）；真到几百条再改 `joinedload`，把这条注释留在代码里当锚点

**不复用 `get_library_list`**：它不返回分段数，为它加上会改动已实现的 `/api/demo/library/list` 行为。两个函数并存，各自简单。

### 4.3 权限保持 `@login_required`

占位代码里已经是 `@login_required`，本轮**保持不动**——与文档 C1 的「登录」一致。

不能加 `@teacher_required`：C1 要服务「陪练选曲」，**学生必须能调**，加了会当场堵死学生端。注意这与 `/api/demo/library/list`（`@teacher_required`）不同，两者不是同一个场景：示范库管理是教师专属，曲目列表是师生共用。

## 5. 页面调用（`annotation.html`）

**只改 `.piece-selector` 与 `switchPiece()` 两处。**

### 5.1 HTML

`annotation.html:440-444` 那 3 个写死的 `<button class="piece-btn">` 换成空容器：

```html
<div class="piece-selector" id="pieceSelector"></div>
```

`.piece-selector` / `.piece-btn` 的 CSS（`annotation.html:191-205`）已存在，不动。

### 5.2 `fetchDemos()`

放在主 `<script>`（body 底部那个）里，页面加载时调用：

- 请求 `fetch('/api/demos', { credentials: 'same-origin' })`
- **必须同源相对路径**：与 `pitch_comparison.html`、`demo_library.html` 同一个坑——写成跨源地址（如 `location.host + ':8877'`）时 fetch 默认不带 Cookie，后端 `login_required` 只会看到空 session 并回 401
- **成功**：每条曲目渲染一个 `.piece-btn`
  - 默认选中第一条 `segment_count > 0` 的；若**全部**为 0，则一条都不选中，歌词网格维持现状不渲染选择态
  - `segment_count === 0` 的按钮**仍然渲染**，但加 `disabled` 与降透明度：标注页标不了，可要让教师看见「这条还没解析」，直接隐藏等于把问题藏起来
  - 按钮文案带分段数，如 `《穆桂英挂帅》· 辕门外三声炮 (5段)`
- **失败**（网络错误或 `code !== 0`）：容器里渲染一行「曲目列表加载失败」，**不弹 toast、不打断页面**——歌词网格仍是 mock，曲目列表拿不到不该让整个标注页不可用
- **空列表**：渲染「暂无曲目」。库里当前不为空，但这两种情况不能混成同一句文案

### 5.3 `switchPiece(idx)`

从 mock 改成读已加载的曲目数组：`idx` 是**渲染顺序的下标**（不是 `demo_id`，与现有 `onclick="switchPiece(0)"` 的写法一致），切 `.active` 高亮 + toast 提示当前曲目。

**toast 必须说清歌词没换**——`LYRICS` 仍是 mock，若提示「已加载新曲目数据」，教师会以为网格已经跟着换了。文案改为点明「歌词数据待接入（C2/C3 未实现）」。

### 5.4 不做的事

- 不给学生隐藏选择器（C1 是师生共用）
- 不动底部登录用户条那段 IIFE（`/api/auth/me`、登出）
- 不动 `renderLyrics()` / `renderAnnotations()` / `saveAnnotation()`

## 6. 验证

项目**没有测试框架**（无 `pytest`、无 `tests/` 目录、`requirements.txt` 里也没有 pytest），所以按仓库既有做法手工验证。

接口部分：

1. 起后端，用 `teacher01` / `stu001` 两个账号分别登录拿 Cookie
2. `curl` 打 `GET /api/demos`，逐条核对：
   - 未登录 → `401` + `{"code":401,...}`（`login_required` 生效）
   - **学生账号也能拿到完整列表**（验证没误加 teacher 限制）
   - `data` 有 **6** 条，`segment_count` 分别为 id 1→1、15→0、16→5、17→3、18→2、19→0（与库中实际一致）
   - 无音频的 id 1 与音频未回填的曲目，`duration` 是 `null` 而不是 0
   - id 15/19 的 `elo_difficulty` 是 `1000.0`（如实返回，未被兜底改掉）
   - `role` / `banshi` 为空的行走通，不 500
3. `python scripts/check_db.py` 跑一遍（本次不改模型与 `schema.sql`，应仍只剩既有漂移）

页面部分：

4. 浏览器打开 `annotation.html`，确认 5 个按钮渲染出来、两条无分段的置灰禁用、默认选中第一条有分段的
5. 停掉后端再刷新，确认显示「曲目列表加载失败」而页面其余部分照常可用

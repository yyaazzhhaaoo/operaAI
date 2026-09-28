# 分段列表接口（C2 `GET /api/demos/<id>/segments`）实现设计

日期：2026-09-28 ｜ 状态：已评审待实现 ｜ 关联：《5-接口清单》2.3 节 C2；`DOC_ISSUES.md` 第 20、27 条

## 1. 背景与目标

C1（`GET /api/demos`）已落地，`annotation.html` 的曲目选择器已接真。本轮做 C2：列出某曲目下的唱段。

**目标**：

1. `GET /api/demos/<int:demo_id>/segments` 返回该曲目的分段列表
2. `annotation.html` 增加分段选择器：切曲目 → 拉分段 → 切分段

**非目标（明确不做）**：

- **不实现 C3–C7**（`/segments/<id>`、标注增删查）。`app/api/demos_segments_annotations.py` 里剩下那 5 个占位路由原样保留
- **不把歌词网格接真**。`LYRICS` / `EXISTING_ANNS` 仍是 mock。接真需要 C3 的 `lyrics_json`，且要先解决第 2 节那三套形状不一致的问题——放到 C3 那轮
- 不改 `schema.sql` / `app/models/*` / `app-d.py`，不引入新依赖
- 不做分页（一个曲目的分段是个位数到几十条）

## 2. 文档给的 vs 库里有的

《5-接口清单》2.3 节 C2 的**全部**内容是一行：

| 编号 | 接口 | 权限 | 说明 |
|---|---|---|---|
| C2 | `GET /api/demos/<id>/segments` | 登录 | 分段列表 |

**响应体字段、排序、404/空数组的口径全部未定义**，与 C1（第 26 条）、G5/G6/G7（第 22/24/25 条）同类。第 3 节的口径是实现时定的（用户逐条确认），登记为第 27 条。

### 2.1 实测到的库表现状

`segments` 表 11 行，分布在 4 个曲目下（2026-09-28 实测）：

| demo_id | 分段数 | segment.id | seq | title | duration |
|---|---|---|---|---|---|
| 1 | 1 | 1 | 1 | 第一段 | 30.5 |
| 15 | **0** | — | — | — | — |
| 16 | 5 | 78 / 102 / 103 / 104 / 105 | 1..5 | 第一段 / 辕门外三声炮 / 如同雷震 / 天波府走出来 / 保国臣 | 24.7 / 2.8 / 2.4 / 2.8 / 2.2 |
| 17 | 3 | 79 / 106 / 107 | 1..3 | 第一段 / 海岛冰轮 / 初转腾 | 44.7 / 3.5 / 3.0 |
| 18 | 2 | 80 / 108 | 1..2 | 第一段 / 看大王在帐中 | 38.5 / 4.0 |
| 19 | **0** | — | — | — | — |

### 2.2 顺带查实的三件事（本次不做，但影响后续）

1. **`lyrics_json` 在库里不是 NULL，11 行全有数据。** `DOC_ISSUES.md` 第 20 条写「该列恒 NULL，与 `seed.sql` 之外的现状一致」——前半句对（解析链路 `replace_segments` 确实写 `None`），后半句与当前库不符：`seed.sql` 只定义了 seg 1，而 seg 78/79/80/102–108 是后来人工录入的，都有内容。第 20 条据此补注。
2. **`lyrics_json` 存在三种互不兼容的形状**（字段名与取值都对不上）：

   | 形状 | 样例 | 出现在 |
   |---|---|---|
   | A 带 `note` | `{word,midi,start,end,note:"NOTE_8"}` | seg 78/79/80 |
   | B 带 `tip` | `{word,midi,start,end,tip:"起音稳…"}` | seg 102–108 |
   | 种子 | `{word,midi,start,end,note:"half",tip:"起音轻…"}` | seg 1 |

3. **前端要的又是第四套**：`annotation.html` 的 `LYRICS` mock 是 `{char,pitch,note,start,duration}`，`note` 取值 `"8"/"4"/"2"/"16"/"1"`。即 `word`↔`char`、`midi`↔`pitch`、`end-start`↔`duration` 三处要转换，`note` 还要在 `NOTE_8` / `half` / `"8"` 之间做词表映射。

C2 不含歌词，所以这三件事**本轮不阻塞**，但要写进第 27 条，否则做 C3 时会踩空。

## 3. 接口契约

```
GET /api/demos/<int:demo_id>/segments        权限：登录（@login_required）
```

统一信封，`data` 是数组：

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {"id": 78,  "seq": 1, "title": "第一段",       "duration": 24.7},
    {"id": 102, "seq": 2, "title": "辕门外三声炮", "duration": 2.8}
  ]
}
```

### 3.1 字段口径

| 字段 | 来源 | 可空 | 说明 |
|---|---|---|---|
| `id` | `segments.id` | 否 | **必须有**——前端调 C3 `/segments/<id>`、C4 标注都要它。文档只说「分段列表」，不给 id 这个接口就没有下游 |
| `seq` | `segments.seq` | **是** | 段序，前端显示「第 N 段」用它 |
| `title` | `segments.title` | **是** | |
| `duration` | `segments.duration` | **是** | 该段时长（秒）。**没有起止时间**——`segments` 表没有 `start`/`end` 列，位置信息只有 `seq` |

三列在 DDL 上均可空，一律写成 `| None`（同 C1 的理由：库里只要有一行空值，写成非空就整片 500）。

**不返回** `lyrics_json`：文档把逐字数据划给 C3（「段落详情，含 lyrics_json」）。C2 是列表接口，带上歌词会让响应体大一个量级，而且第 2.2 节那三套形状没统一之前，返回什么都是错的。也不返回 `demo_id`——它是入参，调用方本来就知道。

### 3.2 排序

`ORDER BY segments.seq ASC`，复用 `library_repo.list_segments` 的既有行为（它的 docstring 写明「前端就按这个顺序显示『第 N 段』」）。

### 3.3 边界

| 情况 | 响应 |
|---|---|
| `demo_id` 存在且有分段 | `200` + 数组 |
| `demo_id` 存在但无分段（库里 15/19） | **`200` + `[]`**——「这个曲目还没有唱段」是正常状态，不是错误 |
| `demo_id` 不存在 | `404` + `{"code":404,"message":"曲目不存在"}` |
| 路径不是整数（`/api/demos/abc/segments`） | `404`，**在路由层**由 `<int:demo_id>` 挡下，不进视图 |

第三种与第四种必须都是 404，但来源不同：前者是视图里 `BusinessError(404)`，后者是 Flask 路由不匹配。两者对调用方表现一致，这是有意的。

### 3.4 权限

`@login_required`，与 C1 一致。**不能**加 `@teacher_required`：学生端陪练要选唱段。

## 4. 实现

| 文件 | 改动 |
|---|---|
| `app/services/library_service.py` | +`demo_segments(db, demo_id)` |
| `app/schemas/demo.py` | +`DemoSegmentOut` |
| `app/api/demos_segments_annotations.py` | `demos_segments()` 填实现；路由 `<id>` → `<int:demo_id>` |
| `DOC_ISSUES.md` | +第 27 条；第 20 条补注 |

### 4.1 不复用 `demo_library_get`

`library_service.demo_library_get(db, demo_id)` 已经返回 `(TeacherDemo, list[Segment])`，看起来可以直接拿来用。不用它，两个理由：

1. 它的 docstring 明确解释了为什么要**一次**把 demo 与 segments 都取回来——「分两次查会在『demo 存在但分段刚好被重跑清空』的瞬间读到不一致的组合」。C2 只要分段，这个理由不成立，强行复用等于把一个为别的场景定的取舍搬过来。
2. 它的 404 文案是「**示范**曲目不存在」。C1 的 spec 已经立过同一条规矩：示范库管理的概念不该泄漏给陪练/标注场景（那里正是因此不返回 `status`）。

新的 `demo_segments` 只有三行：查 demo 判存在 → 抛 404 → 返回 `list_segments`。

## 5. 页面调用（`annotation.html`）

C1 那轮已经建立了 `demos` / `currentDemoIdx` / `switchPiece(idx)` / `fetchDemos()` 这套。本轮在它下面加一层分段。

### 5.1 HTML

在现有的 `<div class="piece-selector" id="pieceSelector"></div>` **之后**加：

```html
<div class="piece-selector" id="segmentSelector"></div>
```

复用 `.piece-selector` / `.piece-btn` 的样式（同一页面里两层选择器视觉一致，靠按钮文案区分：「第 N 段 · X.Xs」）。

### 5.2 CSS

`.piece-btn` 目前是主题色的实心高亮。分段是比曲目低一层的东西，全用同样的高亮会让人分不清哪行在选什么。加一条：

```css
#segmentSelector{margin-top:-6px}
#segmentSelector .piece-btn{font-size:12px;padding:6px 12px}
```

### 5.3 `fetchSegments(demoId)`

- 请求 `fetch(\`/api/demos/${demoId}/segments\`, { credentials: 'same-origin' })`（同源相对路径，理由同 C1）
- **成功**：渲染「第 N 段 · X.Xs」按钮。`title` 有值时显示 `第 N 段 · title · X.Xs`；`seq` 或 `duration` 为 null 时优雅降级（只显示能显示的，不要拼出 `第 null 段 · nulls`）
- 默认选中第一段
- **空数组** → 「该曲目暂无分段」
- **失败** → 「分段加载失败」。不弹 toast、不打断页面

两种文案都渲染成 `<span class="piece-empty">…</span>` 放进 `#segmentSelector`，复用 C1 已有的 `.piece-empty` 样式，不另起一套。

### 5.4 请求竞态守卫

快速连点两个曲目时，先发的慢响应可能**后**到，把后发的正确结果覆盖掉——分段会显示成上一个曲目的。

用一个模块级自增序号挡掉：

```js
let segReqToken = 0;

async function fetchSegments(demoId) {
  const token = ++segReqToken;   // 每次请求领一个号
  ...
  const body = await (await fetch(...)).json();
  if (token !== segReqToken) return;   // 期间又发过一次，本次结果作废
  ...
}
```

判定必须在 `await` **之后**做——`await` 之前领号是没意义的。

### 5.5 `switchPiece(idx)` 追加

现有实现切完高亮 + toast 就结束了。追加两件事：

1. 先把 `#segmentSelector` 清空（`innerHTML = ""`）：换曲目的瞬间旧分段必须立刻消失，否则会在新分段到达前一直显示上一个曲目的分段
2. 再 `fetchSegments(d.id)`，**不 await**——`switchPiece` 是同步函数，改成 `async` 会让 `btn.onclick` 的调用方多一层未处理的 Promise。高亮与 toast 不依赖分段结果，不该等它

### 5.6 `switchSegment(idx)`

新增：切高亮 + toast 提示当前唱段。`idx` 同样是**渲染顺序的下标**（不是 `segments.id`），与 `switchPiece` 保持一致。

**toast 同样要说清歌词没换**（同 C1 的做法）：文案点明「歌词网格待接入（C3 未实现）」，不能说「已加载新唱段数据」。

### 5.7 降级：曲目列表加载失败时

`fetchDemos()` 失败时曲目区显示「曲目列表加载失败」，此时**分段区要一并清空**——否则页面会留着上一次的分段（或空白）而不说明原因。分段区显示同一句话即可。

## 6. 验证

项目**没有测试框架**（无 pytest、无 `tests/`），按仓库既有做法手工验证。

接口部分（后端在跑，种子账号 `teacher01` / `stu001`，密码 `xiyun@2026`）：

1. 未登录 → `401`
2. **学生账号能访问**（没误加教师限制）
3. `demo_id=16` → **5** 段，`seq` 为 `1,2,3,4,5`，`id` 为 `78,102,103,104,105`，`duration` 为 `24.7,2.8,2.4,2.8,2.2`
4. `demo_id=17` → 3 段；`demo_id=18` → 2 段；`demo_id=1` → 1 段（`duration` 为 `30.5`）
5. `demo_id=15` / `demo_id=19` → `200` + `data: []`（**不是 404**）
6. `demo_id=99999` → `404` + 「曲目不存在」
7. `/api/demos/abc/segments` → `404`（路由层挡下，body 是 Flask 的默认 404，不是统一信封——这是 Flask 行为，不是本项目约定）
8. 每条只有 `id / seq / title / duration` 四个键，**没有** `lyrics_json` / `demo_id`

页面部分（用 `/browse` 技能）：

9. 切到 id 16 → 分段区出现 5 个按钮「第 1 段 · 第一段 · 24.7s」…
10. 默认选中第 1 段；点第 2 段 → 高亮切换 + toast 明说歌词未接入
11. **歌词网格无变化**（预期行为，不是 bug）
12. 切到 id 1 → 分段区变成 1 个按钮
13. 降级：临时把 URL 改成不存在的接口，确认分段区显示「分段加载失败」且页面其余部分可用；**验证完改回并确认无残留**
14. 快速连点两个曲目，确认最终显示的分段属于**后点**的那个（竞态守卫生效）

## 7. 收尾

`python scripts/check_db.py` 应只剩既有漂移（`demo_versions` + `teacher_demos` 三列）。本次不改模型与 `schema.sql`。

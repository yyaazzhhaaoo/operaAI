# 段落详情接口（C3 `GET /api/segments/<id>`）实现设计

日期：2026-09-28 ｜ 状态：已评审待实现 ｜ 关联：《5-接口清单》2.3 节 C3；`DOC_ISSUES.md` 第 20、27 条

## 1. 背景与目标

C1（曲目列表）与 C2（分段列表）已落地，`annotation.html` 的曲目/唱段两层选择器已接真。本轮做 C3：取单个唱段的详情，**核心是 `lyrics_json`**——逐字音高/时值/技巧提示。

C3 是 C1→C2→C3 这条链的最后一环，落地后歌词网格才第一次有真数据。

**目标**：

1. `GET /api/segments/<int:segment_id>` 返回段落元信息 + 归一后的逐字歌词
2. `annotation.html` 的歌词网格改读真数据；切唱段时拉取并重渲染
3. 把 `lyrics_json` 的词表归一落到数据层（清掉库里遗留的两套 `note` 词表）

**非目标（明确不做）**：

- **不实现 C4–C7**（`/segments/<id>/annotations`、标注增删查）。那 4 个占位路由原样保留
- **标注仍是 mock**：`saveAnnotation` / `renderAnnotations` / `TECHNIQUE_DEPS` / `RULE_IMPACT` 不动。切唱段时标注列表清空，走空态——这是诚实反映「C4 未实现」，不是缺陷
- 不改 `schema.sql` / `app/models/*`，不引入新依赖，不引 Alembic
- 不做歌词分页（一个唱段的字数是 2–66 条）

## 2. 文档给的 vs 库里有的

《5-接口清单》2.3 节 C3 的**全部**内容是一行：

| 编号 | 接口 | 权限 | 说明 |
|---|---|---|---|
| C3 | `GET /api/segments/<id>` | 登录 | 段落详情，含 `lyrics_json`（逐字音高/时值/技巧提示） |

权限列写的是**登录**（同 C1/C2），不是教师——学生端陪练要看歌词。

「技巧提示」即 `tip`，文档把它和「逐字音高/时值」并列，说明 `tip` 属于 C3 的出参范围。

### 2.1 实测到的 `lyrics_json` 现状（142 条，11 个唱段，2026-09-28）

**字段名是一致的**：`word` / `midi` / `start` / `end`，外加可选的 `note`、`tip`。第 27 条说的「三种互不兼容的形状」，差别不在名字，在**哪些键存在**：

| 条数 | 键集合 | 出现在 | 说明 |
|---|---|---|---|
| 8 | `word, start, end` | seg 78 | 标点。**直接没有 `midi` / `note` 键**，不是 `null` |
| 66 | `word, midi, start, end, note` | seg 78–80 | |
| 34 | `word, midi, start, end, tip` | seg 102–108 | 无 `note`，是录入没填全 |
| 34 | `word, midi, start, end, note, tip` | seg 1 | 两者都有 |

另外：`midi` 有 8 条缺失（全是标点），`start` / `end` **无一缺失**。

**`note` 混了两套词表**（共 102 条有条目有 `note`）：

| 词表 | 取值（条数） | 合计 |
|---|---|---|
| `NOTE_*` | `NOTE_8`(46) `NOTE_16`(21) `NOTE_4`(13) `NOTE_DOT_16`(10) `NOTE_2`(7) `NOTE_1`(1) `NOTE_DOT_8`(1) `NOTE_DOT_32`(1) | 100 |
| MusicXML | `half`(1) `quarter`(1) — **仅在 seg 1** | 2 |

**附点 12 条**（`NOTE_DOT_16` 10、`NOTE_DOT_8` 1、`NOTE_DOT_32` 1），**全部集中在 seg 79 与 seg 80**（各 6 条：79 是 `NOTE_DOT_8`×1 + `NOTE_DOT_16`×5，80 是 `NOTE_DOT_32`×1 + `NOTE_DOT_16`×5）。**seg 78 一条附点都没有**——所以验附点必须切到 seg 79/80，在 seg 78 上是验不到的。

`note` 与 `tip` **语义正交**（seg 1 两者都有），不是二选一。

### 2.2 前端要的又是另一套

`annotation.html` 的 `LYRICS` mock 是 `{char, pitch, note, start, duration}`，`note` 取值 `"8"/"4"/"2"/"16"/"1"`，且：

- 靠 `item.pitch === null` 判标点（`.punct` 样式 + 不挂 `onclick`）——所以缺失的 `midi` **必须显式补成 `null`**，`undefined === null` 为 `false`，否则标点会渲染成一个带音高、可点击的坏格子
- `note` 只用于显示「时值: 1/8拍」，前端只有 1/1、1/2、1/4、1/8、1/16 五档，**没有附点档**
- `duration` 字段目前**前端一处都没读**（只有 `start` 被读）。仍然返回它——它与 `start` 是天然的一对，且以后画时间轴要用

### 2.3 本轮定的四件事（用户逐条确认）

| 决定 | 口径 |
|---|---|
| **字段名** | 库不动，C3 出参映射成前端名（`word→char`、`midi→pitch`、`end-start→duration`）。前端零改动 |
| **`note` 词表** | 统一成 `NOTE_*`，`half→NOTE_2`、`quarter→NOTE_4` |
| **附点** | 前端加档显示，乐理信息不丢 |
| **`tip`** | 进 C3 出参 |

## 3. 接口契约

```
GET /api/segments/<int:segment_id>        权限：登录（@login_required）
```

统一信封，`data` 是**对象**：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "id": 78,
    "seq": 1,
    "title": "第一段",
    "duration": 24.7,
    "lyrics": [
      {"char": "辕", "pitch": 64,  "start": 0.0,   "duration": 0.234, "note": "NOTE_8", "tip": null},
      {"char": "门", "pitch": 66,  "start": 0.234, "duration": 0.234, "note": "NOTE_8", "tip": null},
      {"char": "，", "pitch": null, "start": 4.219, "duration": 0.0,   "note": null,     "tip": null}
    ]
  }
}
```

### 3.1 出参字段

| 字段 | 来源 | 可空 | 说明 |
|---|---|---|---|
| `id` | `segments.id` | 否 | |
| `seq` | `segments.seq` | **是** | |
| `title` | `segments.title` | **是** | |
| `duration` | `segments.duration` | **是** | **唱段时长**（秒）。与 `lyrics[].duration`（单字时长）同名不同义，靠层级区分 |
| `lyrics` | `segments.lyrics_json` | 否 | 数组，无歌词时是 `[]`，**不是 `null`** |

三列可空字段一律 `| None`（同 C1/C2 的理由：库里只要有一行空值，写成非空就整片 500）。

**不返回** `demo_id`：调用方从 C2 过来，本来就知道（同 C2 不返回它的理由）。**不返回**原始 `lyrics_json` 字符串——那是个 JSONB 列的内部表示，出参给结构化数组。

### 3.2 `lyrics[]` 的读时映射

`lyrics_json` 的每条按键映射，**逐字**：

| 库 | 出参 | 规则 |
|---|---|---|
| `word` | `char` | 直传。`word` 缺失或非字符串 → **该字整条丢弃**（构造不出 `char`，前端渲染不出来） |
| `midi` | `pitch` | **键缺失 → `null`**。见 2.2：前端靠 `pitch === null` 判标点 |
| `start` | `start` | 直传，缺 → `null` |
| `end` − `start` | `duration` | 计算得出。两者任一缺失 → `null`；标点是 `end == start` → `0.0` |
| `note` | `note` | **原样传 `NOTE_*`**，不做分数串映射（`"8"` 是前端显示词表，见 3.4） |
| `tip` | `tip` | 键缺失 → `null` |

`lyrics_json` 为 `null`（解析产出的新段落就是这样，见 `DOC_ISSUES` 第 20 条）→ `lyrics: []`。**这是常态不是边角**，前端必须有对应空态。

条目不是对象（理论上不该有，但 JSONB 列没有约束）→ 跳过该条，不让整个接口 500。

### 3.3 边界

| 情况 | 响应 |
|---|---|
| `segment_id` 存在 | `200` + 对象（`lyrics` 可能是 `[]`） |
| `segment_id` 不存在 | `404` + `{"code":404,"message":"唱段不存在"}` |
| 路径不是整数（`/api/segments/abc`） | `404`，**在路由层**由 `<int:segment_id>` 挡下，不进视图 |

与 C2 一致：**「存在但没有歌词」是 `200` + `[]`，不是 404**。

### 3.4 `note` 的分数串映射由前端做

后端只保证「词表统一成 `NOTE_*`」，不决定怎么显示。`NOTE_8` → 「1/8」这一步在前端。理由：`NOTE_8` 是**领域取值**（乐理时值），`"8"` 是**显示词**（UI 措辞），两件事。C1 立过同样的规矩（`elo_difficulty` 如实返回、不做 0–1 兜底）。

## 4. 词表归一落到数据层

只改接口层的话，库里仍是两套词表，下一个人读库照样踩。`half`/`quarter` 只在 **seg 1**，来自 `seed.sql`，所以两处一起改：

1. **`seed.sql` 第 33–35 行**：`"note":"half"` → `"note":"NOTE_2"`，`"quarter"` → `"NOTE_4"`
2. **真库 seg 1 那 1 行**：跑一次性的归一脚本（不引 Alembic，`CLAUDE.md` 明令）

归一脚本按「值」而不是按「下标」匹配（`half`/`quarter` 各自唯一），并在结尾断言**恰好改了 2 处**——下标法一旦 `lyrics_json` 被重排就会静默改错字。

改完跑 `scripts/check_db.py` 应当无新增差异（它比对表结构，不看数据内容）。

## 5. 页面调用（`annotation.html`）

### 5.1 删掉两个 mock

- **`LYRICS`**（第 537–571 行，66 条）：歌词网格改读 `let lyrics = []`
- **`EXISTING_ANNS`**（第 573–586 行，12 条）：它的 `index` 指的是 **mock 数组**的下标，`char` 是 mock 里的字（炮/雷/保/冠…）。真歌词一进来这 12 条全指向错字。删掉，`annotations` 改为 `let annotations = []`

删而不是留：留下一半比删掉更糟——一个按 mock 下标索引、却渲染在真数据上的标注列表，看起来像真数据。

### 5.2 状态与渲染

```
let lyrics = [];        // 当前唱段的逐字数据（C3 出参 data.lyrics）
let lyricReqToken = 0;  // 竞态守卫（同 C2 的 segReqToken）
```

不做「已加载过就跳过请求」的缓存：切唱段是低频操作，而缓存要额外维护一份 id→lyrics 的映射，还可能因为 `lyrics_json` 被后台改动而显示陈旧数据。少一个状态少一个错。

`renderLyrics()` 从 `LYRICS` 改读 `lyrics`；其余逻辑（`.punct` 判定、行内换行、`hasAnn` 标记）不变。

**分句换行**：现有逻辑是 `["，","。"].includes(lyrics[idx-1].char)`。真数据里标点**是**独立条目（seg 78 有 8 条），所以这套逻辑直接可用，不需要新写。但只有 seg 78 有标点，其余唱段会渲染成一整行不断句——**这是数据现状，不是渲染缺陷**，本轮不补。

### 5.3 `switchSegment(idx)` 扩展

现有实现只切高亮 + toast。追加：

1. 重置标注区状态：`selectedIndex = -1`、`selectedTag = null`、`bigChar` 回 `—`、`charInfo` 回「点击左侧歌词字进行标注」、`charMeta` 隐藏、`annotateControls` 的 `pointer-events` 回 `none`、`depsPanel` 移除 `.show`（全部照第 480–507 行的初始值）
2. `annotations = []`，重渲染标注面板
3. `lyrics = []`，重渲染网格为空态「歌词加载中…」
4. **不 await**：调 `fetchLyrics(s.id)`，高亮与 toast 不等它
5. toast 文案去掉「歌词网格待接入（C3 未实现）」——本轮之后它是假话了

同 C2：**toast 不能说「已加载新唱段数据」**这类笼统话；文案点明唱段名即可。

### 5.4 `fetchLyrics(segmentId)`

- `fetch(\`/api/segments/${segmentId}\`, { credentials: 'same-origin' })`（同源相对路径，理由同 C1/C2）
- `let lyricReqToken = 0` + 自增序号守卫，**判定在 `await` 之后**（同 C2 的 `segReqToken`，切唱段同样会连点）
- 成功 → `lyrics = data.lyrics`，`renderLyrics()`
- `lyrics` 为空数组 → 网格显示「该唱段暂无歌词」（`lyrics_json` 为 NULL 的新段落会大量命中）
- 失败 → 网格显示「歌词加载失败」，不弹 toast、不打断页面

三种空态都渲染成 `<span class="piece-empty">…</span>` 放进 `#lyricsGrid`，复用已有样式。

### 5.5 时值显示（新增 `noteLabel(note)`）

把 `NOTE_*` 映射成中文分数串，**共 11 档**（5 个基本 + 3 个附点 + 未知兜底 + `null`）：

| 取值 | 显示 |
|---|---|
| `NOTE_1` | `1/1 拍` |
| `NOTE_2` | `1/2 拍` |
| `NOTE_4` | `1/4 拍` |
| `NOTE_8` | `1/8 拍` |
| `NOTE_16` | `1/16 拍` |
| `NOTE_32` | `1/32 拍` |
| `NOTE_DOT_2` / `NOTE_DOT_4` / `NOTE_DOT_8` / `NOTE_DOT_16` / `NOTE_DOT_32` | 对应基本档 + ` 附点拍` |
| `null` / `undefined` | `—` |
| 其它（库里没有，但不让页面挂） | 原样显示该字符串 |

**替换两处**内联的嵌套三元——`renderLyrics` 第 632 行与 `selectChar` 第 653 行（两处是逐字重复的同一段代码）。它们只认 `"16"/"8"/"4"/"2"` 四个值，**遇到 `NOTE_8` 会一路落到兜底的 `"1/1"`，把 1/8 拍显示成 1/1 拍**。当前之所以看不出问题，只是因为喂进去的是 mock 的 `"8"`；C3 一接真数据就会当场显示错。

## 6. 验证

项目**没有测试框架**（无 pytest、无 `tests/`），按仓库既有做法手工验证。种子账号 `teacher01` / `stu001`，密码 `xiyun@2026`。

接口部分：

1. 未登录 → `401`
2. **学生账号能访问**（没误加教师限制）
3. seg **78** → `lyrics` 长 **66**，第 1 条是 `{"char":"辕","pitch":64,"start":0.0,"duration":0.234,"note":"NOTE_8","tip":null}`
4. seg 78 的**标点**（如第 5 条附近的 `，`）→ `pitch: null`、`note: null`、`tip: null`、`duration: 0.0`，`char` 是标点本身
5. seg **1** → `lyrics` 长 **2**，`note` 是 `NOTE_2` / `NOTE_4`（**归一后**），两条都有 `tip`
6. seg **102** → `lyrics` 长 **6**，6 条的 `note` **全为 `null`**、`tip` **全有值**（34 条 `tip`-only 形状的代表，另 2 条 tip-only 在 seg 1）
7. seg **106** → `lyrics` 长 **4**，同上形状；顺带确认各唱段条数与基线一致：1→2、78→66、79→28、80→14、102→6、103→4、104→6、105→3、106→4、107→3、108→6
8. **附点**：切到 seg **79** 与 **80**（各 6 条，**seg 78 没有附点，在 78 上验不到**）。核对 `note` 原样是 `NOTE_DOT_16` / `NOTE_DOT_8` / `NOTE_DOT_32`，**没有被截成 `NOTE_16`**
9. `segment_id=99999` → `404` + 「唱段不存在」
10. `/api/segments/abc` → `404`（路由层）
11. 每个 `lyrics[]` 条目**恰好 6 个键**：`char / pitch / start / duration / note / tip`
12. 出参**没有** `demo_id`、**没有** `lyrics_json`
13. 全库 11 个唱段逐个跑一遍，**没有一个 500**（这条最重要——JSONB 里的脏条目最容易让某个唱段单独炸）
14. 造一个 `lyrics_json` 为 `NULL` 的段落，确认回 `200` + `lyrics: []`（**验证完删掉这行**）

页面部分（用 `/browse` 技能）：

15. 默认选中 demo 1 → seg 1 → 歌词网格 2 个字（海、岛），时值显示 `1/2 拍` / `1/4 拍`
16. 切到 demo 16（5 段）→ 切到第 1 段 → 网格 66 格，首字「辕」，时值 `1/8 拍`
17. **标点格子**有 `.punct` 类且**点了没反应**（不弹标注面板、`bigChar` 不变）
18. 切唱段后标注面板**归零**：`bigChar` 是 `—`、`charInfo` 是「点击左侧歌词字进行标注」、`charMeta` 隐藏
19. 点某个字 → 面板显示「音高: 64 (E4)」「时值: 1/8 拍」
20. 快速连点两个唱段 → 最终网格属于**后点**的那个（竞态守卫生效）
21. 降级：临时把 URL 改错，确认网格显示「歌词加载失败」且页面其余部分可用；**验证完改回并确认无残留**

## 7. 收尾

- `python scripts/check_db.py` 应只剩既有漂移（`demo_versions` + `teacher_demos` 三列）。本轮不改模型与 `schema.sql`，只改 seg 1 的**数据**
- 更新 `DOC_ISSUES.md` 第 27.2 节：本轮已定下的四件事写进去（词表统一成 `NOTE_*`、标点以「无 `midi` 键」表示、`tip` 与 `note` 正交、附点在前端加档），并**更正**「库里没有标点条目」那句——seg 78 有 8 条

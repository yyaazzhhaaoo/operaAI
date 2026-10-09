# 实时跟唱页（`sing_along.html`）曲目列表与示范播放 实现设计

日期：2026-10-09 ｜ 状态：已评审待实现 ｜ 关联：《5-接口清单》2.3 节 C1/C2/C3、2.2 节 B5；`DOC_ISSUES.md` 第 19、20、26、27 条

## 1. 背景与目标

`sing_along.html`（学生练习 · 实时跟唱）当前**完全不调业务后端**：曲目下拉是写死的 3 个 `<option>`，段落列表与逐字歌词读页面内的 `PIECES` 常量（`:627-743`），「播放示范」是一个 `performance.now()` + `requestAnimationFrame` 的**纯模拟动画**（`:1306-1340`），从头到尾没有发出过一个声音。全页唯一的网络请求是顶部登录用户条的 `/api/auth/me`。

本轮把「曲目列表」与「播放示范」两件事接上真接口与真实音频。

**目标**：

1. 曲目下拉从 `GET /api/demos`（C1）拉取并渲染
2. 切换曲目后，段落列表从 `GET /api/demos/<id>/segments`（C2）拉取
3. 选中段落后，逐字歌词与教师提示从 `GET /api/segments/<id>`（C3）拉取，据此重画音高画布
4. 点「播放示范」播放该曲目的真实示范音频（经 B5 流式接口），进度条与时间显示由音频 `currentTime` 驱动

**关键前提（决定了本轮所有取舍）**：**段落没有自己的音频**。`segments` 表只有 `duration` 与 `lyrics_json`，音频挂在曲目级的 `teacher_demos.audio_id`。所以「播放示范」只能播整首，无法做到「播当前段落那一段」。

## 2. 文档给的 vs 库里有的

### 2.1 接口

《5-接口清单》2.2/2.3 节相关四条（均**已实现**，本轮不改后端一行）：

| 编号 | 方法 + 路径 | 权限（已落地） | 说明（原文） |
|---|---|---|---|
| C1 | `GET /api/demos` | 登录 | 曲目列表（陪练选曲 + 作业布置用） |
| C2 | `GET /api/demos/<id>/segments` | 登录 | 分段列表 |
| C3 | `GET /api/segments/<id>` | 登录 | 段落详情，含 `lyrics_json` |
| B5 | `GET /api/audio/<file_id>` | 登录 | 经 access 规则校验后 `send_file`，禁止静态直出 |

C1/C2/C3 的响应字段文档**全部未定义**（只有一句话说明），契约是代码侧自拟的，登记在 `DOC_ISSUES.md` 第 26、27 条。本轮以**代码现状**为准。

### 2.2 库里真实数据（2026-10-09 实测）

| demo id | 曲目 | 音频 | 时长 | 分段数 |
|---|---|---|---|---|
| 16 | 《穆桂英挂帅》· 辕门外三声炮 | 有（public） | 111.93s | 10 |
| 17 | 《贵妃醉酒》· 海岛冰轮初转腾 | 有（public） | 44.7s | 3 |
| 18 | 《霸王别姬》· 看大王在帐中 | 有（public） | 38.5s | 2 |
| 15 | `01_xipi_1931` | 有 | 182.80s | **0** |
| 19 | 《红娘》· 叫张生隐藏在棋盘之下 | 有 | 28.3s | **0** |
| 1 | 贵妃醉酒·选段 | **无** | — | 1 |

- 16/17/18 正好对应当前硬编码的三首——**说明现在页面里的 `PIECES` 就是从库里抄出来的**。
- 16/17/18 的 16 个分段 `lyrics_json` **全部非空**，形状为 `[{word, midi, start, end, note, tip}]`，其中 94 条逐字条目带 `tip`。样例：`{"word":"看","midi":62,"start":0.0,"end":0.6,"note":"NOTE_DOT_16","tip":"平稳行腔，咬字清楚"}`。
- 真实段落时长是 **19.48s / 11.12s** 这个量级，不是硬编码里的 2.8s。
- demo 17/18 里混着解析残留的「第一段」（时长等于整曲），与手工分段并存。

### 2.3 字段缺口（本轮要处理的）

C3 的 `lyrics[]` 给 `char / pitch / start / duration / note / tip`，页面现用到 6 个字段，其中 4 个有对应、2 个无来源：

| 页面现用 | C3 对应 | 处理 |
|---|---|---|
| `ly.char` | `char` | 直接用 |
| `ly.teacherPitch` | `pitch`（`null` = 标点） | 改名 |
| `ly.start` | `start`（可空） | 直接用，需判空 |
| `ly.dur` | `duration`（可空） | 改名 + 判空 |
| `ly.pinyin` | **无** | **删掉画布上的拼音行**（`:854`） |
| `seg.coachingTips[].tip` | 逐字的 `tip` | 直接读 `ly.tip`，不再按字查表 |

另有两处无来源，一并删除：

- **`seg.subtitle`**（`:1034`、`:1045`、`:1053`）：库里 `segments.title` 本身就是唱词（如「辕门外三声炮如同雷震」），没有「段落 1 + 副标题」这层结构。改用 `seq` + `title`。
- **`PIECES[key].bpm` / `.key`**：全页**只定义、从不读取**，随 `PIECES` 一起删。

`seg.completed` 同样从不被赋值（恒为 `undefined`），段落状态恒显「待练习」——这不是 bug，本轮维持。

### 2.4 音频 url 的来源

C1 的响应是 `{id, title, role, banshi, duration, elo_difficulty, segment_count}`，**不含音频地址**，也没有 `audio_id`。带 url 的是：

```
GET /api/demo/library/<int:demo_id>   → data.url = url_for("api.audio_download", file_id=demo.audio_id)
```

该接口只需 `@login_required`（`app/api/demo_library.py:79-81`），**学生可以调**。

**口径**：前端在**首次点「播放示范」时**懒加载该接口取 `url`，同一曲目缓存不再重复请求。

这是一个有意识的取舍——`/api/demo/library/*` 语义上属于「示范库管理」，被陪练页复用略勉强（其 `status` / `created_at` / `elo_difficulty` 字段本页一概忽略）。另一条路是给 C1 加 `url` 字段，但那要改已落地的接口契约并追加 `DOC_ISSUES` 条目。**选前者：零后端改动、零文档变更，代价是每首曲目多一次请求。**

### 2.5 `elo_difficulty` 的坑

库里该列是**未标定的默认值 1000**，而前端页面按 0–1 渲染（`DOC_ISSUES` 第 19 条）。本轮下拉框**只显示 `title`**，不显示难度，因此**不触碰这个坑**——这是本轮维持下拉框形态（而非改造成卡片列表）的一个附带理由。

## 3. 调用链

全部同源相对路径（`credentials: 'same-origin'`），经 nginx 代理到 Flask，**不写 `location.host + ':8877'`**（跨源请求默认不带 Cookie，后端 `login_required` 只会回 401——同 `pitch_comparison.html` 的教训）。

```
页面加载
  └─ GET /api/demos                          → 填充 #pieceSelect
切换曲目 (changePiece)
  └─ GET /api/demos/<demoId>/segments        → renderSegments()
选中段落 (selectSegment)
  └─ GET /api/segments/<segmentId>           → currentLyrics → 画布 + 教师提示
首次点「播放示范」(playDemo)
  └─ GET /api/demo/library/<demoId>          → audioUrl（懒加载 + 按 demoId 缓存）
        └─ <audio src=audioUrl> 播放
```

## 4. 前端改造点

### 4.1 删除与新增

- **删除整个 `PIECES` 常量**（`:627-743`）。
- 新增模块级状态：`demos`（C1 列表）、`segments`（C2 列表）、`currentLyrics`（C3 的 `lyrics` 数组）、`audioUrlCache`（`{demoId: url}`）。
- `currentPiece` 由字符串 key（`"mu"`）改为 **`currentDemoId`（数字）**；`currentSegmentIdx` **保留下标语义**（全页十余处依赖它），需要 id 时取 `segments[idx].id`。

### 4.2 逐函数改动

| 函数 | 改动 |
|---|---|
| `init()` `:1406` | 改为 async：先 `await loadDemos()`，其余（画布、空态、日志）不变 |
| `changePiece()` `:1382` | 取 `#pieceSelect.value` 的数字 demoId → `loadSegments(demoId)` |
| `renderSegments()` `:1023` | 改读 `segments`；副标题去掉、改显 `seq` + `title`；**`duration` 判空**（见 §5） |
| `selectSegment(idx)` `:1040` | 改 async：`await loadLyrics(segments[idx].id)` 后再 `prepareTeacherCurve` / `renderTeacherTips` |
| `prepareTeacherCurve(seg)` `:1055` | 入参改为 C3 的 `lyrics` 数组；`ly.teacherPitch`→`ly.pitch`、`ly.dur`→`ly.duration`；**跳过 `pitch === null` 的标点** |
| `drawLyricsAndGrid()` `:825` | 去掉 `ly.pinyin` 那一段（`:849-855`）；其余不变 |
| `renderTeacherTips(seg)` `:998` | 改吃 C3 的 `lyrics`，直接读 `ly.tip`；删掉 `coachingTips` 查表逻辑 |
| `recordLoop()` `:1136` | `ly.dur`→`ly.duration`、`ly.teacherPitch`→`ly.pitch`；`showCoaching` 的 tip 改从 `ly.tip` 读 |
| `updateMetrics()` `:1185` | `ly.teacherPitch`→`ly.pitch`（其余模拟逻辑不动） |
| `playDemo()` `:1306` | **整段重写**（见 §4.3） |
| `stopAll()` `:1345` | 增加 `audio.pause(); audio.currentTime = 0` |
| `updateProgress(elapsed)` `:1248` | 分母由 `segmentDuration` 改为音频总时长（见 §4.3） |

### 4.3 播放（`playDemo` 重写）

用游离的 `new Audio()` 实例，不往 DOM 里塞 `<audio>` 元素（页面没有播放器控件的设计位，一切播控都走既有的 `btnPlayDemo` / `btnStop`）：

```js
const demoAudio = new Audio();
demoAudio.preload = 'none';
```

- **放开「必须先选段落」**：播放的是整首，与段落无关。改为「选中曲目且该曲目有音频即可播」；未选段时画布维持空态，音频照常播。
- 取 url：`audioUrlCache[demoId] ??= (await GET /api/demo/library/<demoId>).data.url`。`url` 为 `null`（曲目无音频，如 demo 1）→ `addLog` 提示 + 本次不播。
- 播放：`demoAudio.src = url; await demoAudio.play()`。
- `timeupdate` → `progressFill` 宽度、`timeCurrent`/`timeTotal` 由 `demoAudio.currentTime`/`.duration` 驱动。**`timeTotal` 的初值由 `loadedmetadata` 事件给**（`play()` 返回时 `duration` 常还是 `NaN`）。
- `ended` → `stopAll()`。
- `isPlaying` 语义改为「音频正在播」，按钮禁用逻辑沿用现有 `btnPlayDemo` / `btnRecord` / `btnStop` 的显隐规则。
- **播放期间画布不动**（按已确认口径）：不画播放头、不推 `currentWordIndex`。原 `demoLoop()` 的 `requestAnimationFrame` 循环整段删除。

### 4.4 画布

- `prepareTeacherCurve` 之后画布即静态呈现该段的目标音高曲线与歌词，作为「唱前参照」。
- `drawPlayhead` / `syncCurrentTime` 仍只服务于跟唱录制模拟，本轮不改。

## 5. 容错口径

以下每条都在库里存在真实触发数据，不是假想边角（延续 `demo_library.html` 的教训：一个 `null` 上的 `.toFixed()` 会抛 TypeError 打断整张列表的 `map`，整页渲染不出来）。

| 情况 | 真实数据 | 处理 |
|---|---|---|
| `seg.duration` 为 `null` | C2 的 `seq/title/duration` 三列在 DDL 上均可空 | `renderSegments` 判定「非有限数 → 显示『时长未知』」，**不得直接 `.toFixed`** |
| `lyrics: []`（`lyrics_json` 为 NULL） | 解析产出的新段落常态（`DOC_ISSUES` 第 20 条） | 画布空态 + 提示「该唱段还没有歌词数据」；教师提示区显示空态文案 |
| `segment_count === 0` | demo 15、19 | 分段区显示「该曲目还没解析出唱段」。**不置灰下拉项**——C1 不过滤零分段曲目，判定留给前端 |
| 曲目无音频（`url === null`） | demo 1 | 点播放时提示「该曲目没有示范音频」并 `addLog`；随后把 `btnPlayDemo` 置为 `disabled` |
| 任一 fetch 失败 / 非 2xx | — | `addLog` 记录 + 保持上一次数据或空态，不白屏 |
| 401 | — | 由顶部登录条的既有逻辑接管（`location.replace('/login.html')`） |

`lyrics[]` 中 `start` / `duration` 为 `null` 的条目（标点判定之外的脏数据）同样跳过，不让一条脏数据打断整条曲线构建。

## 6. 非目标（明确不做）

- **录制跟唱与评分流程不动**。`toggleRecord()` / `recordLoop()` / `simulateAnalysisAfterRecord()` 仍是模拟生成（页面本来就只标注了「真实现实录音 UI」）。本轮的改动仅限于它们读取的字段名与来源。
- **不接 D1/D2/D3**（练习提交、练习日志、上次结果回显）。
- **不接 C4–C7**（歌词级标注）。
- **不做段落级音频**——后端无此数据（§1 的关键前提）。也不去猜「分段按序累加铺满整曲」来切片：库里 demo 17/18 的残留「第一段」会让累加和超过总时长（51.2s vs 44.7s），切片位置必然错。
- **不做「已完成」状态**：C2 不返回，段落恒显「待练习」。
- **不改后端**：不动 `app/`、`schema.sql`、`app-d.py`，不引入新依赖。
- **不改设计 token 或侧边栏**：本页不新增页面，不触及跨页样式同步。

## 7. 验证方式

项目无测试框架，按惯例用临时脚本 + `curl` 验链路，再起服务用浏览器点一遍：

1. **接口链路**：带登录 Cookie 依次 `curl` 四条接口，确认 C1 返回 6 条、C2 对 demo 16 返回 10 条、C3 对段 110 返回 10 个逐字条目、`/api/demo/library/16` 返回 `url`。
2. **浏览器正路**：`teacher01` 与 `stu001` 各登录一次（C1/C2/C3 只要求登录，学生应能全程走通），依次切 16/17/18，确认下拉、分段、歌词、教师提示、音频播放与进度条正常。
3. **边角**（必须实测，不能只看代码）：
   - demo 19（零分段）→ 分段区显示「还没解析出唱段」，不报错、不白屏
   - demo 1（无音频）→ 点播放给出提示，页面不崩
   - 断开后端 → 页面给出失败日志与空态，不白屏
4. **字段确证**：确认播放的画布**不出现拼音行**，「已完成」状态未出现，`PIECES` 常量已从文件中消失。

## 8. 风险与遗留

- **接口复用**：`/api/demo/library/<id>` 被陪练页复用（§2.4），其命名与「示范库管理」绑定，未来若该接口收紧权限（如加 `@teacher_required`），本页会当场失效。此处登记，不预订后续。
- **示范音频是整首**，与学生「跟着这一句唱」的直觉有落差。真要按段播，需要在 `segments` 上加起止时间或独立音频，属数据模型变更，本轮不碰。
- **demo 17/18 的残留「第一段」**（时长等于整曲）会在段落列表里显示为一个超长段落。这是库里数据问题，页面如实展示、不做隐藏。

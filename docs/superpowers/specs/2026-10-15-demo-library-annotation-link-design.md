# 示范库「标注」按钮接入歌词级标注页 实现设计

日期：2026-10-15 ｜ 状态：已评审待实现 ｜ 关联：《3-功能清单》模块 9、模块 10；《5-接口清单》2.3 节 C1–C7

## 1. 背景与目标

`demo_library.html` 每张示范卡片右下角有「标注」「版本」两个按钮（`:1787-1788`），但 `annotateDemo()` 只弹一个 toast（`:2174`），点完什么都不会发生——这是页面里最后一个纯占位入口。

**本轮只做一件事**：把「标注」按钮接到已经存在的歌词级标注页 `annotation.html`，并让跳过去之后**自动定位到刚才点的那条示范**。

**关键前提（决定了本轮范围）**：这条链路的两端**都已经实现完了**，本轮不写后端、不写标注页业务逻辑：

| 环节 | 状态 | 位置 |
|---|---|---|
| C1 `GET /api/demos` 曲目列表 | ✅ 已实现 | `app/api/demos_segments_annotations.py:23` |
| C2 `GET /api/demos/<id>/segments` 分段列表 | ✅ 已实现 | 同上 `:37` |
| C3 `GET /api/segments/<id>` 段落详情 | ✅ 已实现 | 同上 `:51` |
| C4 `GET /api/segments/<id>/annotations` 读标注 | ✅ 已实现 | 同上 `:67` |
| C5 `POST /api/annotations` 新增标注 | ✅ 已实现 | 同上 `:84` |
| C6 `DELETE /api/annotations/<id>` 删除标注 | ✅ 已实现 | 同上 `:113` |
| C7 `GET /api/annotations/rules` 全库规则 | ✅ 已实现 | 同上 `:143` |
| `annotation.html` 页面（含选曲目/选段/增删标注/规则表） | ✅ 已全部接真数据 | `annotation.html:766/877/937/1010/1092/1131/1202` |

唯一的缺口是**入口接线**：`annotation.html` 不支持任何 URL 参数，加载后写死走 `switchPiece(first)`——选中「第一个有分段的曲目」（`:975-976`）。所以就算手工敲地址过去，也落不到你刚才点的那条示范上。

## 2. 缺口核实（2026-10-15 实测）

| 事实 | 证据 |
|---|---|
| `annotateDemo` 全项目只有一处定义、一处调用 | `demo_library.html:2174`（定义）、`:1787`（卡片 `onclick`） |
| `annotation.html` 不读 `location.search` | 全文件无 `URLSearchParams` 用于入参（`:1194` 那处是 C7 的**出参**查询串） |
| C1 与示范库列表**同源同 id** | `library_service.demo_list:35` 与 `demo_library_list:59` 都出自 `teacher_demos`，`id` 就是 `demo.id` |
| `switchPiece(idx)` 收的是**渲染下标**不是 `demo_id` | `annotation.html:982` 读 `demos[idx]`；`demos` 由 C1 结果按 id 升序填充（`:956`） |
| 选中曲目后分段会自动落第一个 | `fetchSegments` 末尾 `switchSegment(0)`（`:1041`） |
| 侧边栏已互链 | `demo_library.html:1256` 有指向 `annotation.html` 的导航项，跳过去之后能原路返回 |

库里现状（`docker exec docker_postgres psql` 实测）：`teacher_demos` 共 **3 条，全部有 10 个分段**。也就是说**当前数据触发不到「未解析」分支**，但该分支仍须写对——示范库存在 `parsing` 状态的上传（`demo_library.html` 处理中弹窗那条路径），且 C1 明确「不过滤 `segment_count = 0` 的曲目」（`library_service.demo_list:29`）。

## 3. 设计

### 3.1 `demo_library.html`：把 toast 换成真跳转（改 1 行）

```js
function annotateDemo(id) { location.href = `annotation.html?demo_id=${encodeURIComponent(id)}`; }
```

- **同页跳转**，不用 `window.open`：与全站导航惯例一致（侧边栏一律普通 `<a href>`），且 `annotation.html` 侧边栏有链回示范库的项，回去不用重进页面。
- `encodeURIComponent` 是防御性的：真实链路 `d.id` 是数字，但 `renderDemoList` 是拼 `onclick="annotateDemo('${d.id}')"` 字符串（`:1787`），值得把值当成不受信文本处理。
- **不弹 toast**：页面立刻切走，弹窗没人看得见。

### 3.2 `annotation.html`：深链优先，失效回退（改 `fetchDemos` 末尾 3 行）

把 `annotation.html:975-976` 的

```js
const first = rows.findIndex(d => d.segment_count > 0);
if (first >= 0) switchPiece(first);
```

换成

```js
// 深链失效时回退到第一个可标注曲目，与加参数之前的行为一致。
// hit 只判「这条示范在不在」，与「能不能标注」分开：文案说的是「尚未解析出
// 分段」，套在 id 不存在/非数字上就是在说假话（同本文件 :951 的口径）
const raw = new URLSearchParams(location.search).get("demo_id");
const hit = rows.findIndex(d => d.id === Number(raw));
const idx = hit >= 0 && rows[hit].segment_count > 0 ? hit : -1;
const first = rows.findIndex(d => d.segment_count > 0);
if (idx >= 0) switchPiece(idx);
else if (first >= 0) {
  switchPiece(first);
  if (hit >= 0) showToast("info", "该示范尚未解析出分段", "已切换到其他曲目");
}
```

要点：

- `Number(null)` 与 `Number("abc")` 都是 `NaN`，`findIndex` 不会命中任何行 → **无参数时行为与现在逐字一致**，不需要显式判空分支。
- **`hit` 与 `idx` 必须分成两个变量**（初版设计只用一个 `idx` + `raw !== null` 判是否有参数，实现时发现不成立）：`?demo_id=abc` 与 `?demo_id=999999` 的 `raw` 也**非 null**，会被那个条件判成「带了参数却标不了」而弹出「尚未解析出分段」——可这两个 id 根本不存在，那句文案是在说假话。改成按「示范在不在」（`hit`）决定弹不弹，文案才与事实相符。这与本文件 `:951`「拿不到」与「确实没有」不混成一句文案的口径一致。
- 深链命中的条件里带上 `segment_count > 0`：这条正是「未解析的示范跳过来怎么办」的答案（见 3.3）。
- 不改 `fetchDemos` 的异常路径（`:941-948`）与空列表路径（`:950-954`）：那两处根本不走到这里。
- `if (first >= 0)` 守卫保留：一条可标注的曲目都没有时（`first === -1`）不调 `switchPiece`，与改动前一致。

### 3.3 边界：深链指向「未解析」的示范 → 回退 + 说明

演示库里 `status: "parsing"` 的条目、以及任何 `segment_count === 0` 的曲目，点了「标注」跳过来后**回退到第一个可标注曲目**，并 toast 说明发生了什么。

理由：用户点「标注」的目的就是去标注。落在一条标不了的曲目上（置灰、无歌词、无字可点）等于把用户丢进死胡同；回退到能标的，并告诉他为什么不是他点的那条，诉求即刻满足。

实现落点见 3.2 的代码：回退分支里补一次 `showToast("info", "该示范尚未解析出分段", "已切换到其他曲目")`，条件是 `hit >= 0`。

这个条件把三种情况分开：

| 输入 | `hit` | 行为 | 理由 |
|---|---|---|---|
| 无参数（侧边栏正常进页） | -1 | 静默回退 | 用户没点任何示范，弹窗是打扰 |
| `?demo_id=abc` / `?demo_id=999999` | -1 | 静默回退 | 参数是垃圾/指向不存在的数据，说「尚未解析出分段」与事实不符 |
| `?demo_id=<存在但未解析>` | ≥0 | 回退 + 提示 | 用户明确点了某条示范，得知道为什么不是它 |

判据落在「这条示范在不在库里」（`hit`），而不是「URL 有没有带参数」——后者的失效场景见 3.2 要点第二条。

### 3.4 学生端

无需额外处理。`demo_library.html` 的列表对学生直接渲染「示范库仅教师可见」、不渲染卡片（`:1654-1659`），因此学生根本看不到「标注」按钮。C4–C7 本身是 `@teacher_required`，越权场景由后端兜底。

## 4. 范围边界（本轮不做）

- **不做 `segment_id` 级深链**。示范库详情里的「唱段列表」（`demo_library.html:1862-1872`）目前是纯展示、不可点击，本轮不把它改成可点击入口，也不给它加深链。跳到标注页后落该示范的第一个分段（`switchSegment(0)`）即可。
- **不动后端一行**，不动 C1–C7。
- **不碰「版本」按钮**。版本管理的真实链路在库里只有一张漂移出来的 `demo_versions` 表、文档与 `schema.sql` 都没有它的位置，是另一件事。
- **不清理 `DEMO_DATA` / `fetchDemoDetail` 的 mock 分支**。虽然列表已不再产出 mock 条目、那段分支不可达，但它是既存死代码，不在本轮范围内。

## 5. 验证方案

无测试框架，按项目惯例用临时脚本 + 真接口 curl 验证：

1. **静态检查**：`grep` 确认 `annotateDemo` 不再含 `showToast`，`annotation.html` 的 `fetchDemos` 末尾出现 `URLSearchParams`。
2. **真链路 curl**：`/api/demos` 取真实 id 列表，确认 `d.id` 是数字、`segment_count` 字段存在（这是 `findIndex` 比较的前提）。
3. **页面夹具测试**（`/tmp/annlink/test.mjs`，`node:vm` + 假 DOM 跑页面**真正那个**主 `<script>` 块，零依赖）。`/api/demos` 的桩数据前 3 条是 psql 实测的真实行，第 4 条（`segment_count: 0`）是编造的——真实库 3 条全有分段，那条分支只能构造。

| 输入 | 期望曲目 idx | 期望唱段 idx | 期望深链 toast | 结果 |
|---|---|---|---|---|
| 无参数 | 0 | 0 | 0 | PASS |
| `?demo_id=16` | 0 | 0 | 0 | PASS |
| `?demo_id=25` | 2 | 0 | 0 | PASS |
| `?demo_id=999999` | 0 | 0 | 0 | PASS |
| `?demo_id=abc` | 0 | 0 | 0 | PASS |
| `?demo_id=99`（存在、无分段） | 0 | 0 | 1 | PASS |
| 全部曲目都无分段（`first === -1`） | -1 | -1 | 0 | PASS |

- **唱段 idx 一并断言**：`fetchSegments` 末尾会自动 `switchSegment(0)`（`:1041`），这是「深链只需定位到 demo」这一设计前提的实测证据。夹具的分段桩必须非空，否则走的是「该曲目暂无分段」分支、根本到不了 `switchSegment`。
- toast 断言**只数含「尚未解析出分段」的那条**：页面自身在选中曲目/唱段时也会弹 toast（`:993`/`:1076`），那是既有行为，不是本轮引入的。
- 第 1 条是无参数的回归保护：确认加参数前后行为逐字一致。

4. **后端字段核对**（已做）：`library_service.demo_list` 实测 `id` 为 `int`、`segment_count` 存在，`findIndex(d => d.id === Number(raw))` 的比较前提成立。

## 6. 待文档方确认

- **示范库与标注页的跳转关系，三份文档均未规定**：《3-功能清单》模块 10（示范库管理）只写「VocalParse 自动解析入库 · Elo 难度校准」，模块 9（歌词级标注）只描述标注页自身的 9.1–9.7，没有任何一处描述「从示范库某条示范进入标注」。本轮自拟的交互（卡片按钮跳转 + `?demo_id=` 深链 + 未解析回退）**需要文档方确认**。登记入 `DOC_ISSUES.md`。
- 该跳转关系的自拟口径不影响任何接口契约，`DOC_ISSUES.md` 第 43 条。

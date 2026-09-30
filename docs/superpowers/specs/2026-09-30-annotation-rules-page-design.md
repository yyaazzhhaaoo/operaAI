# 标注规则列表管理页面（功能 9.6 / C7）实现设计

日期：2026-09-30 ｜ 状态：已评审待实现 ｜ 关联：《3-功能清单》9.6、《5-接口清单》2.3 节 C7；`annotation.html`；`DOC_ISSUES.md` 第 32 条

## 1. 背景与目标

`GET /api/annotations/rules`（C7，见 `2026-09-30-annotation-rules-api-design.md`）已实现并验证，但**没有任何前端调用方**——本轮补上。

关键前提：《3-功能清单》的模块 9「歌词级标注」共七个功能点，**9.1–9.5 与 9.7 都已在 `annotation.html` 内实现**：

| 编号 | 功能点 | 现状 |
|---|---|---|
| 9.1 | 歌词网格展示 | `renderLyrics()`，真链路 C3 |
| 9.2 | 点击字选中标注 | `selectChar()` |
| 9.3 | 六种标注类型 | 六个 `.type-btn`，真链路 C5 |
| 9.4 | 量化容忍度滑块 | `#toleranceSlider` |
| 9.5 | 技法依赖图谱展示 | `renderDeps()` |
| **9.6** | **标注规则列表管理（集中展示+筛选）** | **缺** |
| 9.7 | 删除标注 | `deleteAnnotation()`，真链路 C6 |

所以 9.6 不是新模块，是**同一页上唯一缺的一块**——因此并进 `annotation.html`，不新建页面、不动其它 10 个页面的侧边栏。

**目标**：

1. 在 `annotation.html` 页尾新增一张通栏卡片，展示全库标注规则
2. 按 `tag` 与 `word` 筛选，**走 C7 的服务端参数**
3. 学生（403）优雅降级为「仅教师可见」

**非目标（明确不做）**：

- 不做分页、列排序、导出
- 不做行内编辑 / 删除（**只读展示**，"管理"体现在筛与看，改动回左侧单唱段标注区）
- 不做点行跳转、不与左侧歌词网格联动
- 不改 C4/C5/C6 的既有逻辑（唯一新增是 4.3 节说的「写成功后调一次 `fetchRules()`」）
- 不动后端、不动 `schema.sql`、不动其它任何 `.html`、不动 `:root` 设计 token

## 2. 页面现状（改动前）

`annotation.html` 共 1183 行，单文件自包含。主内容区结构：

```
<main class="main-content">                        (426)
  <div class="page-header">                        (441)
  <div class="piece-selector" id="pieceSelector">  (446)  曲目按钮，C1 渲染
  <div class="piece-selector" id="segmentSelector">(448)  唱段按钮，C2 渲染
  <div style="display:grid;...">                   (451)  两栏网格
    左：歌词网格 card
    右：标注面板 card（选中字 / 六类型 / 滑块 / 依赖图谱 / 已添加标注规则）
  </div>                                           (525)  ← 网格闭合
</main>                                            (526)
```

**整页作用域是「当前选中的那一个唱段」**：右侧那张卡的「📋 已添加标注规则」只含当前唱段（C4）。

页尾脚本在 1108–1110 行初始化：`renderLyrics(); renderAnnotations(); fetchDemos();`

### 2.1 两个必须知道的前提

**权限只管「登录」不管「教师」。** 页面级鉴权（`page_login_required`）只要求登录。页末脚本（1143 行）确实算了 `isTeacher`，但**只用于显示姓名与头像**，没有用它拦任何内容。所以**学生能打开这一页**，而 C7 挂 `@teacher_required`——学生会拿到 403。

**既有 fetch 的统一写法**（`fetchDemos` 880 行、`fetchAnnotations` 1075 行）：

```js
const r = await fetch(url, { credentials: 'same-origin' });  // 必须同源相对路径
const body = await r.json();
if (!r.ok || body.code !== 0) throw new Error(body.message || String(r.status));
rows = body.data || [];
```

`credentials: 'same-origin'` 不可省：写成 `location.host + ':8877'` 那种跨源地址时 fetch 默认不带 Cookie，后端只看得到空 session 并回 401（`CLAUDE.md` 与 `pitch_comparison.html:428` 都记过这个坑）。

`fetchAnnotations` 另有**竞态守卫**（`annReqToken`）：领号在 `await` 之前、判定在 `await` 之后。本轮的新请求照抄这套，但见 4.2。

## 3. 页内结构

在 525 行的 `</div>`（两栏网格闭合）与 526 行的 `</main>` 之间插入：

```html
<!-- 全库标注规则（功能 9.6 / C7 GET /api/annotations/rules） -->
<div class="card" style="margin-top:16px">
  <div class="card-header">
    <div class="card-title">
      <div class="icon" style="background:var(--primary-soft);color:var(--primary)">📋</div>
      全库标注规则
    </div>
    <span class="card-subtitle" id="ruleCount"></span>
  </div>
  <div class="rule-filter" id="ruleTagFilter"></div>
  <input class="rule-word" id="ruleWordInput" maxlength="1" placeholder="输入一个字筛选">
  <div id="ruleList"></div>
</div>
```

位置理由：作用域自上而下从窄到宽——选曲目/唱段 → 改这一个唱段 → 看全库。与右上「已添加标注规则」（**只含当前唱段**）中间隔着整块歌词区，不会被误认成同一个列表。

## 4. 数据流

```
页尾初始化 ──► fetchRules()                 ← 不带参数 = 全库
点 tag 按钮 ─┐
输入框变化  ─┴► fetchRules()                ← 带当前筛选条件重新请求 C7
saveAnnotation() 写成功 ─┐
deleteAnnotation()      ┴► fetchRules()     ← 带**当前**筛选条件刷新
```

### 4.1 请求构造

```js
const qs = new URLSearchParams();
if (ruleTag !== null) qs.set('tag', ruleTag);     // null = 「全部」
if (ruleWord !== '') qs.set('word', ruleWord);
fetch(`/api/annotations/rules?${qs}`, { credentials: 'same-origin' })
```

两个条件都不设时查询串为空（`?`），等价于全库。这与后端 `request.args.get(...) or None` 的「缺省与空串一并收敛成不筛」一致。

**不传空串**：后端 `?word=` 会收敛成 None（即不筛），前端若传空串虽然结果相同，但会让「没输入」与「输入了空」在网络层无法区分，排查时多一层困惑。

### 4.2 竞态守卫新开一个计数器

新增 `ruleReqToken`，**不复用 `annReqToken`**。左侧标注列表与全库列表是两条互不相干的请求流；共用一个计数器会让「切唱段」把「筛字」的响应判成过期，反之亦然。写法与 `fetchAnnotations` 完全一致：领号在 `await` 之前，判定在 `await` 之后，失败分支也要判。

### 4.3 写操作后刷新

`saveAnnotation()` 与 `deleteAnnotation()` 写成功后各调一次 `fetchRules()`。

理由：左侧加一条/删一条，下面全库列表的**行与计数就陈旧了**——而 9.6 的全部价值就是「全库有多少条规则，这个数字是对的」。显示旧数字等于谎报。

刷新**带当前筛选条件**、不复位成「全部」：用户在筛「拖腔」时加了一条「归韵」，列表就该仍是拖腔的结果（新加的那条不出现，正确）。

**不 `await`**：与 `switchPiece` 里 `fetchSegments` 的口径一致（「高亮与 toast 不依赖分段结果，不该等它」）。

**插入的锚点必须精确**：

- `saveAnnotation()`：插在 `showToast("success", "已添加标注", ...)`（745 行）与 `clearTagSelection()`（746 行）之后、**两个 `return` 分支之前**（750 行的「切走了唱段」与 752 行的 `if (!annLoaded)`）。放在函数末尾会被这两个 `return` 跳过——而它们跳过的恰恰是「用户快速操作」的常见路径，也是全库列表最容易陈旧的时候。
- `deleteAnnotation()`：追加在函数末尾（`renderLyrics()` 之后）。该函数 toast 之后没有分支。

### 4.4 403 与其它失败分开判

catch 里用 `r.status === 403` 判定（**不看 `body.code`**，那只是 HTTP 状态码的同值副本，而 `r.json()` 本身也可能失败）。403 走「仅教师可见」，其余走「加载失败」。

注意：左侧 C4 的 403 现在统一显示「标注加载失败」，这对学生是误导性的文案——但那是既有写法，**本轮不碰**（同 1 节非目标）。同一页因此会同时出现两种错误文案，这是可接受的代价；要统一是另一件事。

### 4.5 不做加载中态

既有 `fetchDemos` / `fetchAnnotations` 都没有——请求期间保持上一帧的画面。为一致起见新块也不加骨架屏。

## 5. 筛选控件

### 5.1 tag：七个 `.piece-btn`

```
[全部] [滑音] [归韵] [换气] [强音] [拖腔] [擞音]
```

复用本页 `.piece-btn` + `.active`（「曲目/唱段按钮」就是这套，`annotation.html:193-208`）。

**「全部」是本地概念，不是词表的第七项**——它对应「不发 `tag` 参数」，用 `null` 表示。六个技法名从既有的 `TAG_CATEGORY`（774 行）取键，与 `ANNOTATION_TAGS`、左侧六个 `.type-btn` 同源，不另抄一份字符串字面量。

不用 `.type-btn`：那是「选一个标注类型去写」的动作按钮，带 emoji 与配色语义；筛选用互斥选择按钮组更贴。

### 5.2 word：单字输入框

`<input maxlength="1">`，placeholder「输入一个字筛选」。

**必须处理中文输入法的合成事件。** 拼音阶段浏览器就会发 `input` 事件：不挡的话，打「san」会依次按 `s`→`a`→`n` 各请求一次，而且 `maxlength` 在合成期间不生效，最后一个字母可能被留下来当筛选条件。

```js
input.addEventListener('input', (e) => {
  if (e.isComposing) return;        // 拼音合成中，不是最终输入
  ruleWord = input.value;
  fetchRules();
});
input.addEventListener('compositionend', () => {
  ruleWord = input.value;
  fetchRules();
});
```

**不 debounce**：一个字就是一次完整查询，输入即查询，没有中间态可言。删空也是一次查询（回到不筛）。

输入框为空 = 不发 `word` 参数。

## 6. 表格渲染

六列，顺序 **曲目｜唱段｜字｜技法｜容忍度｜标注时间**。行序由后端定（曲目 → 唱段 → 字序），前端不再排。

C7 返回 10 个字段，前端用 7 个：`char` `word_index` `tag` `tolerance` `created_at` `segment_title` `demo_title`。
**不用的三个**：`id`（只读展示，行上没有动作可挂）、`segment_id` / `demo_id`（同理，页面不跳转）。

| 列 | 取值 | 空值渲染 |
|---|---|---|
| 曲目 | `demo_title` | `—` |
| 唱段 | `segment_title` | `—` |
| 字 | `char` + `word_index` 小字 | `?` |
| 技法 | `tag` | —（NOT NULL，无空值分支） |
| 容忍度 | `tolerance` | `—` |
| 标注时间 | `created_at` | `—` |

四处细节：

**1. `char` 为 null 显示 `?` 而不是留空。** 同左侧 `annChar()`（779 行）的兜底口径——越界/取不到是数据问题，要让人看见。三种来源（见 C7 spec 3.4）：`segment_id` 为 NULL、`lyrics_json` 为 NULL、`word_index` 越界。

**2. `word_index` 以 `第 {word_index + 1} 字` 渲染。** 库里的 `word_index` 是 **0 基**（C5 的 `Field(ge=0)` 也这么约束），直接显示「第 0 字」不通顺。`char` 为空时它就是唯一能定位这一行的信息——而这一行很可能 `segment_title` 也是 `—`，是「彻底失联」的那种。

**3. 技法沿用左侧的彩色药丸** `.ann-tag.tag-${TAG_CATEGORY[tag] || ""}`，含左侧那条口径（802 行）：「认不出的 tag 不硬安语义配色」，`|| ""` 落回基础外观。

**4. 容忍度 null 显示 `—`，与左侧不同。** 左侧 `.ann-tol` 为 null 时整格不渲染（flex 布局，少一格不影响别人）；表格里少一格会让整列错位。

### 6.1 时间格式：切字符串，不经过 `Date`

```js
// "2026-09-29T14:33:21.123456" → "09-29 14:33"
```

库里 `created_at` 是 `TIMESTAMP`（`schema.sql:83`，**不带时区**，naive），而 DB 服务器时区是 `Asia/Shanghai`（实测，见记忆与 `DOC_ISSUES` 第 28 条），所以拿到的**已经是北京时间**，不需要也不应该再做时区换算。

不写 `new Date(x).toLocaleString()`：一是没有必要（无需换算），二是 `new Date` 对无时区 ISO 串的解析行为在 ES5 / ES2016+ 之间变过（UTC vs 本地），切字符串没有这层歧义。

## 7. 空态与失败态

`#ruleCount` 的文案随之区分，避免「筛出 3 条」被误读成「全库共 3 条」：

| 情形 | 判定条件 | 列表区显示 | 计数 |
|---|---|---|---|
| 全库为空 | 成功 · 无筛选 · 0 行 | 📋 库里还没有标注规则 | 共 0 条 |
| 筛选无匹配 | 成功 · 有筛选 · 0 行 | 🔍 没有匹配的规则 | 筛出 0 条 |
| 学生 | `r.status === 403` | 🔒 全库规则仅教师可见 | 清空 |
| 其它失败 | 其余异常 | ⚠️ 规则列表加载失败 | 清空 |
| 正常 | — | 表格 | 共 N 条 / 筛出 N 条 |

**「有筛选」的判定**：`ruleTag !== null || ruleWord !== ''`。

「拿不到」与「确实没有」不能混成同一句文案——同 `fetchDemos`（894 行）既有的口径。

空态复用本页既有的 `.empty-state` / `.empty-icon`（`renderAnnotations` 792 行就是这么用的），空态文案变量照 `annEmptyMsg` / `annEmptyIcon`（1067–1068 行）的既有做法。

## 8. 复用与新增

**只复用、不新造**（均已存在）：`.card` `.card-header` `.card-title` `.card-subtitle` `.piece-btn`(+`.active`)、`.empty-state` `.empty-icon`（382–383 行，**无作用域前缀，可直接用**）。

**但 `.ann-tag` 不能直接复用**：它的基础规则与四个 `tag-*` 配色**全部挂在 `.annotation-item` 之下**（340–346 行），表格里写 `class="ann-tag"` 会一点样式都没有。处理办法是**把那五条选择器扩成并列选择器**：

```css
.annotation-item .ann-tag,
.rule-table .ann-tag{ ... }
```

而不是在表格的 CSS 里重抄一份颜色常量——两处十六进制色值迟早漂移。扩选择器不改变左侧标注列表的任何渲染结果。

**新增 CSS 只有三条**，写在本页既有的 `<style>` 里（单文件架构，不新建文件、不动 `:root`）：

- `.rule-filter` — 按钮行容器，flex + gap + 可换行
- `.rule-word` — 输入框，边框/圆角/配色对齐 `.piece-btn`
- `.rule-table` — 表格，表头用 `--text-muted`，行分隔用 `--border-light`

**新增 JS**：`ruleTag` / `ruleWord` 两个状态变量、`ruleReqToken`、`fetchRules()`、`renderRules()`、`ruleEmptyMsg` / `ruleEmptyIcon`（当前空态文案与图标，两个变量分开，同 `annEmptyMsg` / `annEmptyIcon` 的既有做法）。

## 9. 验证

仓库无测试框架（无 `tests/`、`requirements.txt` 里无 pytest）。验证手段：

1. **起后端 + worker**，用 HTTP 访问（`file://` 打不开，页面受登录保护）
2. **教师账号 `teacher01`** 打开 `annotation.html`：全库块应显示真库的 3 条标注（id 109/110/111），计数「共 3 条」
3. **逐个点 tag 按钮**，对照 `curl` 同一查询串的返回行数，必须一致
4. **输入框**：输入一个字 → 列表只剩该字；删空 → 回到全库；用拼音输入法打一个字，确认只发一次请求（devtools Network 面板）
5. **写操作后刷新**：在左侧给某字加一条标注 → 全库块计数 +1；删掉 → 减回去；且在筛了某个 tag 的状态下加别的 tag 的标注，列表内容不变、计数不变
6. **学生账号 `stu001`**：全库块显示「🔒 全库规则仅教师可见」，不是「加载失败」
7. **空库/无匹配**：筛一个词表外不存在的组合（如 `tag=擞音` 且当前无该 tag 的行）→「🔍 没有匹配的规则」，计数「筛出 0 条」
8. **数据安全**：全程 `annotations` 表行数不得变化（教师手写的两条要按抓到的 id 删回去）
9. `git status` 应显示**只有 `annotation.html` 一个文件被改**（外加 spec / plan / DOC_ISSUES）

## 10. 收尾

1. **`DOC_ISSUES.md` 新增条目**（接在第 32 条之后，插在 `## 待核实` 之前），登记：
   - 「9.6 的 UI 落在 `annotation.html`」是自拟口径——文档只写了「集中展示+筛选」，没说在哪一页
   - C7 的 `word` 是**单字精确匹配**，UI 据此做成 `maxlength=1`；文档未定义匹配语义（承接第 32 条）
   - 学生可打开教师工作台页面（页面级鉴权只管登录）——与本轮 4.4 的降级有关，指向既有条目
2. **更新第 32 条的「待确认」第 5 项**：本轮之后「C7 目前没有任何前端调用方」不再成立
3. `git commit` 落在 `main` 上（本项目惯例，不开分支）

## 11. 待文档方确认

1. 9.6 的 UI 归属页（本轮自拟：`annotation.html`，理由见 1 节的功能点归属表）
2. C7 `word` 的匹配语义（本轮自拟：单字精确匹配，理由见 C7 spec 3.2）
3. 教师工作台页面是否应禁止学生访问（本轮不动，仅在 4.4 做了降级文案）

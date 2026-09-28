# 班级畏难倾向指数（G6 `fear_index`）实现设计

日期：2026-09-28 ｜ 状态：已评审待实现 ｜ 关联：《班级看板--班级畏难倾向指数说明.md》（`../艺校_docs/`）、《1-PRD》5.8、《3-功能清单》5.8、《5-接口清单》G6；`DOC_ISSUES.md` 第 24 条

## 1. 背景与目标

`GET /api/dashboard/process-metrics`（功能 5.8）此前只实现了「人均练习时长」与「人均练习频次」两个真指标，`fear_index` **恒回 `null`**——因为当时全库 11 份文档里检索不到畏难指数的任何定义，`DOC_ISSUES.md` 第 24 条把这记为「功能 5.8 只实现了一半」。

2026-09-28 新增了 `../艺校_docs/班级看板--班级畏难倾向指数说明.md`，补上了算法：从练习行为数据中取 5 类信号，各自归一化到 0~1 后**加权求和**，权重示例为各占 20%，输出 0~1，越接近 1 越畏难。

**目标**：把 `fear_index` 从占位 `null` 换成按该文档算出的真实值，并让 `dashboard.html` 按文档第四节渲染「数值 + 较上周趋势 + 需关注等级」。

**非目标（明确不做）**：

- 不新增数据采集（埋点、中断事件表、学生主动上报）。全部信号从已有表派生
- 不做学生粒度。文档旁证提到 `AI_teacher.html` 的学生画像有「畏难倾向 0.32」，但那是学生级指标、且该页是纯 mock，不在本次范围
- 不在响应里返回 5 个分量的明细（文档未要求，卡片也放不下）
- 不改「本周起算」的口径——复用 `process_metrics()` 现有的 `this_week` / `last_week`，与 `students()` 的周定义保持一致
- 不引入新依赖、不改 `schema.sql`、不动 `app-d.py`

## 2. 文档给的 vs 库里有的

文档第二节列了 6 类信号，第三节的公式只含其中 5 项（**不含「练习时长」**）。本设计按**公式的 5 项**实现。

| # | 文档信号 | 库里可依据 | 缺口 |
|---|---|---|---|
| 1 | 练习中断率 | `practice_records.duration_sec` + `segments.duration` | **无「是否中断」字段**，只能代理 |
| 2 | 重试放弃率 | `practice_records`(student, segment, ai_score) 多次记录 | 「放弃」判据未定义 |
| 3 | 连续未练习率 | `practice_records.created_at` | **无事件日志表**，窗口未定义 |
| 4 | 挫败关键词触发率 | `chat_messages.content`（`role='user'`） | 词表与频次口径未定义 |
| 5 | 作业未提交率 | `homeworks` + `submissions` | 窗口口径未定义（按周切会常出现分母 0） |
| — | 练习时长 | 已在指标 1/2 中体现 | 公式不含，本次不单列 |

以下口径是**实现时定的**（用户逐条确认），文档没有规定，全部以注释形式写在代码里。

## 3. 公式与分量口径

```
fear_index = 0.2 × 中断率
           + 0.2 × 重试放弃率
           + 0.2 × 连续未练习率
           + 0.2 × 关键词触发率
           + 0.2 × 作业未提交率
```

- **权重**：`FEAR_WEIGHTS: tuple[float, ...] = (0.2, 0.2, 0.2, 0.2, 0.2)`，模块级常量（与 `SKILLS`、`DIFF_MATCH` 同风格），不做配置化。
- **分母为 0 的分量记 0，不重新归一化**。理由：权重固定，周与周之间的指数才可比；若按可用分量重归一化，某一周缺一项就会改变权重结构，趋势本身失去意义。代价是「某分量长期无数据」会让指数被固定压低，见第 7 节。
- **窗口**：本周 = 北京周一 ~ 今天；上周 = 上周一 ~ 上周日（同口径）。
- **两个值都在服务端算**，`fear_index_last_week` 由接口返回，**差值不在后端算**——与 `avg_duration_sec` / `avg_duration_sec_last_week` 现有的分工一致。

### 3.1 练习中断率（本周）

- **分子**：本周 `practice_records` 中 `duration_sec < 0.5 × segments.duration` 的记录数
- **分母**：本周能取到唱段时长的记录数，即 `segment_id` 非空 **且** 该 segment 的 `duration` 非空且 `> 0`
- 唱段时长取不到（`segment_id` 为 NULL、或 segment 无时长）的记录**不进分母也不进分子**——判不了就不算，不用第二把尺子兜底
- 分母 0 → 记 0
- 阈值 `0.5` 以常量 `INTERRUPT_RATIO = 0.5` 定义在 `dashboard_service` 顶部

> **这是代理，不是文档语义的中断。** 库里没有任何「学生主动退出」的记录，只能拿「录下来的时长明显短于唱段时长」当「没唱完」的近似。一首快板唱段被正常快练一遍、时长压在唱段时长的 50% 以内，会被误判为中断。

### 3.2 重试放弃率（本周）

- **分组**：本周记录里 `segment_id` 非空的，按 `(student_id, segment_id)` 分组
- **有效组**：组内记录数 `≥ 2` 且 `ai_score` **全部非空**
- **放弃**：有效组内按 `created_at` 升序，**最后一次 `ai_score` 未超过组内此前的最高分** → 该组记为一次放弃
  - 即「练了不止一遍，最后一遍没有刷新自己的最好成绩」
- **率** = 放弃组数 / 有效组数；有效组为 0 → 记 0
- `ai_score` 有缺值的组整体不进分母（判不了不算），不部分参与

### 3.3 连续未练习率

- **截至点**：本周算到**今天**，上周算到**上周日**（两边都是「该周已经过完的最后一天」）
- **分子**：在册学生中，`get_last_practice_dates` 给出的最后一次练习日期距截至点 **≥ 7 天**的人数，**含从未练过的学生**（取不到最后练习日期的按正无穷距离算）
- **分母**：在册学生数；0 人 → 记 0
- 天数差按**北京日期**相减（`date - date`），不涉及时分秒

### 3.4 挫败关键词触发率（本周）

- **词表**（模块级常量）：
  `太难 好难 不会 学不会 算了 放弃 不想练 听不懂 做不到 坚持不下去`
- **分子**：本周 `role='user'` 且 `content` 命中任一关键词的消息数
- **分母**：本周 `role='user'` 消息总数；0 → 记 0
- 子串匹配（`content LIKE '%词%'`，或取回内容后在 Python 里 `any(k in content)`）；一条消息命中多个词只计一次
- 只统计 `role='user'`，`assistant` 的消息不参与

### 3.5 作业未提交率（**不按周切**）

- **分子**：`Σ over 全部作业 (在册学生数 − 该作业已提交的在册学生数)` + 逾期提交组合数
- **分母**：作业总数 × 在册学生数；0 → 记 0
- 「已提交」按 `(homework_id, student_id)` **去重**（表上无唯一约束，与 `get_progress_rows` 同口径，避免出现 6/5）
- 「逾期提交」= `submissions.submitted_at` 的日期 **晚于** `homeworks.deadline`；已逾期的组合在「未提交」里不计第二次
- **本周与上周取同一个值**：作业截止日不随周滚动，按周切分母会频繁为 0（当前库 3 份作业的截止日全在 2026-07/08，本周无到期作业）。代价是这一项对周趋势没有贡献
- `deadline` 为 NULL 的作业照常计入（属于「已布置」）

## 4. 接口契约变更

`ProcessMetrics`（`app/schemas/dashboard.py`）新增一个字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `fear_index` | `float \| None` | 由「恒 None」改为真实值，0~1 |
| `fear_index_last_week` | `float \| None` | **新增**，上周同口径值，供前端算趋势 |

**仅当在册学生数为 0 时两者回 `None`**（此前的顾虑：`null` 是「没有数据」，0 是「一点都不畏难」，两者不能混）。其余情况恒为 `0.0 ~ 1.0` 的浮点数——包括「有学生但完全没有练习/对话/作业记录」的班级，那时指数为 `0.2 × 1.0 = 0.2`（全员从未练习 → 连续未练习率 1.0）。

`app/api/dashboard.py` **不用改**：该路由已经用 `model_dump(mode="json")`，新增的 float 字段直接可序列化。

## 5. 代码改动清单

| 文件 | 改动 |
|---|---|
| `app/repositories/practice_records_repo.py` | +`get_interrupt_rows(db, start, end)`：本周/上周的 `(duration_sec, segment_duration)` 行；+`get_retry_groups(db, start, end)`：本周的 `(student_id, segment_id, ai_score, created_at)` 行；+`get_last_practice_dates(db, student_ids, until)` |
| `app/repositories/chat_repo.py` | **新建**：`count_user_messages(db, start, end, keywords) -> tuple[int, int]`（命中数, 总数） |
| `app/repositories/homeworks_repo.py` | +`get_submission_stats(db, student_ids) -> tuple[int, int, int]`（作业数, 已提交组合数, 逾期组合数） |
| `app/services/dashboard_service.py` | 顶部 +`FEAR_WEIGHTS` / `INTERRUPT_RATIO` / `FRUSTRATION_KEYWORDS` 常量；+私有 `_fear_index(db, student_ids, start, end, until) -> float`；`process_metrics()` 调两次（本周/上周）并填 4 个字段 |
| `app/schemas/dashboard.py` | `ProcessMetrics` +`fear_index_last_week`，重写 `fear_index` 的注释（现注释写「文档未定义，恒 None」已过时） |
| `dashboard.html` | `loadProcessMetrics()` 渲染数值/趋势/等级；`fmtTrend` +`invert` 参数（畏难上升是坏消息，现有 `.metric-trend.up` 是绿色）；更新 `:914` 起那段注释 |
| `DOC_ISSUES.md` | 第 24 条追加「2026-09-28 已按新增说明文档实现」，列出仍为自定口径的 4 处 |
| `docs/superpowers/specs/2026-09-28-class-fear-index-design.md` | 本文件 |

不改：`app/api/dashboard.py`、`schema.sql`、`seed.sql`、`app/models/*`（无新增表/列）、`app-d.py`。

## 6. 前端展示

`dashboard.html` 的畏难卡片（`#metricFear` / `#metricFearTrend`）：

- **数值**：`fear_index.toFixed(2)`。`None` → `—`，副标「在册学生为 0」
- **趋势**：复用 `fmtTrend(delta, unit, digits)`，但**颜色要反着来**——`invert=true` 时上升用 `.down`（`--danger`）、下降用 `.up`（`--success`）。单位留空
- **等级标签**（文档第五节 4 档），跟在趋势后面用 `·` 连接：

| 区间 | 档位文案 |
|---|---|
| `< 0.20` | 保持节奏 |
| `0.20 ~ 0.40` | 需关注 |
| `0.40 ~ 0.60` | 需调整难度 |
| `>= 0.60` | 需立即干预 |

区间取左闭右开（`v < 0.2` / `v < 0.4` / `v < 0.6` / else），文档的边界值（0.20、0.40、0.60）归入**偏高**那一档。

加载失败时维持现状：数值 `—`、趋势「加载失败，请刷新重试」。

## 7. 已知局限（必须登记，不可当作已解决）

1. **「中断」是时长代理**。库里没有中断字段，`duration_sec < 0.5 × 唱段时长` 会把正常快练误判为中断。**该阈值未经真实素材标定**，与 `parse_service.TOP_DB` 同类性质。
2. **第 4 分量当前恒为 0**：真库 `chat_messages` 里 `role='user'` 消息 0 条（只有 1 条 assistant 记录）。固定权重下指数被压低最多 0.2。
3. **第 5 分量不按周切**，对周趋势无贡献；且当前库 3 份作业里 2 份无人提交，该项会显著偏高。
4. **文档第二节的「练习时长」信号未单列**，因为第三节公式只有 5 项。若文档方本意是 6 项加权，需重新定义权重。
5. **真库数据极薄**（在册 10 人、练习记录 10 条、本周 8 条），算出的指数是**演示值**，不具备统计意义。上线前需要真实使用数据。
6. 权重 20% 均等来自文档的「例如各占 20%」，是示例值，未经教学效果验证。

## 8. 验证方式

仓库当前**没有任何测试文件**（`find . -name "test_*.py"` 为空，无 `tests/` 目录），因此本次不新建测试框架，验证走：

1. **手工核对**：`curl` 打 `GET /api/dashboard/process-metrics`（带教师 session），把返回的 `fear_index` 与直接从库里按第 3 节口径手算的数字对齐
2. **边界**：构造「在册 0 人」（改 `user_repo` 的临时桩或直接跑纯函数）确认回 `None` 而不是 500 或 0
3. **页面**：`http://localhost/index.html` 用 `teacher01 / xiyun@2026` 登录，确认卡片显示数值、趋势箭头方向与颜色正确、等级文案落在对应档
4. **回归**：`avg_duration_sec` / `avg_practice_count` 及其上周值不变（本次不动它们的查询路径）
5. `python scripts/check_db.py` 仍通过（本次不改表结构，属保险）

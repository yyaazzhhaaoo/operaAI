# D1–D3 练习接口设计（实时跟唱真实评分接线的后端部分）

日期：2026-10-19
范围：`POST /api/practice/submit`（D1）、`GET /api/practice/logs`（D2）、`GET /api/practice/last/<segment_id>`（D3）
关联：《5-接口清单-V1.0》2.4 智能陪练；排期第 1 周「实时跟唱」

## 背景

`sing_along.html` 的录音是真实的，但停录后调用 `simulateAnalysisAfterRecord()` 在浏览器本地算分（音准/节奏/气息本地算，咬字/拖腔随机）。B1–B5 分析链路已实现，B4 已返回五维 `音准/节奏/气息/咬字/拖腔`。本轮把三个练习接口从桩实现补成真实链路，为前端接线提供后端能力。

**文档只给了一句话**：D1「入参 segment_id + audio_id；内部走 B2 同一分析管线（基准=该分段示范），结果落 practice_records 并更新 BKT；返回 task_id」；D2「练习日志（功能 2.14；学生仅本人）」；D3「上次练习结果回显（对比进步）」。请求/响应体、错误码、BKT 更新规则均未定义，本设计定的口径登记在 `DOC_ISSUES.md` 第 44 条。

## D1 POST /api/practice/submit

- 权限：`@login_required` + `@student_required`
- 请求：`multipart/form-data`
  - `segment_id`：必填，`segments.id`
  - `audio_id`：必填，`audio_files.id`（B1 返回的 `file_id`）
  - `duration_sec`：选填，本次录音时长（秒）；不传则 `NULL`
- 校验：
  - 当前账号没有学生档案 → 403
  - `audio_id` 不存在 → 404；`uploader_id` 不是当前登录用户 → 403（防止拿别人的录音冒充）
  - `segment_id` 不存在或所属剧目没绑示范音频 → 404（由 `analyze_service.submit` 统一判）
- 行为：调用 `analyze_service.submit` 的模式二（`segment_id` + `student_audio_id`），并把 `{student_id, segment_id, audio_id, duration_sec}` 作为纯数据随 Celery 任务传下去。
- 响应：`{"task_id": "<id>"}`
- 异步落库：worker 算完结果后，在同一事务里
  1. 插入 `practice_records`：`student_id`、`segment_id`、`source='practice'`、`audio_id`、`ai_score=result.overall`、`dimensions_json=result.dimensions`、`duration_sec`；
  2. 按第 4 节更新 `bkt_history`。
  落库成功后才把 redis 任务状态置为 `done`；落库失败按分析失败处理（任务置 `failed`），避免前端看到分数但库里没有记录。

## D3 GET /api/practice/last/&lt;segment_id&gt;

- 权限：`@login_required` + `@student_required`
- 行为：查当前学生（`students.id`）在该 `segment_id` 上 `created_at` 最新的一条 `practice_records`。
- 响应：
  ```json
  {"record": {
    "id": 1, "student_id": 48, "segment_id": 5, "source": "practice",
    "audio_id": 9, "ai_score": 82.5,
    "dimensions": {"音准": 80.0, "节奏": 85.0, "气息": 78.0, "咬字": 84.0, "拖腔": 86.0},
    "duration_sec": 24.7, "created_at": "2026-10-19T14:30:00"
  }}
  ```
  没有记录时 `{"record": null}`，不是 404——「还没练过」是正常状态。
- `created_at` 是北京时间墙上时间（与 `practice_records_repo` 的既有口径一致），不带时区偏移。

## D2 GET /api/practice/logs

- 权限：`@login_required`
  - 学生：只能查本人；`student_id` 省略时默认本人，传了别人 → 403；没有学生档案 → 403
  - 教师：`student_id` 必填，省略 → 400；可查任意学生
- 查询参数：`student_id`、`segment_id`（选填）、`limit`（默认 50，最大 200）、`offset`（默认 0）
- 响应：按 `created_at DESC, id DESC` 返回记录，记录结构与 D3 相同：
  ```json
  {"records": [...], "total": 12}
  ```
- `total` 是过滤条件下的总条数，供前端分页。

## 4. BKT 更新（临时口径）

文档没有 BKT 更新公式。本轮取一条可解释的临时规则，待第 4 周算法标定时替换：

- 维度 → 技法映射：

  | 维度 | 技法 |
  |---|---|
  | 音准 | 音准控制 |
  | 节奏 | 节奏感知 |
  | 气息 | 气息支撑 |
  | 咬字 | 归韵咬字 |
  | 拖腔 | 拖腔 |

- 旧掌握度：该学生该技法最新一条 `bkt_history.p_l`；没有记录时取 0.5。
- 更新：`new = clamp(old + 0.3 * (score / 100 - old), 0, 1)`，`score` 为该维度分数。
- `confidence = min(1.0, (旧 confidence 或 0.5) + 0.05)`。
- 每次练习写 5 行 `bkt_history`，`source_type='practice'`、`source_id=practice_records.id`。
- 滑音/装饰音技巧/颤音没有对应维度，本轮不更新。

## 5. 错误码

| 场景 | HTTP |
|---|---|
| 未登录 | 401 |
| 非学生调用 D1/D3；学生查他人日志；学生无档案 | 403 |
| 音频不属于本人 | 403 |
| `segment_id` / `audio_id` 不存在，或分段没绑示范音频 | 404 |
| 教师查日志未给 `student_id`；参数非法 | 400 |

## 6. 验证

无测试框架，使用临时脚本 + Flask test client（`create_app({"CELERY": {"task_always_eager": True}})` 让任务同步跑完）：

1. 学生登录 → B1 上传一段真实录音 → D1 提交 → 任务完成 → `practice_records` 新增一行且五维齐全；`bkt_history` 新增 5 行。
2. 同一分段再练一次 → D3 返回最新一条。
3. 学生 D2 省略 `student_id` 返回本人记录；传别人的 `student_id` 返回 403。
4. 教师 D2 带 `student_id` 返回该学生记录；不带返回 400。
5. 用另一个学生的 audio_id 调 D1 → 403。
6. 无效 `segment_id` → 404。

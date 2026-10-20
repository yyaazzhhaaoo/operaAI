# 示范分段音频切分与跟唱对比基线 设计

日期：2026-10-20

## 1. 背景与目标

`sing_along.html`（实时跟唱）的「开始跟唱」停录后走 D1 → B2，后端
`audio_repo.get_segment_teacher_audio` 取的是 **整个 `teacher_demos.audio_id`**
作为教师轨，学生只唱了一个唱段，比较基线却是整首。

同时，Demucs 解析链路已经算出每个唱段的起止区间（`parse_service._split_segments`），
但只写 `segments` 元数据，不产出切分音频，`segments` 表也没有音频列
（2026-10-09 跟唱页 spec 已记录该缺口）。

本轮目标：

1. Demucs 解析时按唱段切出**原始混音**音频文件，一段一个文件。
2. 该文件作为跟唱页「开始跟唱」的对比分析基线（D1/B2 的教师轨）。
3. 「播放示范」选中段时播放该段切片。
4. 在 Linux 环境完成一次 Demucs 全链路验收。

## 2. 范围

- **只做 Demucs 解析路径**。带 Excel 逐字数据的示范不切音频，`segments.audio_id`
  保持 `NULL`，对比基线继续回退到整首音频。
- 不做实时画布的教师音高曲线（Demucs 段没有 `lyrics_json`，画布保持空态）。
- 不修改 D1/B2/B3/B4/C3 的接口契约。
- 不改文档目录（`../艺校_docs/` 或 `/home/myz/lianshu/艺校_docs/`）中的需求文档；
  与《4-数据库设计》的差异登记到 `DOC_ISSUES.md`。

## 3. 数据模型

`segments` 新增一列：

```sql
audio_id INT REFERENCES audio_files(id)
```

- 可空。`NULL` 表示该段没有独立音频（Excel 路径、旧数据）。
- 同步位置：`schema.sql`、`app/models/demo.py`、活库 `ALTER TABLE`。
- `scripts/check_db.py` 是模型与真库的一致性闸门，改完必须跑。
- 选择独立音频列而非「约定路径」：文件与库一一对应，缺失可查；
  也而非「只存起止时间」：避免每次分析重复切片，并给前端稳定的音频 URL。
- 《4-数据库设计》未定义该列，按项目约定登记 `DOC_ISSUES.md`。

`audio_files` 中每段切片一行：

| 字段 | 取值 |
|---|---|
| `uploader_id` | 原示范音频的 `uploader_id` |
| `file_path` | `segments/<demo_id>/<uuid>.wav`（相对 `uploads/`） |
| `original_name` | `<曲目名> 第 N 段.wav` |
| `file_size` | 实际字节数 |
| `duration_sec` | 切片实际时长 |
| `access` | `public`（学生可经 B5 播放） |

## 4. 解析管线

`app/services/parse_service.py`：

1. `_split_segments` 返回值增加每段起止秒数（`start` / `end`），仅供内部切片；
   不新增 `segments` 起止时间列。
2. 切段后、入库前，以原生采样率重读原音频（`duration=MAX_AUDIO_SEC`，与 Demucs
   处理的 3 分钟上限一致），按区间截取**原始混音**，保留原声道数。
3. 通过 `app/common/storage.py` 新增的 `save_generated()` 写 WAV 到
   `uploads/segments/<demo_id>/`，返回相对路径；音频落盘仍只经 storage 模块。
4. 每段登记一行 `audio_files`，并把 id 放进传给 `replace_segments` 的 dict。
5. `library_repo.replace_segments` 写入 `segments.audio_id`；`audio_id` 缺省为
   `None`，Excel 路径不受影响。
6. 重新解析的清理：替换前记下旧分段音频的 id 与路径；新片段入库的同一事务里删除
   旧 `audio_files` 行；**事务提交成功后**再删旧文件。提交失败时旧数据与旧文件
   都保留。新文件用 uuid 命名，不会与旧文件互相覆盖。
7. 切片或写盘失败直接抛异常，由 `run_parse` 落成 `error`，message 用现有兜底文案；
   旧分段与旧音频不受影响。

## 5. 对比基线

`app/repositories/audio_repo.py::get_segment_teacher_audio`：

1. 先按 `segments.audio_id` 取 `audio_files`。
2. 为空或记录缺失时，回退到现有 `segments → teacher_demos → audio_files` 的整首音频。
3. 两者都没有返回 `None`，调用方维持 404「片段不存在或未绑定示范音频」。

B2 的 `_load_vocal` 仍会对教师轨做 HPSS，切片是混音不影响现有管线；
`lyrics_json` 为 `NULL` 时逐字结果为空、`regions` 走滑窗兜底，与现状一致。

## 6. 接口

仅 C2 `GET /api/demos/<int:demo_id>/segments`：

- 每条分段新增 `url` 字段：有 `audio_id` 时用
  `url_for("api.audio_download", file_id=...)` 生成，否则为 `null`。
- `app/schemas/demo.py::DemoSegmentOut` 增加 `url: str | None = None`。
- 不返回 `file_path`（服务端存储路径不外泄，与现有约定一致）。
- C3 不变；B5 已按 `access=public` 允许所有登录用户取音频。

## 7. 前端

`sing_along.html`：

- 「播放示范」`playDemo()`：
  - 当前选中段存在且 `segments[idx].url` 非空 → 播放该段切片；
  - 未选段或该段无 `url` → 维持现状，经 `/api/demo/library/<id>` 播整首。
  - 播放态、停止按钮、错误处理沿用现有逻辑。
- 不修改录音、实时检测、停录上传、D1/B2 轮询与评分面板。

## 8. Linux 全链路验收

环境已具备：torch 2.14.0+cpu、demucs、`models/demucs/repo/` 权重、
远程 PostgreSQL/Redis 可达。验收步骤：

1. 活库执行 `ALTER TABLE segments ADD COLUMN IF NOT EXISTS audio_id INT REFERENCES audio_files(id)`；
   跑 `scripts/check_db.py`。
2. 启动 Flask（8877）、默认 Celery worker、`-Q demucs` worker。
3. 教师登录 → `POST /api/demo/library/upload` 上传
   `uploads/demos/muguaying_yuanmenwai.wav` → 轮询 parse status 到 `parsed`。
4. `GET /api/demos/<id>/segments`：确认每段有 `url`；下载一条切片，校验 HTTP 200、
   内容为 WAV、时长与 `duration` 相符。
5. 学生登录 → 用切片作为学生录音走 B1 上传 → D1 提交 → 轮询 B3 到 `done` →
   取 B4，确认 `overall`、`dimensions`、`timeline` 正常。
6. 汇总实际耗时、分段数、切片文件大小；失败环节如实报告。

验收只覆盖 HTTP/文件链路，不做浏览器 UI 操作（本机 `/browse` 不可用）。

## 9. 涉及文件

- `schema.sql`
- `app/models/demo.py`
- `app/services/parse_service.py`
- `app/common/storage.py`
- `app/repositories/library_repo.py`
- `app/repositories/audio_repo.py`
- `app/schemas/demo.py`
- `app/api/demos_segments_annotations.py`
- `sing_along.html`
- `DOC_ISSUES.md`
- `CLAUDE.md`
- 验收脚本（放 `scripts/`）

## 10. 未做 / 风险

- Excel 路径不切音频，行为不变。
- 不画实时教师音高曲线。
- 分段切片总大小约等于原音频前 3 分钟的混音量，磁盘占用需关注。
- 重新解析失败时可能留下本轮新写的孤儿文件（提交失败路径）；旧数据不受影响。
  可在后续加定期清理，本轮不做。
- `TOP_DB` 仍未经真实素材标定，切片边界质量取决于该阈值。

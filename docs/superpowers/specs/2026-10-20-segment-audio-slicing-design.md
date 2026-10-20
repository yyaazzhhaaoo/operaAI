# 示范库按段切分音频设计（跟唱对比分析的参考轨）

日期：2026-10-20
范围：示范上传（`POST /api/demo/library/upload` 的两条路径）、示范解析（`parse.run`）、B2 模式二的参考音频来源
关联：《5-接口清单-V1.0》B2；`2026-10-15-demo-lyrics-excel-upload-design.md`；`DOC_ISSUES.md` 第 45 条

## 背景

示范上传后只落一个整曲音频文件（`teacher_demos.audio_id` → `audio_files`），分段 `segments` 只有 `duration`，没有起止时间。B2 模式二（`audio_repo.get_segment_teacher_audio`）因此拿**整首示范**去和学生单段录音做 DTW 对齐：参考轨包含学生没唱的部分，对齐靠算法硬撑，且每段分析都要解码整曲。

本轮在解析阶段按切分边界把整曲切成每段一个音频文件，跟唱页「开始跟唱」的对比分析改用该段的音频作参考轨。

## 目标与非目标

- 目标：上传（Demucs 路径与 Excel 路径）后，每个分段挂一份独立的示范音频；B2 模式二优先用它。
- 非目标：跟唱页「播放示范」仍播整首（已确认，`resolveAudioUrl` 与详情接口的 `url` 不动）；详情接口的分段响应不加字段；不写历史数据补切脚本。

## 数据模型

`schema.sql` 的 `segments` 增加一列：

```sql
audio_id INT REFERENCES audio_files(id),   -- 该段的示范音频（切自整曲）；NULL = 未切，回退整曲
```

- `app/models/demo.py` 的 `Segment` 同步加 `audio_id`；新增模型字段无需改 `app/models/__init__.py`（`Segment` 已在其中）。
- 真库手工执行 `ALTER TABLE segments ADD COLUMN audio_id INT REFERENCES audio_files(id);`（项目不用 Alembic）。
- `scripts/check_db.py` 是动态比对，不用改；改完必须跑一遍。
- **不存 start/end 列**：边界只在切片时使用，落库后无人读，`_split_segments` 现有「不加 start_sec 列」的决定继续成立。

## 切片实现

新增 `app/services/segment_audio_service.py`：

- `slice_and_attach(db, *, demo, source_audio, bounds) -> dict[int, int]`
  - `bounds`：`[(seq, start_sec, end_sec)]`，秒，相对整曲。

- 读取：`librosa.load(storage.resolve(source_audio.file_path), sr=16000, mono=True, duration=max_end + 1)`。与 `analyze_service._load_vocal` 的取样口径一致（16k 单声道），切出的段音频直接可被分析链路消费。
- 写盘：按边界切 numpy 数组，`soundfile.write` 到 `uploads/segments/<uuid>.wav`，每段一行 `audio_files`：`uploader_id = source_audio.uploader_id`、`access = 'public'`、`original_name = "<曲目名>_第N段.wav"`、`file_size`/`duration_sec` 按实际写回。
- 挂接：按 seq 把 `audio_id` 写到对应 `segments` 行上，返回 `{seq: audio_id}`。
- `app/common/storage.py` 新增 `save_bytes(data: bytes, *, subdir: str) -> tuple[str, int]`：现有 `save()` 只收 `FileStorage`，这里从内存写。与 `save()` 共用同一套 `subdir` 合法性与 `uploads/` 相对路径约定。
- 新目录 `uploads/segments/` 与现有 `uploads/demos/` 平级，`STORAGE` 侧不需要额外配置。

## 两条上传路径

### Demucs 路径（`parse_service._parse`）

1. `_split_segments(y, sr)` 的返回值补 `start`/`end`（秒，`s / sr`）。`library_repo.replace_segments` 只读 `seq/title/duration/lyrics`，多出的键被忽略，不需要改它。
2. 时长为 0 或段边界为空的段不切。
3. `_parse` 在「结果入库」阶段前、**会话外**完成切片（librosa 解码 + 写盘约 1–3 秒，不占数据库连接），再在会话内 `replace_segments` + 写 `audio_id` + 回填整曲时长，一次提交。
4. 重入解析：`replace_segments` 删除旧段前先收集这些段的 `audio_id`，随返回值交给 `_parse`；新段落库后删除这些 `audio_files` 行并 unlink 对应文件。

### Excel 路径（`library_service.demo_library_add_with_segments`）

1. `lyrics_excel.parse_segments` 每页额外返回 `start`/`end`（全局秒，取该页 `min(start)` 与 `max(end)`）——这两个键**不入库**，只用于切片。
2. 整页没有时间（`duration is None`）的段跳过切片；该段 `audio_id` 保持 NULL，B2 回退整曲。
3. 切片在 `replace_segments` 之后、`commit` 之前完成，与建 demo、写段、回填时长同一个事务。落盘失败会留下孤儿文件（与现有 `storage.save` 语义一致），不会留下半截记录。

## 消费端

`app/repositories/audio_repo.get_segment_teacher_audio`：

1. 按 `segment_id` 取 `Segment`；不存在返回 None。
2. `segment.audio_id` 非空 → 取该 `AudioFile` 返回。
3. 否则取 `segment.demo_id` → `TeacherDemo.audio_id` → `AudioFile`（即现有的整曲回退）。

`analyze_service.submit` 及之后的 `_load_vocal` 一行不改：切出的段音频仍含伴奏，HPSS 照做，分析口径与现在一致，只是参考轨从整首缩到一段。

## 失败与边界

- 切片失败（解码失败、磁盘满）**不改变解析终态**：记 warning 日志，任务仍落 `parsed`，`message` 追加「分段音频未生成」，B2 自动回退整曲。
- 上传超过 3 分钟时 Demucs 只处理前 3 分钟，切分边界也在此范围内；Excel 路径按 `max_end + 1` 限制读取长度。
- Excel 路径同一段重复上传会生成新的 demo，不覆盖旧记录，旧文件无需特殊处理。
- 现存历史示范没有 `audio_id`，行为完全不变。

## 与需求文档的偏差

`DOC_ISSUES.md` 新增第 45 条：文档未规定分段音频的存在与否、切片来源（原音 vs 分离人声）、以及「切段后 B2 参考轨应取段音频还是整曲」，本轮口径以本 spec 为准。

## 验收

无自动化测试框架，按现有惯例用 psql + curl + 临时脚本：

1. 带 Excel 上传 → `segments.audio_id` 全非空（无时间的段除外）、`uploads/segments/` 有对应文件、文件时长与 `duration` 差值 < 0.1s。
2. 不带 Excel 上传并起 `-Q demucs` worker → 解析完成后同上；再触发一次解析（临时脚本调 `parse_service.submit`）→ 旧段音频行与文件被清理、新段音频不累积。
3. 跟唱页选段录音提交 → B4 的 `teacher_pitch` 时间轴落在段长内（临时脚本打印）。
4. `python scripts/check_db.py` 通过。

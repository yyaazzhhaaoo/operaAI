# 示范库按段切分音频 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 示范上传时把整曲按分段边界切成每段一个音频文件，B2 模式二的参考轨优先用该段音频。

**Architecture:** `segments` 加 `audio_id` 列；新增 `segment_audio_service` 负责「切文件」（不碰 DB）与「登记并挂接」（只碰 DB）两件事；Demucs 解析与 Excel 上传两条路径分别调用它；`audio_repo.get_segment_teacher_audio` 改成优先段音频、回退整曲。

**Tech Stack:** Python 3.11 / Flask / SQLAlchemy / PostgreSQL / librosa / soundfile / Celery

设计见 `docs/superpowers/specs/2026-10-20-segment-audio-slicing-design.md`。

## Global Constraints

- 表结构真源是 `schema.sql`；模型只做映射。**不引入 Alembic**，真库变更手工 `ALTER`。
- **不引入 `pyproject.toml`**；依赖只进 `requirements.txt`（本计划不新增依赖，librosa/soundfile 已有）。
- 注释按 `~/.claude/skills/human-comments/SKILL.md`：默认不写，只写看不出来的 why/坑。
- 本项目**没有测试框架**：验证一律用 `/tmp` 下的临时脚本 + `psql` + `curl`，脚本不提交。
- 所有命令在项目根目录 `/Users/meiyazhao/Documents/lianshu/operaAI` 执行，Python 用 `.venv/bin/python`。
- 直接提交到 `main`，不开分支；commit message 用中文。
- 本机 macOS 装不到 torch（`requirements-demucs.txt` 带 `sys_platform == "linux"`），**Demucs 全链路只能逻辑级验证**，真机验证在 Linux 部署环境。

---

### Task 1: `segments.audio_id` 数据模型与真库迁移

**Files:**
- Modify: `schema.sql:66-73`
- Modify: `app/models/demo.py:28-41`

**Interfaces:**
- Produces: `segments.audio_id`（真库与 ORM 同时具备），后续所有任务依赖该列。

- [ ] **Step 1: 改 `schema.sql`**

```sql
CREATE TABLE segments (
  id SERIAL PRIMARY KEY,
  demo_id INT REFERENCES teacher_demos(id),
  seq INT,
  title VARCHAR(100),
  lyrics_json JSONB,   -- [{word,midi,start,end,note,tip}]，tip=功能2.4唱前提示
  duration FLOAT,
  audio_id INT REFERENCES audio_files(id)   -- 该段示范音频（切自整曲）；NULL=未切，分析回退整曲
);
```

- [ ] **Step 2: 改 `app/models/demo.py`**

在 `duration` 之后加一行：

```python
    duration: Mapped[float | None] = mapped_column(Float)
    audio_id: Mapped[int | None] = mapped_column(ForeignKey("audio_files.id"))
```

`Segment` 已在 `app/models/__init__.py` 中，不需要新增导入。

- [ ] **Step 3: 真库加列**

```bash
docker exec docker_postgres psql -U xiyun -d xiyun \
  -c "ALTER TABLE segments ADD COLUMN audio_id INT REFERENCES audio_files(id);"
```

Expected: `ALTER TABLE`

- [ ] **Step 4: 跑一致性闸门**

```bash
.venv/bin/python scripts/check_db.py
```

Expected: `比对范围：15 张表 / 104 列 / 22 个外键 / 2 个自定义索引`，差异只剩既有的两条（`demo_versions` 表、`teacher_demos` 的 `techniques_json/parse_status/parse_time_sec` 三列）。**`segments` 不得出现在差异列表里**。

- [ ] **Step 5: Commit**

```bash
git add schema.sql app/models/demo.py
git commit -m "feat: segments 增加 audio_id 关联分段示范音频"
```

---

### Task 2: 切片服务（`storage.save_bytes` + `segment_audio_service`）

**Files:**
- Modify: `app/common/storage.py`（在 `save()` 之后新增 `save_bytes()`）
- Create: `app/services/segment_audio_service.py`
- Modify: `docs/superpowers/specs/2026-10-20-segment-audio-slicing-design.md`（把 `slice_and_attach` 改成 `slice_files` + `attach` 两步，理由见下）

**Interfaces:**
- Produces:
  - `storage.save_bytes(data: bytes, *, subdir: str) -> tuple[str, int]`
  - `segment_audio_service.slice_files(source_path: Path, bounds: list[tuple[int, float, float]]) -> list[dict]`，元素为 `{"seq": int, "file_path": str, "file_size": int, "duration_sec": float}`
  - `segment_audio_service.attach(db, *, demo_title: str, uploader_id: int | None, slices: list[dict], segments: list[Segment]) -> None`

为什么拆两步：Demucs worker 解码 + 写盘要 1–3 秒，不能占着数据库连接（连接池 `pool_size=5`）。`slice_files` 完全不碰 DB。

- [ ] **Step 1: `app/common/storage.py` 追加 `save_bytes()`**

```python
def save_bytes(data: bytes, *, subdir: str) -> tuple[str, int]:
    """把内存里的音频字节落盘，返回 (存储路径, 字节数)。

    与 save() 同一套路径约定，只是不收 FileStorage——解析任务切片时手里
    只有 numpy 切出来的字节，没有上传流。固定 .wav：调用方只会写 WAV。
    """
    if not data:
        raise BusinessError(400, "写入的音频为空")

    root = settings.upload_dir.resolve()
    dest_dir = (root / subdir).resolve()
    if dest_dir != root and root not in dest_dir.parents:
        raise BusinessError(400, "非法的存储子目录")

    dest = dest_dir / f"{uuid.uuid4().hex}.wav"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest.relative_to(root).as_posix(), len(data)
```

- [ ] **Step 2: 新建 `app/services/segment_audio_service.py`**

```python
# -*- coding: utf-8 -*-
"""把示范整曲按分段边界切成每段一个音频（spec 2026-10-20）。

两步分工：slice_files 只碰文件系统，attach 只碰数据库。Celery worker 里
两步之间必须关掉会话——解码写盘 1–3 秒，攥着连接会把连接池白占一个。
"""

import io
import logging
from pathlib import Path

import librosa
import soundfile as sf
from sqlalchemy.orm import Session

from app.common import storage
from app.models.demo import Segment
from app.repositories import audio_repo

logger = logging.getLogger(__name__)

# 与 analyze_service 的状态：分析链路就按 16k 单声道读参考轨，切出来的段
# 直接喂进去不用再重采样
SR = 16000
ACCESS_PUBLIC = "public"


def slice_files(
    source_path: Path, bounds: list[tuple[int, float, float]]
) -> list[dict]:
    """按 [(seq, start_sec, end_sec)] 切整曲，返回 [{seq, file_path, file_size, duration_sec}]。

    切的是**原始整曲**（含伴奏），不是 Demucs 分离出的人声：分析侧本来就对输入
    做 HPSS 压伴奏，换成人声轨会改变现有分析口径。
    """
    usable = [(seq, float(s), float(e)) for seq, s, e in bounds if e > s]
    if not usable:
        return []

    limit = max(e for _, _, e in usable) + 1.0
    y, _ = librosa.load(str(source_path), sr=SR, mono=True, duration=limit)

    slices: list[dict] = []
    for seq, start, end in usable:
        chunk = y[int(start * SR):int(end * SR)]
        if chunk.size == 0:
            continue
        buf = io.BytesIO()
        sf.write(buf, chunk, SR, format="WAV", subtype="PCM_16")
        stored_path, size = storage.save_bytes(buf.getvalue(), subdir="segments")
        slices.append({
            "seq": seq,
            "file_path": stored_path,
            "file_size": size,
            "duration_sec": round(chunk.size / SR, 3),
        })
    return slices


def attach(
    db: Session,
    *,
    demo_title: str,
    uploader_id: int | None,
    slices: list[dict],
    segments: list[Segment],
) -> None:
    """给每份切片登记 audio_files，并挂到同 seq 的分段上。只 flush，不 commit。

    segments 必须是本次刚插入的那批（replace_segments 的返回值）——按 seq
    而不是 id 关联，调用方拿不到自增 id 的顺序保证。
    """
    by_seq = {s.seq: s for s in segments}
    for item in slices:
        segment = by_seq.get(item["seq"])
        if segment is None:
            continue
        audio = audio_repo.create(
            db,
            uploader_id=uploader_id,
            file_path=item["file_path"],
            original_name=f"{demo_title}_第{item['seq']}段.wav",
            file_size=item["file_size"],
            access=ACCESS_PUBLIC,
        )
        audio.duration_sec = item["duration_sec"]
        segment.audio_id = audio.id
    db.flush()
```

- [ ] **Step 3: 同步 spec 的函数名**

把 spec「切片实现」一节里的 `slice_and_attach(...)` 改成 `slice_files(...)` + `attach(...)`，并补一句：拆两步是为了让 worker 在解码期间不持有数据库连接。

- [ ] **Step 4: 临时脚本验证切片**

写 `/tmp/verify_slice.py`：

```python
import sys
from pathlib import Path

sys.path.insert(0, "/Users/meiyazhao/Documents/lianshu/operaAI")

from app.common import storage
from app.db import session_scope
from app.models.demo import TeacherDemo
from app.services import segment_audio_service

with session_scope() as db:
    demo = db.query(TeacherDemo).filter(TeacherDemo.audio_id.isnot(None)).first()
    assert demo is not None, "库里没有绑定音频的示范曲目"
    src = storage.resolve(demo.audio.file_path)
    print("source:", src, "duration:", demo.audio.duration_sec)

slices = segment_audio_service.slice_files(src, [(1, 0.0, 3.0), (2, 5.0, 6.5)])
assert len(slices) == 2, slices
for item in slices:
    path = storage.resolve(item["file_path"])
    print(item["seq"], item["file_path"], item["file_size"], item["duration_sec"])
    assert path.is_file()
    assert abs(item["duration_sec"] - (3.0 if item["seq"] == 1 else 1.5)) < 0.05
    path.unlink()

print("OK")
```

Run: `.venv/bin/python /tmp/verify_slice.py`

Expected: 两行切片信息，`duration_sec` 分别约 3.0 / 1.5，末尾 `OK`。

- [ ] **Step 5: Commit**

```bash
git add app/common/storage.py app/services/segment_audio_service.py docs/superpowers/specs/2026-10-20-segment-audio-slicing-design.md
git commit -m "feat: 新增分段音频切片与登记服务"
```

---

### Task 3: Demucs 解析路径接入切片 + 重入清理

**Files:**
- Modify: `app/services/parse_service.py`（`_split_segments`、新增 `_save_results`、`_parse`）
- Modify: `app/repositories/library_repo.py`（`replace_segments` 返回新行；新增 `segment_audio_ids`、`audio_paths_by_ids`、`delete_audio_rows`）

**Interfaces:**
- Consumes: `segment_audio_service.slice_files` / `.attach`（Task 2）
- Produces:
  - `_split_segments(y, sr) -> list[dict]`，每项多 `start`/`end`（秒，非采样点）
  - `library_repo.replace_segments(db, demo_id, segments) -> list[Segment]`（原本返回 `None`）
  - `library_repo.segment_audio_ids(db, demo_id) -> list[int]`
  - `library_repo.audio_paths_by_ids(db, audio_ids) -> list[str]`
  - `library_repo.delete_audio_rows(db, audio_ids) -> None`

- [ ] **Step 1: `_split_segments` 补回边界**

`app/services/parse_service.py` 里把返回值改成（同时改掉 docstring 中「duration 只落时长、不落起止时间」那段的后半句）：

```python
    return [
        {
            "seq": i,
            "title": f"第 {i} 段",
            "duration": round((e - s) / sr, 3),
            # start/end 只给切片用，不入库（segments 不加 start/end 列）
            "start": round(s / sr, 3),
            "end": round(e / sr, 3),
        }
        for i, (s, e) in enumerate(kept, start=1)
    ]
```

docstring 改为：

```python
    """把 16k 单声道人声轨按停顿切成唱段，返回
    [{seq, title, duration, start, end}]（时间单位：秒）。

    start/end 只用于把原始整曲切成分段音频，不入库——segments 没有起止列，
    前端也就做不了「点击定位到该段」。最后那步回退是刻意的：任何输入都要有
    分段、都要能走到 `parsed` 终态。没有它，一段全静音的人声轨（分离失败、
    纯伴奏）会让 segments 一行不落，而前端还在轮询一个永远不会到来的 `parsed`。
    """
```

- [ ] **Step 2: `library_repo` 三个新函数 + `replace_segments` 返回值**

`app/repositories/library_repo.py`：

`replace_segments` 末尾把 `db.flush()` 换成返回新行：

```python
def replace_segments(db: Session, demo_id: int, segments: list[dict]) -> list[Segment]:
    """整批替换某 demo 的分段：先按 demo_id DELETE，再 INSERT，返回新插入的行。

    返回的是**新行**（自增 id 已就位），调用方靠它按 seq 挂分段音频。
    其余口径见原 docstring：不用 upsert 是因为段数可能变少；只 flush 不 commit。
    """
    db.execute(delete(Segment).where(Segment.demo_id == demo_id))
    rows = [
        Segment(
            demo_id=demo_id,
            seq=s["seq"],
            title=s["title"],
            lyrics_json=s.get("lyrics"),
            duration=s["duration"],
        )
        for s in segments
    ]
    db.add_all(rows)
    db.flush()
    return rows
```

同文件追加：

```python
def segment_audio_ids(db: Session, demo_id: int) -> list[int]:
    """某 demo 现有分段挂着的音频 id。重入解析前先取，替完再删旧行。"""
    return [i for i in db.scalars(
        select(Segment.audio_id).where(Segment.demo_id == demo_id)
    ) if i is not None]


def audio_paths_by_ids(db: Session, audio_ids: list[int]) -> list[str]:
    """audio_files.file_path 批量查。取不到（历史脏 id）就是空列表。"""
    if not audio_ids:
        return []
    return list(db.scalars(
        select(AudioFile.file_path).where(AudioFile.id.in_(audio_ids))
    ))


def delete_audio_rows(db: Session, audio_ids: list[int]) -> None:
    """删掉分段音频的登记行。**必须先删 segments**（replace_segments），
    否则 segments.audio_id 的外键会挡住。磁盘文件由调用方在提交后 unlink。"""
    if not audio_ids:
        return
    db.execute(delete(AudioFile).where(AudioFile.id.in_(audio_ids)))
    db.flush()
```

- [ ] **Step 3: `_parse` 接入切片，新增 `_save_results`**

`app/services/parse_service.py` 的 `_parse` 改成：

```python
def _parse(demo_id: int) -> None:
    """跑在 worker 进程里，没有请求上下文，所以自己开 session_scope()，不走 get_db()。
    会话**分三段开、中间不留连接**：Demucs 要跑 8–15 分钟，切片还要解码 1–3 秒，
    攥着连接不放会把连接池（pool_size=5）白占一个。
    """
    # --- 取路径与旧分段音频（短会话）---
    with session_scope() as db:
        demo, path = _require_demo(db, demo_id)
        uploader_id = demo.audio.uploader_id
        demo_title = demo.title or ""
        old_audio_ids = library_repo.segment_audio_ids(db, demo_id)
        old_paths = _resolve_all(library_repo.audio_paths_by_ids(db, old_audio_ids))

    duration = audio_service.probe_duration(path)

    # --- 人声分离（8–15 分钟，进度停在 20%）---
    _enter_stage(demo_id, STAGE_SEPARATE, "正在分离人声，单条约需 8–15 分钟，请勿关闭页面…")
    y = vocal_service.separate_vocal(path)

    # --- 唱段切分（秒级，进度 50%）---
    _enter_stage(demo_id, STAGE_SEGMENT, "正在按停顿切分唱段…")
    segments = _split_segments(y, vocal_service.SR)

    # --- 分段音频切片（1–3 秒，进度 80%）---
    _enter_stage(demo_id, STAGE_SAVE, "正在切分分段音频并写入分段…")
    slice_failed = False
    slices: list[dict] = []
    try:
        slices = segment_audio_service.slice_files(
            path, [(s["seq"], s["start"], s["end"]) for s in segments]
        )
    except Exception:
        # 切片失败不该让整条解析作废：分段照落，分析自动回退整曲
        logger.exception("示范 %s 的分段音频切片失败，分析将回退整曲", demo_id)
        slice_failed = True

    # --- 结果入库（毫秒级）---
    _save_results(
        demo_id,
        demo_title=demo_title,
        uploader_id=uploader_id,
        segments=segments,
        slices=slices,
        duration=duration,
        old_audio_ids=old_audio_ids,
        old_paths=old_paths,
    )

    # --- 终态 ---
    note = f" · {TRUNCATE_NOTE}" if duration and duration > vocal_service.MAX_AUDIO_SEC else ""
    if slice_failed:
        note += " · 分段音频未生成"
    task_repo.update(
        demo_id,
        status=STATUS_PARSED,
        progress=100,
        stage=STAGE_SAVE,
        message=f"解析完成，共 {len(segments)} 段{note}",
    )
```

同文件追加两个内部函数（放在 `_parse` 之后）：

```python
def _resolve_all(stored_names: list[str]) -> list[Path]:
    """file_path → 磁盘路径。脏数据抛错时宁可少删一个文件，也不能中断解析。"""
    paths: list[Path] = []
    for name in stored_names:
        try:
            paths.append(storage.resolve(name))
        except BusinessError:
            logger.warning("分段音频路径非法，跳过删除：%s", name)
    return paths


def _save_results(
    demo_id: int,
    *,
    demo_title: str,
    uploader_id: int | None,
    segments: list[dict],
    slices: list[dict],
    duration: float | None,
    old_audio_ids: list[int],
    old_paths: list[Path],
) -> None:
    """一次事务写完全部分段与切片，提交后再删旧文件。"""
    with session_scope() as db:
        rows = library_repo.replace_segments(db, demo_id, segments)
        if slices:
            segment_audio_service.attach(
                db,
                demo_title=demo_title,
                uploader_id=uploader_id,
                slices=slices,
                segments=rows,
            )
        library_repo.delete_audio_rows(db, old_audio_ids)
        if duration is not None:
            library_repo.update_audio_duration(db, demo_id, duration)

    for path in old_paths:
        path.unlink(missing_ok=True)
```

顶部 import 补 `from app.services import audio_service, segment_audio_service, vocal_service`（把原来那行改成三模块）。

- [ ] **Step 4: 临时脚本验证切分边界**

写 `/tmp/verify_split.py`：

```python
import sys

sys.path.insert(0, "/Users/meiyazhao/Documents/lianshu/operaAI")

import numpy as np

from app.services.parse_service import _split_segments

sr = 16000
tone = lambda n: (0.5 * np.sin(2 * np.pi * 440 * np.arange(n) / sr)).astype(np.float32)
y = np.concatenate([np.zeros(sr, np.float32), tone(sr), np.zeros(sr, np.float32),
                    tone(sr * 2), np.zeros(sr, np.float32)])
segs = _split_segments(y, sr)
for s in segs:
    print(s)
assert len(segs) == 2, segs
assert abs(segs[0]["start"] - 1.0) < 0.15 and abs(segs[0]["end"] - 2.0) < 0.15
assert abs(segs[1]["start"] - 3.0) < 0.15 and abs(segs[1]["end"] - 5.0) < 0.15
print("OK")
```

Run: `.venv/bin/python /tmp/verify_split.py`

Expected: 两段，`start/end` 约 `(1.0, 2.0)` 与 `(3.0, 5.0)`，末尾 `OK`。

- [ ] **Step 5: 临时脚本验证 `_save_results`（用一次性 demo，跑完清干净）**

写 `/tmp/verify_save_results.py`：

```python
import sys

sys.path.insert(0, "/Users/meiyazhao/Documents/lianshu/operaAI")

from sqlalchemy import delete, select

from app.common import storage
from app.db import session_scope
from app.models.audio import AudioFile
from app.models.demo import Segment, TeacherDemo
from app.repositories import audio_repo
from app.services import parse_service

with session_scope() as db:
    src_demo = db.query(TeacherDemo).filter(TeacherDemo.audio_id.isnot(None)).first()
    assert src_demo is not None
    src_audio = src_demo.audio
    clone = audio_repo.create(
        db, uploader_id=src_audio.uploader_id, file_path=src_audio.file_path,
        original_name="临时验证.wav", file_size=src_audio.file_size, access="public",
    )
    demo = TeacherDemo(title="临时验证", audio_id=clone.id)
    db.add(demo)
    db.flush()
    demo_id, clone_id, src_path = demo.id, clone.id, storage.resolve(clone.file_path)

segments = [
    {"seq": 1, "title": "第 1 段", "duration": 2.0, "start": 0.0, "end": 2.0},
    {"seq": 2, "title": "第 2 段", "duration": 1.0, "start": 3.0, "end": 4.0},
]
slices = parse_service.segment_audio_service.slice_files(
    src_path, [(s["seq"], s["start"], s["end"]) for s in segments]
)
parse_service._save_results(
    demo_id, demo_title="临时验证", uploader_id=clone.uploader_id,
    segments=segments, slices=slices, duration=10.0,
    old_audio_ids=[], old_paths=[],
)

with session_scope() as db:
    rows = db.scalars(select(Segment).where(Segment.demo_id == demo_id).order_by(Segment.seq)).all()
    assert len(rows) == 2 and all(r.audio_id for r in rows), rows
    audios = [db.get(AudioFile, r.audio_id) for r in rows]
    assert all(a and a.access == "public" for a in audios)
    print([(r.seq, r.audio_id, a.duration_sec) for r, a in zip(rows, audios)])
    slice_paths = [storage.resolve(a.file_path) for a in audios]

# 第二次跑同一 demo：旧切片行与文件都该被清掉
parse_service._save_results(
    demo_id, demo_title="临时验证", uploader_id=clone.uploader_id,
    segments=segments, slices=[], duration=10.0,
    old_audio_ids=[r.audio_id for r in rows], old_paths=slice_paths,
)
with session_scope() as db:
    assert db.scalars(select(Segment).where(Segment.demo_id == demo_id)).all()
    assert all(not p.exists() for p in slice_paths), "旧切片文件未删除"
    assert not db.get(AudioFile, audios[0].id), "旧切片登记行未删除"
    db.execute(delete(Segment).where(Segment.demo_id == demo_id))
    db.execute(delete(TeacherDemo).where(TeacherDemo.id == demo_id))
    db.execute(delete(AudioFile).where(AudioFile.id == clone_id))
print("OK")
```

Run: `.venv/bin/python /tmp/verify_save_results.py`

Expected: 打印两段 `(seq, audio_id, duration_sec≈2.0/1.0)`，末尾 `OK`，且临时 demo/段/音频行都已被删除（脚本自己清理）。

- [ ] **Step 6: Commit**

```bash
git add app/services/parse_service.py app/repositories/library_repo.py
git commit -m "feat: Demucs 解析按段切分示范音频并在重入时清理旧切片"
```

---

### Task 4: Excel 上传路径接入切片

**Files:**
- Modify: `app/services/lyrics_excel.py:93-117`（`_parse_page` 返回 `start`/`end`）
- Modify: `app/services/library_service.py:125-153`（`demo_library_add_with_segments`）

**Interfaces:**
- Consumes: `segment_audio_service.slice_files` / `.attach`、`replace_segments` 的新返回值（Task 2/3）
- Produces: `lyrics_excel.parse_segments(blob)` 每页多 `start`/`end`（全局秒）；这两个键不入库。

- [ ] **Step 1: `_parse_page` 保留全局边界**

把 `_parse_page` 末尾改成：

```python
    starts = [c["start"] for c in lyrics if c["start"] is not None]
    if not starts:
        # 整页没标时间（如第 1、2 段，那些字唱在被剪掉的开头里）：字照存、
        # 时间全空，duration 也给 None——前端对段长非有限值有「时长未知」分支。
        duration = None
        span = {}
    else:
        base = min(starts)
        for char in lyrics:
            char["start"] = _rel(char["start"], base)
            char["end"] = _rel(char["end"], base)
        ends = [char["end"] for char in lyrics if char["end"] is not None]
        # 该页最后一个有时间的字的 end（已转相对）就是段长。中间缺时间的字
        # 只是没有自己的 start/end，不影响这个值（spec 3.3）。
        duration = ends[-1] if ends else None
        # start/end 是**全局秒**，只给切片用；上面已经把它们转成段内相对时间。
        span = {"start": base, "end": base + duration} if duration is not None else {}

    return {
        "seq": seq,
        "title": title or f"第 {seq} 段",
        "duration": duration,
        "lyrics": lyrics,
        **span,
    }
```

`parse_segments` 的 docstring 返回值说明改成 `[{seq, title, duration, lyrics, start?, end?}]`，并补一句：`start/end` 是该页在整曲里的全局秒，只用于切分段音频。

- [ ] **Step 2: `demo_library_add_with_segments` 调用切片**

```python
def demo_library_add_with_segments(
    db: Session,
    *,
    title: str,
    role: str | None = None,
    banshi: str | None = None,
    audio: AudioFile,
    segments: list[dict],
    commit: bool = True,
) -> TeacherDemo:
    """带逐字数据的示范上传：建 demo + 写 segments + 切分段音频 + 回填音频时长。

    **这里的 commit 是这条链路唯一的提交点**：调它之前不能有任何提交，否则
    解析失败就撤不干净。逐字数据的解析已经在调用方做完并先于落盘——坏文件
    连音频文件都不会落盘（spec 3.1、3.4）。

    与 Demucs 那条路的区别：段边界由唱词句给出，不再需要停顿切分，所以不投
    解析任务；切片失败也不拦上传——该段没有音频时 B2 自动回退整曲。
    """
    demo = demo_library_add(
        db, title=title, role=role, banshi=banshi, audio_id=audio.id, commit=False
    )
    rows = library_repo.replace_segments(db, demo.id, segments)

    bounds = [
        (s["seq"], s["start"], s["end"])
        for s in segments
        if s.get("start") is not None and s.get("end") is not None
    ]
    if bounds:
        try:
            slices = segment_audio_service.slice_files(
                storage.resolve(audio.file_path), bounds
            )
            segment_audio_service.attach(
                db,
                demo_title=title,
                uploader_id=audio.uploader_id,
                slices=slices,
                segments=rows,
            )
        except Exception:
            logger.exception("示范 %s 的分段音频切片失败，分析将回退整曲", title)

    duration = audio_service.probe_duration(storage.resolve(audio.file_path))
    if duration is not None:
        library_repo.update_audio_duration(db, demo.id, duration)
    if commit:
        db.commit()
    return demo
```

顶部 import 里把 `from app.services import audio_service, parse_service` 补成 `from app.services import audio_service, parse_service, segment_audio_service`，并确认有 `logger`（文件内已有则复用，没有就加 `logger = logging.getLogger(__name__)` 与 `import logging`）。

- [ ] **Step 3: 端到端验证（Excel 路径）**

先起后端（另开一个终端，见 CLAUDE.md「运行方式」），再在项目根执行：

```bash
curl -s -c /tmp/ck.txt -X POST http://127.0.0.1:8877/api/auth/login \
  -H 'Content-Type: application/json' -d '{"username":"teacher01","password":"xiyun@2026"}' | head -c 200
```

Expected: `"code":0`

用一个短音频 + 一份「第1段_…」格式的 Excel 走上传（Excel 由临时脚本用 openpyxl 生成到 `/tmp/demo.xlsx`，两页各两个字并标全局时间）：

```bash
curl -s -b /tmp/ck.txt -X POST http://127.0.0.1:8877/api/demo/library/upload \
  -F 'title=切片验证' -F 'access=public' \
  -F 'audio=@/tmp/demo.wav' -F 'excel=@/tmp/demo.xlsx'
```

Expected: `{"code":0,...,"data":{"demo_id":<id>,"task_id":null}}`

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -c \
  "SELECT s.seq, s.duration, s.audio_id, a.file_path, a.duration_sec FROM segments s LEFT JOIN audio_files a ON a.id = s.audio_id WHERE s.demo_id = <id> ORDER BY s.seq;"
```

Expected: 每行 `audio_id` 非空，`duration_sec` 与 `duration` 差值 < 0.1；`file_path` 形如 `segments/<hex>.wav`，且 `ls uploads/segments/` 能看到对应文件。

- [ ] **Step 4: Commit**

```bash
git add app/services/lyrics_excel.py app/services/library_service.py
git commit -m "feat: Excel 上传示范时按页切分分段音频"
```

---

### Task 5: B2 参考轨改为优先段音频

**Files:**
- Modify: `app/repositories/audio_repo.py:50-65`

**Interfaces:**
- Consumes: `segments.audio_id`（Task 1）
- Produces: `audio_repo.get_segment_teacher_audio(db, segment_id)` 行为变更：优先段音频、回退整曲。签名不变，`analyze_service` 不用改。

- [ ] **Step 1: 改 `get_segment_teacher_audio`**

```python
def get_segment_teacher_audio(db: Session, segment_id: int) -> AudioFile | None:
    """分段要用的示范音频：优先该段切出来的音频，没有则回退整首（B2 模式二）。

    历史示范（切分上线前解析的）没有 segments.audio_id，走回退分支，行为与
    改造前完全一致。分段不存在、或剧目没绑音频，都返回 None——调用方统一
    当作 404 处理，对前端而言「这个分段现在没法比对」是同一种情况。
    """
    segment = db.get(Segment, segment_id)
    if segment is None:
        return None

    if segment.audio_id is not None:
        audio = db.get(AudioFile, segment.audio_id)
        if audio is not None:
            return audio

    if segment.demo_id is None:
        return None
    demo = db.get(TeacherDemo, segment.demo_id)
    if demo is None or demo.audio_id is None:
        return None
    return db.get(AudioFile, demo.audio_id)
```

- [ ] **Step 2: 临时脚本验证回退链**

写 `/tmp/verify_teacher_audio.py`：

```python
import sys

sys.path.insert(0, "/Users/meiyazhao/Documents/lianshu/operaAI")

from sqlalchemy import select

from app.db import session_scope
from app.models.demo import Segment, TeacherDemo
from app.repositories import audio_repo

with session_scope() as db:
    sliced = db.scalars(select(Segment).where(Segment.audio_id.isnot(None))).first()
    legacy = db.scalars(select(Segment).where(Segment.audio_id.is_(None))).first()
    if sliced is not None:
        got = audio_repo.get_segment_teacher_audio(db, sliced.id)
        assert got.id == sliced.audio_id, (got.id, sliced.audio_id)
        print("段音频命中:", sliced.id, got.id)
    if legacy is not None and legacy.demo_id is not None:
        demo = db.get(TeacherDemo, legacy.demo_id)
        if demo is not None and demo.audio_id is not None:
            got = audio_repo.get_segment_teacher_audio(db, legacy.id)
            assert got.id == demo.audio_id, (got.id, demo.audio_id)
            print("整曲回退:", legacy.id, got.id)
    assert audio_repo.get_segment_teacher_audio(db, -1) is None
print("OK")
```

Run: `.venv/bin/python /tmp/verify_teacher_audio.py`

Expected: 至少打印「段音频命中」一行（Task 4 产生的数据），有历史段时再打印「整曲回退」，末尾 `OK`。

- [ ] **Step 3: 走一次真实 B2→B4，确认参考轨是段音频**

起后端 + 分析 worker（`celery -A app.worker:celery_app worker --loglevel=info --pool=solo`），用 Task 4 上传的 demo 的某个段 + 一段学生录音：

```bash
curl -s -b /tmp/ck.txt -X POST http://127.0.0.1:8877/api/audio/upload -F 'audio=@/tmp/student.wav'
# 记下返回的 file_id，然后
curl -s -b /tmp/ck.txt -X POST http://127.0.0.1:8877/api/analyze/submit \
  -H 'Content-Type: application/json' -d '{"segment_id":<段id>,"student_audio_id":<file_id>}'
```

轮询 `/api/analyze/status/<task_id>` 到 `done` 后取 `/api/analyze/result/<task_id>`，确认参考轨长度是段长而不是整曲长：

```bash
curl -s -b /tmp/ck.txt http://127.0.0.1:8877/api/analyze/result/<task_id> \
  | .venv/bin/python -c "import json,sys; print(json.load(sys.stdin)['data']['timeline']['duration'])"
```

Expected: 打印值 ≤ 该段 `duration` + 0.5（**不是**整曲长度）。

- [ ] **Step 4: Commit**

```bash
git add app/repositories/audio_repo.py
git commit -m "feat: B2 参考轨优先使用分段示范音频，缺失时回退整曲"
```

---

### Task 6: 文档同步

**Files:**
- Modify: `DOC_ISSUES.md`（追加第 45 条，在「待核实」之前）
- Modify: `CLAUDE.md`（「示范库解析链路（Demucs）」小节）

**Interfaces:** 无代码接口，只是把口径写进真源。

- [ ] **Step 1: `DOC_ISSUES.md` 追加第 45 条**

```markdown
## 45. 分段音频是否存在、切自哪条音轨、B2 参考轨取段还是取整曲，文档均未规定

《4-数据库设计》的 `segments` 没有音频字段，《5-接口清单》B2 只写「基准=该分段示范」，
没说这个「分段示范」是整曲还是切出来的段；PRD 也没提上传时要产出分段音频。

本轮口径（spec `docs/superpowers/specs/2026-10-20-segment-audio-slicing-design.md`）：

- `segments.audio_id` 指向该段的示范音频（`audio_files` 一行，`access=public`）；
- 切的是**原始整曲**（含伴奏），16k 单声道 WAV，不是 Demucs 分离出的人声；
- B2 模式二优先用段音频，`audio_id` 为空（历史数据、Excel 页无时间）时回退整曲；
- 跟唱页「播放示范」仍播整首，不在本轮范围内。
```

- [ ] **Step 2: `CLAUDE.md` 补一段**

在「示范库解析链路（Demucs）」小节的 `TOP_DB` 段落之后插入：

```markdown
- **分段音频（`segments.audio_id`）自 2026-10-20 起落库**：解析（或 Excel 上传）时按段边界从**原始整曲**切出 16k 单声道 WAV，存 `uploads/segments/`，每段一行 `audio_files`（`access=public`）。B2 模式二的参考轨优先用它，为空时回退整曲（历史曲目、Excel 里没有时间的页）。跟唱页「播放示范」仍播整首，不要顺手改成段音频——进度基准是按段算的，会串。切分失败不影响 `parsed` 终态，只记日志并在 message 里提示。
```

- [ ] **Step 3: Commit**

```bash
git add DOC_ISSUES.md CLAUDE.md
git commit -m "docs: 登记分段音频口径（DOC_ISSUES 第 45 条）"
```

---

## 自检

- 覆盖 spec 每一节：数据模型 → Task 1；切片实现 → Task 2；两条路径 → Task 3/4；消费端 → Task 5；失败与边界 → Task 3/4 的 try/except 与回退；偏差登记 → Task 6。
- 无占位符、无「同 Task N」省略。
- 名称一致：`slice_files` / `attach` / `_save_results` / `segment_audio_ids` / `audio_paths_by_ids` / `delete_audio_rows` 在各 Task 间一致。

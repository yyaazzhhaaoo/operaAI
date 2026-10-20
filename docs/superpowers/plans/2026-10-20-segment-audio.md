# 示范分段音频与跟唱对比基线 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Demucs 解析示范音频时按唱段切出独立混音音频，并让实时跟唱页的「开始跟唱」以该段音频作为对比分析基线、以该段音频作为示范播放源。

**Architecture:** 在 `segments` 表增加 `audio_id` 外键；解析管线用 Demucs 算出的时间区间从原文件切出混音 WAV，登记 `audio_files` 并回填 `segments.audio_id`。B2 的教师轨解析优先取该列，前端 C2 拿到每段 `url` 后按段播放。全程不改变 D1/B2/B3/B4 契约。

**Tech Stack:** Python 3.11 / Flask / SQLAlchemy / PostgreSQL / librosa / soundfile / Celery / 原生 HTML+JS。

**Spec:** `docs/superpowers/specs/2026-10-20-segment-audio-design.md`

## Global Constraints

- 所有文档、注释、提交信息使用简体中文，UTF-8；代码标识符保持英文。
- Python 3.11；依赖清单是 `requirements.txt`，不引入 pytest 或新依赖。
- 表结构唯一真源是 `schema.sql`；模型只做映射，不引入 Alembic。
- 不修改需求文档目录（`/home/myz/lianshu/艺校_docs/`），差异登记 `DOC_ISSUES.md`。
- 不自动 `git commit`/`git push`，除非用户明确要求。
- 所有日期、时间展示按北京时间；本计划不涉及新增时间列。
- 本地验证一律在项目根目录、激活 `.venv` 后执行。

---

### Task 1: `segments` 增加 `audio_id`

**Files:**
- Modify: `schema.sql:66-73`
- Modify: `app/models/demo.py:32-44`
- Test: `scripts/check_db.py`

**Interfaces:**
- Produces: `segments.audio_id`（`INT NULL`，外键 `audio_files.id`）；ORM `Segment.audio_id: int | None`。

- [ ] **Step 1: 改写 `schema.sql` 的 `segments` 表**

```sql
CREATE TABLE segments (
  id SERIAL PRIMARY KEY,
  demo_id INT REFERENCES teacher_demos(id),
  seq INT,
  title VARCHAR(100),
  lyrics_json JSONB,   -- [{word,midi,start,end,note,tip}]，tip=功能2.4唱前提示
  duration FLOAT,
  audio_id INT REFERENCES audio_files(id)  -- 该段独立音频（Demucs 解析产出）；NULL=无
);
```

- [ ] **Step 2: 同步 ORM 模型**

在 `app/models/demo.py` 的 `Segment` 类中，`duration` 之后加：

```python
    # 该唱段独立的混音切片（Demucs 解析产出）。Excel 路径与旧数据为 NULL，
    # B2 解析教师轨时会回退到 teacher_demos.audio_id。
    audio_id: Mapped[int | None] = mapped_column(ForeignKey("audio_files.id"))
```

- [ ] **Step 3: 对活库执行 DDL**

```bash
.venv/bin/python - <<'PY'
from sqlalchemy import text
from app.db import engine

with engine.begin() as conn:
    conn.execute(text(
        "ALTER TABLE segments ADD COLUMN IF NOT EXISTS audio_id INT REFERENCES audio_files(id)"
    ))
print("segments.audio_id 已就绪")
PY
```

- [ ] **Step 4: 跑一致性闸门**

Run: `.venv/bin/python scripts/check_db.py`
Expected: 退出码 0，输出无差异（列数变为 111、外键变为 23）。

- [ ] **Step 5: 记录本步结果（不提交 git）**

在实现日志里记录：DDL 执行时间、`check_db.py` 输出、目标库地址（`.env` 的 `DATABASE_URL` 主机名）。

---

### Task 2: 存储与仓储层支持生成音频

**Files:**
- Modify: `app/common/storage.py`（文件末尾新增两个函数）
- Modify: `app/repositories/audio_repo.py:1-40`
- Test: `python -c` 内联检查

**Interfaces:**
- Produces:
  - `storage.save_generated(samples, sr: int, *, subdir: str, suffix: str = ".wav") -> tuple[str, int]`
  - `storage.remove(stored_name: str) -> None`
  - `audio_repo.create(..., duration_sec: float | None = None) -> AudioFile`
  - `audio_repo.delete_ids(db: Session, ids: list[int]) -> None`

- [ ] **Step 1: 在 `app/common/storage.py` 末尾新增**

```python
def save_generated(
    samples, sr: int, *, subdir: str, suffix: str = ".wav"
) -> tuple[str, int]:
    """把内存里的音频样本写成 WAV，返回 (相对 uploads/ 的路径, 字节数)。

    samples 形状与 librosa.load(mono=False) 一致：(channels, frames) 或一维
    (frames,)。soundfile.write 要的是 (frames, channels)，这里负责转置。

    与 save() 一样，只允许写到 uploads/ 之内；subdir 由本仓库代码显式传入。
    """
    import numpy as np
    import soundfile as sf

    data = np.asarray(samples)
    if data.ndim == 1:
        data = data[:, None]
    else:
        data = data.T

    root = settings.upload_dir.resolve()
    dest_dir = (root / subdir).resolve()
    if dest_dir != root and root not in dest_dir.parents:
        raise BusinessError(400, "非法的存储子目录")

    dest = dest_dir / f"{uuid.uuid4().hex}{suffix}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    sf.write(dest, data, sr)

    size = dest.stat().st_size
    if size == 0:
        dest.unlink(missing_ok=True)
        raise BusinessError(400, "生成的音频为空")
    return dest.relative_to(root).as_posix(), size


def remove(stored_name: str) -> None:
    """删除一个存储文件；路径非法或文件已不在都静默返回。"""
    try:
        path = resolve(stored_name)
    except BusinessError:
        return
    path.unlink(missing_ok=True)
```

- [ ] **Step 2: 扩展 `audio_repo.create`**

把签名与构造改成：

```python
def create(
    db: Session,
    *,
    uploader_id: int | None,
    file_path: str,
    original_name: str | None,
    file_size: int,
    access: str,
    duration_sec: float | None = None,
) -> AudioFile:
    audio = AudioFile(
        uploader_id=uploader_id,
        file_path=file_path,
        original_name=original_name,
        file_size=file_size,
        duration_sec=duration_sec,
        access=access,
    )
    db.add(audio)
    db.flush()
    return audio
```

- [ ] **Step 3: 在 `app/repositories/audio_repo.py` 增加批量删除**

在文件末尾加（并把顶部 `from sqlalchemy import select` 改成 `from sqlalchemy import delete, select`）：

```python
def delete_ids(db: Session, ids: list[int]) -> None:
    """按主键批量删除音频登记。只 flush 不 commit，事务边界在 service 层。

    segments.audio_id 的外键行必须先于本调用删除，否则会撞外键约束。
    """
    if not ids:
        return
    db.execute(delete(AudioFile).where(AudioFile.id.in_(ids)))
```

- [ ] **Step 4: 验证生成音频可写可读**

```bash
.venv/bin/python - <<'PY'
import numpy as np
from app.common import storage
import librosa

sr = 16000
tone = 0.2 * np.sin(2 * np.pi * 440 * np.arange(sr) / sr)
path, size = storage.save_generated(tone, sr, subdir="segments/_smoke")
assert path.startswith("segments/_smoke/") and size > 0
y, got_sr = librosa.load(str(storage.resolve(path)), sr=None)
assert got_sr == sr and len(y) == sr
storage.remove(path)
print("save_generated/remove ok", path, size)
PY
```

Expected: 打印 `save_generated/remove ok ...`，无异常。

- [ ] **Step 5: 验证删除不存在的路径是静默的**

```bash
.venv/bin/python -c "from app.common import storage; storage.remove('../etc/passwd'); storage.remove('segments/_smoke/nope.wav'); print('remove 静默 ok')"
```

Expected: 打印 `remove 静默 ok`。

---

### Task 3: 解析管线切分音频并回填 `audio_id`

**Files:**
- Modify: `app/services/parse_service.py:104-125`（`_split_segments`）
- Modify: `app/services/parse_service.py:290-328`（`_parse`）
- Modify: `app/repositories/library_repo.py:59-87`（`replace_segments`）
- Test: `python -c` 内联检查 + Task 7 的全链路脚本

**Interfaces:**
- Consumes: `storage.save_generated`、`audio_repo.create(duration_sec=...)`、`audio_repo.delete_ids`。
- Produces: `_split_segments` 的每项额外含 `start`/`end`（秒）；`replace_segments` 支持 `audio_id` 键。

- [ ] **Step 1: 让 `_split_segments` 返回起止秒数**

把 `return` 改成：

```python
    return [
        {
            "seq": i,
            "title": f"第 {i} 段",
            "duration": round((e - s) / sr, 3),
            # start/end 只给切片用，不进 segments 表
            "start": round(s / sr, 3),
            "end": round(e / sr, 3),
        }
        for i, (s, e) in enumerate(kept, start=1)
    ]
```

- [ ] **Step 2: 新增切片函数**

放在 `_merge_intervals` 之后：

```python
def _slice_segment_audio(
    demo_id: int, path: Path, segments: list[dict]
) -> list[dict]:
    """按 segments 的 start/end 从原始混音切出每段音频并落盘。

    时间边界来自 16k 的人声轨，这里按秒切原生采样率的原文件、保留声道数。
    返回新列表，每项带 audio_path / file_size / duration（按切片实际长度）。
    """
    y, sr = librosa.load(
        str(path), sr=None, mono=False, duration=vocal_service.MAX_AUDIO_SEC
    )
    if y.size == 0:
        raise BusinessError(400, "音频是空的，无法切分唱段")

    samples = y if y.ndim == 2 else y[None, :]
    total = samples.shape[1]

    out: list[dict] = []
    for seg in segments:
        start = max(0, min(int(round(seg["start"] * sr)), total))
        end = max(start, min(int(round(seg["end"] * sr)), total))
        clip = samples[:, start:end]
        if clip.shape[1] == 0:
            raise BusinessError(400, f"第 {seg['seq']} 段切分结果为空")

        audio_path, file_size = storage.save_generated(
            clip, sr, subdir=f"segments/{demo_id}"
        )
        out.append({
            "seq": seg["seq"],
            "title": seg["title"],
            "duration": round(clip.shape[1] / sr, 3),
            "audio_path": audio_path,
            "file_size": file_size,
        })
    return out
```

- [ ] **Step 3: 改写 `_parse` 的保存阶段**

把 `_parse` 从「--- 结果入库 ---」到函数末尾替换为：

```python
    # --- 结果入库（切音频 + 写分段，进度 80%）---
    _enter_stage(demo_id, STAGE_SAVE, "正在切分唱段音频并写入数据库…")
    # 切片放在会话之外：读写音频是秒级 IO，不占数据库连接
    segments_with_audio = _slice_segment_audio(demo_id, path, segments)

    old_files = []
    with session_scope() as db:
        for seg in segments_with_audio:
            audio = audio_repo.create(
                db,
                uploader_id=uploader_id,
                file_path=seg["audio_path"],
                original_name=f"{title} 第 {seg['seq']} 段.wav",
                file_size=seg["file_size"],
                duration_sec=seg["duration"],
                access=audio_service.ACCESS_PUBLIC,
            )
            seg["audio_id"] = audio.id

        # 重新解析：旧分段音频行随新分段在同一事务里删除，文件等提交后再删
        old_files = [
            audio
            for old in library_repo.list_segments(db, demo_id)
            if old.audio_id and (audio := audio_repo.get_by_id(db, old.audio_id))
        ]
        library_repo.replace_segments(db, demo_id, segments_with_audio)
        audio_repo.delete_ids(db, [a.id for a in old_files])
        if duration is not None:
            library_repo.update_audio_duration(db, demo_id, duration)

    for old in old_files:
        storage.remove(old.file_path)

    # --- 终态 ---
    #
    # 处理被 MAX_AUDIO_SEC 截断时把话说清楚，而不是让「只有前 3 分钟的分段」
    # 这件事藏在库里。message 会原样显示在前端的处理中弹窗与 toast 上。
    note = f" · {TRUNCATE_NOTE}" if duration and duration > vocal_service.MAX_AUDIO_SEC else ""
    task_repo.update(
        demo_id,
        status=STATUS_PARSED,
        progress=100,
        stage=STAGE_SAVE,
        message=f"解析完成，共 {len(segments)} 段{note}",
    )
```

同时在 `_parse` 顶部「--- 取路径（短会话）---」那段里，把 `with session_scope() as db:` 的内容改成：

```python
    with session_scope() as db:
        demo, path = _require_demo(db, demo_id)
        uploader_id = demo.audio.uploader_id if demo.audio else None
        title = demo.title
```

- [ ] **Step 4: 让 `replace_segments` 写入 `audio_id`**

在 `app/repositories/library_repo.py` 的 `Segment(...)` 构造里加一行：

```python
            audio_id=s.get("audio_id"),
```

并在函数 docstring 的「参数是纯 dict」段落后补一句：

```
    dict 里的 audio_id 由解析管线在登记 audio_files 后填入；Excel 路径没有，
    s.get("audio_id") 得到 None。
```

- [ ] **Step 5: 验证切分函数（不跑 Demucs）**

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
from app.services.parse_service import _slice_segment_audio

path = Path("uploads/demos/muguaying_yuanmenwai.wav")
segs = [
    {"seq": 1, "title": "第 1 段", "duration": 1.0, "start": 0.0, "end": 1.0},
    {"seq": 2, "title": "第 2 段", "duration": 0.5, "start": 1.0, "end": 1.5},
]
out = _slice_segment_audio(999999, path, segs)
assert len(out) == 2 and all(o["audio_path"].startswith("segments/999999/") for o in out)
assert all(o["file_size"] > 0 for o in out)
print([(o["seq"], o["duration"], o["file_size"]) for o in out])
PY
```

Expected: 打印两段的 `(seq, duration, file_size)`，两个 `file_size` 均大于 0。

- [ ] **Step 6: 清理验证产物**

```bash
rm -rf uploads/segments/999999 uploads/segments/_smoke
```

Expected: 命令成功（目录不存在也不报错需加 `rm -rf` 已满足）。

---

### Task 4: B2 教师轨优先取分段音频

**Files:**
- Modify: `app/repositories/audio_repo.py:50-65`（`get_segment_teacher_audio`）
- Test: `python -c` + Task 7 全链路

**Interfaces:**
- Consumes: `Segment.audio_id`。
- Produces: `get_segment_teacher_audio(db, segment_id)` 语义不变，优先返回分段切片。

- [ ] **Step 1: 改写 `get_segment_teacher_audio`**

```python
def get_segment_teacher_audio(db: Session, segment_id: int) -> AudioFile | None:
    """B2 模式二的教师轨：优先用该分段自己的音频，其次回退到整首示范音频。

    segments.audio_id 由 Demucs 解析产出；Excel 路径与旧数据为 NULL，
    继续走 segments → teacher_demos → audio_files 的老路。
    两者都没有返回 None，调用方统一按 404 处理。
    """
    segment = db.get(Segment, segment_id)
    if segment is None:
        return None
    if segment.audio_id is not None:
        audio = db.get(AudioFile, segment.audio_id)
        if audio is not None:
            return audio

    stmt = (
        select(AudioFile)
        .join(TeacherDemo, TeacherDemo.audio_id == AudioFile.id)
        .join(Segment, Segment.demo_id == TeacherDemo.id)
        .where(Segment.id == segment_id)
    )
    return db.scalar(stmt)
```

- [ ] **Step 2: 验证回退与优先两条路径**

```bash
.venv/bin/python - <<'PY'
from app.db import session_scope
from app.repositories import audio_repo

with session_scope() as db:
    seg = audio_repo.get_segment(db, 1)
    print("segment 1 audio_id =", None if seg is None else seg.audio_id)
    teacher = audio_repo.get_segment_teacher_audio(db, 1)
    print("teacher audio =", None if teacher is None else teacher.id)
PY
```

Expected: 不抛异常；有 `audio_id` 时分段音频 id 被返回，否则回退到整首音频 id；两者都没有时打印 `None`。

---

### Task 5: C2 返回分段音频 URL

**Files:**
- Modify: `app/schemas/demo.py:32-49`（`DemoSegmentOut`）
- Modify: `app/api/demos_segments_annotations.py:1-40`
- Test: Task 7 全链路

**Interfaces:**
- Consumes: `Segment.audio_id`、`url_for("api.audio_download")`。
- Produces: C2 响应每项含 `url: str | null`。

- [ ] **Step 1: 给 `DemoSegmentOut` 增加 `url`**

```python
    id: int
    seq: int | None = None
    title: str | None = None
    duration: float | None = None
    # 该段音频的播放地址（B5）。没有独立音频时为 None，前端回退到整首。
    url: str | None = None
```

- [ ] **Step 2: 在 C2 视图组装 `url`**

把 `app/api/demos_segments_annotations.py` 顶部导入改成：

```python
from flask import request, url_for
```

把 `demos_segments` 的返回改成：

```python
    rows = library_service.demo_segments(get_db(), demo_id)
    return ok([
        DemoSegmentOut.model_validate({
            "id": r.id,
            "seq": r.seq,
            "title": r.title,
            "duration": r.duration,
            "url": url_for("api.audio_download", file_id=r.audio_id) if r.audio_id else None,
        }).model_dump(mode="json")
        for r in rows
    ])
```

- [ ] **Step 3: 静态检查**

```bash
grep -n "url_for\|url" app/api/demos_segments_annotations.py | head
.venv/bin/python -c "import app.api.demos_segments_annotations; print('import ok')"
```

Expected: 能看到 `url_for("api.audio_download"...)`，并打印 `import ok`。

---

### Task 6: 跟唱页按段播放示范

**Files:**
- Modify: `sing_along.html:1160-1162`（`selectSegment`）
- Modify: `sing_along.html:1953-1998`（`playDemo`）
- Test: 静态检查 + 浏览器手测（可选）

**Interfaces:**
- Consumes: C2 的 `segments[idx].url`。
- Produces: 无接口变化。

- [ ] **Step 1: 切段时停止旧段播放**

把 `selectSegment` 开头两行改成：

```javascript
  // 播放的是选中段的切片，切段后旧段的声音必须停下；录音同样要丢弃。
  if (isRecording) { discardRecording = true; stopAll(); }
  else if (isPlaying) stopAll();
```

- [ ] **Step 2: 改写 `playDemo` 的取址逻辑**

把函数开头到 `addLog("▶️ 播放示范音频…", "info");` 之间改成：

```javascript
async function playDemo() {
  if (currentDemoId === null) { alert("请先选择曲目"); return; }
  if (isRecording) { discardRecording = true; stopAll(); }

  // 连点两次时两次调用都在 await 里，后者会设 src 打断前者的 play()。
  // 用令牌让先到的那次在 await 之后直接放弃，只剩最后一次真正落地。
  const token = ++playToken;
  const seg = currentSegmentIdx >= 0 ? segments[currentSegmentIdx] : null;
  const isSegmentPlayback = !!(seg && seg.url);

  let url;
  if (isSegmentPlayback) {
    url = seg.url;
  } else {
    try {
      url = await resolveAudioUrl(currentDemoId);
    } catch (e) {
      if (token === playToken) addLog(`获取示范音频失败：${e.message}`, "error");
      return;
    }
    if (token !== playToken) return;
  }
  if (!url) {
    addLog("该曲目没有示范音频", "warn");
    document.getElementById("btnPlayDemo").disabled = true;
    return;
  }

  audioError = false;
  demoAudio.src = url;
  demoAudio.currentTime = 0;

  isPlaying = true;
  document.getElementById("btnPlayDemo").style.display = "none";
  document.getElementById("btnStopDemo").style.display = "inline-flex";
  document.getElementById("btnRecord").disabled = true;
  addLog(isSegmentPlayback ? "▶️ 播放本段示范音频…" : "▶️ 播放整首示范音频…", "info");
```

后面的 `try { await demoAudio.play(); } ...` 保持不变。

- [ ] **Step 3: 静态检查**

```bash
grep -n "isSegmentPlayback\|seg.url" sing_along.html
```

Expected: 能看到 `const isSegmentPlayback = !!(seg && seg.url);` 与 `url = seg.url;`。

- [ ] **Step 4: 可选浏览器手测**

启动后端后访问 `sing_along.html`，选中一个已解析的段，点「播放示范」应只播该段；未选段时播整首。本机 `/browse` 不可用，手测可不做，以 Task 7 的 HTTP 验收为准。

---

### Task 7: Linux 全链路验收脚本与执行

**Files:**
- Create: `scripts/smoke_demo_segment.sh`
- Test: 脚本自身

**Interfaces:**
- Consumes: Task 1–6 的全部改动、`scripts/check_db.py`。
- Produces: 可重复执行的验收脚本，退出码 0=全通过、1=有失败。

- [ ] **Step 1: 写验收脚本**

```bash
#!/usr/bin/env bash
# 戏韵AI — 示范解析 + 分段音频 + 跟唱对比 全链路验收
#
# 用法（项目根目录）：
#     scripts/smoke_demo_segment.sh
#     BASE=http://127.0.0.1:80 scripts/smoke_demo_segment.sh
#
# 前置：
#   1. Flask 已启动：.venv/bin/python app-d.py
#   2. 默认 Celery worker 已起（D1/B2 分析）：
#      .venv/bin/celery -A app.worker:celery_app worker -n default@%h --concurrency=2
#   3. Demucs worker 已起（-Q demucs，解析）：
#      .venv/bin/celery -A app.worker:celery_app worker -Q demucs -n demucs@%h --concurrency=1
#   4. 活库已执行 segments.audio_id 的 ALTER TABLE
#
# ⚠️ 解析单条约 8–15 分钟，脚本默认最多等 25 分钟。
set -u

BASE="${BASE:-http://127.0.0.1:8877}"
PY="${PY:-python3}"
AUDIO_FILE="${AUDIO_FILE:-uploads/demos/muguaying_yuanmenwai.wav}"
PARSE_MAX="${PARSE_MAX:-300}"          # 300 × 5s = 25 分钟
ANALYZE_MAX="${ANALYZE_MAX:-120}"      # 120 × 2s = 4 分钟

TD="$(mktemp -d)"
cleanup() { rm -rf "$TD"; }
trap cleanup EXIT

TEACHER_JAR="$TD/teacher.jar"
STUDENT_JAR="$TD/student.jar"
BODY_FILE="$TD/body.json"
STATUS=""
BODY=""

PASS=0
FAIL=0
red()   { printf '\033[31m%s\033[0m' "$1"; }
green() { printf '\033[32m%s\033[0m' "$1"; }
ok()    { PASS=$((PASS + 1)); printf '  %s %s\n' "$(green ✓)" "$1"; }
bad()   { FAIL=$((FAIL + 1)); printf '  %s %s —— %s\n' "$(red ✗)" "$1" "$2"; }

req() {
  STATUS=$(curl -s -o "$BODY_FILE" -w '%{http_code}' "$@")
  BODY=$(cat "$BODY_FILE")
  if [ "$STATUS" = "000" ]; then
    echo "$(red "无法连接 $BASE") —— 后端没起？" >&2
    exit 1
  fi
}

jget() {
  printf '%s' "$BODY" | "$PY" -c '
import json, sys
try:
    cur = json.load(sys.stdin)
    for k in sys.argv[1].split("."):
        cur = cur[int(k)] if isinstance(cur, list) else cur[k]
except Exception:
    cur = ""
print(cur if cur is not None else "")
' "$1"
}

login() {
  local jar="$1" user="$2"
  req -c "$jar" -b "$jar" -X POST -H 'Content-Type: application/json' \
    -d "{\"username\":\"$user\",\"password\":\"xiyun@2026\"}" "$BASE/api/auth/login"
  [ "$STATUS" = "200" ] || { echo "登录 $user 失败：HTTP $STATUS $BODY" >&2; exit 1; }
}

echo "== 1. 教师登录并上传示范 =="
login "$TEACHER_JAR" teacher01
req -c "$TEACHER_JAR" -b "$TEACHER_JAR" -X POST \
  -F "audio=@$AUDIO_FILE" -F "title=验收-分段音频-$(date +%s)" \
  -F "access=public" "$BASE/api/demo/library/upload"
DEMO_ID=$(jget data.demo_id)
TASK_ID=$(jget data.task_id)
[ -n "$DEMO_ID" ] && ok "上传成功 demo_id=$DEMO_ID task_id=$TASK_ID" \
  || bad "上传失败" "HTTP $STATUS $BODY"

echo "== 2. 轮询解析状态（最多 $((PARSE_MAX * 5)) 秒）=="
for _ in $(seq 1 "$PARSE_MAX"); do
  req -c "$TEACHER_JAR" -b "$TEACHER_JAR" "$BASE/api/demo/library/$DEMO_ID/parse/status"
  ST=$(jget data.status)
  [ "$ST" = "parsed" ] && break
  [ "$ST" = "error" ] && break
  sleep 5
done
[ "$ST" = "parsed" ] && ok "解析完成：$(jget data.message)" \
  || bad "解析未完成" "status=$ST message=$(jget data.message)"

echo "== 3. 校验分段与音频 URL =="
req -c "$TEACHER_JAR" -b "$TEACHER_JAR" "$BASE/api/demos/$DEMO_ID/segments"
SEG_COUNT=$(printf '%s' "$BODY" | "$PY" -c 'import json,sys; print(len(json.load(sys.stdin)["data"]))')
[ "$SEG_COUNT" -gt 0 ] && ok "分段数=$SEG_COUNT" || bad "没有分段" "$BODY"
SEG_ID=$(jget data.0.id)
SEG_URL=$(jget data.0.url)
SEG_DUR=$(jget data.0.duration)
[ -n "$SEG_URL" ] && ok "第 1 段 url=$SEG_URL" || bad "第 1 段没有 url" "$BODY"

echo "== 4. 学生登录并下载分段音频（验证 public 可听）=="
login "$STUDENT_JAR" stu001
SEG_FILE="$TD/seg.wav"
STATUS=$(curl -s -o "$SEG_FILE" -w '%{http_code}' -c "$STUDENT_JAR" -b "$STUDENT_JAR" "$BASE$SEG_URL")
[ "$STATUS" = "200" ] && ok "分段音频可下载" || bad "分段音频下载失败" "HTTP $STATUS"
"$PY" - "$SEG_FILE" "$SEG_DUR" <<'PY'
import sys, librosa
path, expect = sys.argv[1], float(sys.argv[2])
got = librosa.get_duration(path=path)
assert abs(got - expect) < 0.15, f"时长不符：文件 {got:.3f}s，字段 {expect}s"
print(f"  \033[32m✓\033[0m 时长一致：{got:.3f}s")
PY
[ $? -eq 0 ] && PASS=$((PASS + 1)) || bad "分段音频时长不符" "见上"

echo "== 5. 学生上传录音并提交跟唱分析 =="
req -c "$STUDENT_JAR" -b "$STUDENT_JAR" -X POST \
  -F "audio=@$SEG_FILE" "$BASE/api/audio/upload"
AUDIO_ID=$(jget data.file_id)
[ -n "$AUDIO_ID" ] && ok "学生录音上传 file_id=$AUDIO_ID" || bad "学生录音上传失败" "$BODY"

req -c "$STUDENT_JAR" -b "$STUDENT_JAR" -X POST \
  -F "segment_id=$SEG_ID" -F "audio_id=$AUDIO_ID" \
  -F "duration_sec=$SEG_DUR" "$BASE/api/practice/submit"
PRACTICE_TASK=$(jget data.task_id)
[ -n "$PRACTICE_TASK" ] && ok "D1 提交 task_id=$PRACTICE_TASK" || bad "D1 提交失败" "$BODY"

echo "== 6. 轮询分析结果 =="
for _ in $(seq 1 "$ANALYZE_MAX"); do
  req -c "$STUDENT_JAR" -b "$STUDENT_JAR" "$BASE/api/analyze/status/$PRACTICE_TASK"
  AST=$(jget data.status)
  [ "$AST" = "done" ] && break
  [ "$AST" = "failed" ] && break
  sleep 2
done
[ "$AST" = "done" ] && ok "分析完成" || bad "分析未完成" "status=$AST message=$(jget data.message)"

req -c "$STUDENT_JAR" -b "$STUDENT_JAR" "$BASE/api/analyze/result/$PRACTICE_TASK"
OVERALL=$(jget data.overall)
DIM_COUNT=$(printf '%s' "$BODY" | "$PY" -c 'import json,sys; print(len(json.load(sys.stdin)["data"]["dimensions"]))')
[ -n "$OVERALL" ] && ok "综合评分=$OVERALL" || bad "结果缺 overall" "$BODY"
[ "$DIM_COUNT" = "5" ] && ok "五维齐全" || bad "维度数=$DIM_COUNT" "$BODY"

echo
echo "通过 $PASS 项，失败 $FAIL 项"
[ "$FAIL" -eq 0 ] || exit 1
```

- [ ] **Step 2: 赋可执行权限并做语法检查**

```bash
chmod +x scripts/smoke_demo_segment.sh
bash -n scripts/smoke_demo_segment.sh && echo "语法 ok"
```

Expected: 打印 `语法 ok`。

- [ ] **Step 3: 启动后端与两个 worker（三个终端）**

终端 1：

```bash
.venv/bin/python app-d.py
```

终端 2：

```bash
.venv/bin/celery -A app.worker:celery_app worker -n default@%h --loglevel=info --concurrency=2
```

终端 3：

```bash
.venv/bin/celery -A app.worker:celery_app worker -Q demucs -n demucs@%h --loglevel=info --concurrency=1
```

- [ ] **Step 4: 执行验收**

```bash
scripts/smoke_demo_segment.sh
```

Expected: 全部检查为 ✓，末尾 `通过 N 项，失败 0 项`，退出码 0。

- [ ] **Step 5: 记录验收数据**

把以下内容记入汇报：解析实际耗时（轮询次数 × 5s）、分段数、第 1 段时长与文件大小、综合评分与五维分值、worker 日志里的耗时。失败项如实记录，不得改断言掩盖。

---

### Task 8: 文档同步

**Files:**
- Modify: `DOC_ISSUES.md`（在「## 待核实」之前新增第 45 条）
- Modify: `CLAUDE.md`（示范库解析链路、check_db 计数、跟唱页说明）

**Interfaces:**
- 无代码接口。

- [ ] **Step 1: 在 `DOC_ISSUES.md` 新增第 45 条**

```markdown
## 45. `segments` 表新增 `audio_id`，文档未定义分段级音频

《4-数据库设计-V1.1》的 `segments` 表只有 `demo_id/seq/title/lyrics_json/duration`，
没有分段音频列；《5-接口清单》C2 也没有音频地址字段。但跟唱页要「按段示范 +
按段对比」，整首 `teacher_demos.audio_id` 无法表达。

2026-10-20 的口径：

1. `segments` 增加 `audio_id INT REFERENCES audio_files(id)`，Demucs 解析时按
   停顿切出的每段各存一份**原始混音**切片（`uploads/segments/<demo_id>/<uuid>.wav`，
   `access=public`）；
2. C2 `GET /api/demos/<id>/segments` 增加 `url` 字段，无音频时为 `null`；
3. B2 的教师轨优先取 `segments.audio_id`，为空才回退到整首；
4. Excel 逐字数据路径不切音频，仍走整首回退；
5. 重新解析会删除旧分段音频的 `audio_files` 行，并在事务提交后删除旧文件。

这是数据模型与接口契约的扩展，需求文档方如需另定口径，以文档为准再调整。
```

- [ ] **Step 2: 更新 `CLAUDE.md` 的示范库解析链路**

在「示范库解析链路（Demucs）」小节末尾补一条：

```markdown
- **解析会为每段切一份原始混音音频**（2026-10-20 起）：存
  `uploads/segments/<demo_id>/<uuid>.wav`，登记 `audio_files`（`access=public`）
  并写回 `segments.audio_id`；C2 每段多一个 `url`。`sing_along.html` 选中段后
  「播放示范」播该段切片，D1/B2 的教师轨也优先用它（Excel 路径与旧数据回退整首）。
  重新解析会清理旧分段音频。设计见
  `docs/superpowers/specs/2026-10-20-segment-audio-design.md`。
```

同时把 `scripts/check_db.py` 那句「当前 15 表 / 110 列 / 22 外键 / 2 索引」改成
「当前 15 表 / 111 列 / 23 外键 / 2 索引」。

- [ ] **Step 3: 检查文档编码与内容**

```bash
python3 -c "open('DOC_ISSUES.md', encoding='utf-8').read(); open('CLAUDE.md', encoding='utf-8').read(); print('utf-8 ok')"
grep -n "segments.audio_id\|111 列" CLAUDE.md DOC_ISSUES.md
```

Expected: 打印 `utf-8 ok`，并能看到新增的两处关键词。

---

## Self-Review

- **Spec coverage:** 数据模型→Task 1；解析切片→Task 2/3；对比基线→Task 4；C2 url→Task 5；前端→Task 6；Linux 验收→Task 7；文档→Task 8。
- **Placeholder scan:** 无 TBD/TODO；所有代码步骤均给出可执行内容。
- **Type consistency:** `save_generated` 返回 `(path, size)` 在 Task 2/3 一致；`replace_segments` 的 `audio_id` 键在 Task 3 写入、Task 1 的模型列承接；C2 的 `url` 与前端 `seg.url` 一致。
- **已知取舍:** 提交失败可能留下本轮新写的孤儿文件（spec 第 10 节已登记）；本计划不自动提交 git。

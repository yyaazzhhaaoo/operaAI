# 音频存储分层（`uploads/` + `uploads/demos/`）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `app/common/storage.py` 能表达「学生录音平铺在 `uploads/`、示范音频放 `uploads/demos/`」这个产品口径，并把这批脏数据改成可解析的形态——修完 `sing_along.html` 选 demo 16 能真正听到示范音频。

**Architecture:** 只动一个存储原语的契约：`resolve()` 的守卫从「父目录正好是 `uploads/`」放宽为「`uploads/` 必须是祖先目录」，`save()` 加一个可选的 `subdir` 参数。落点由调用方显式给，不从 `access` 推导。三条读取链路（B5 播放、Demucs 解析、分析）都经由 `resolve()`，一处改动同时修好。

**Tech Stack:** Python 3.11 / Flask / SQLAlchemy + psycopg2 / PostgreSQL（Docker `docker_postgres`）。

**Spec:** `docs/superpowers/specs/2026-10-09-upload-storage-subdir-design.md`

## Global Constraints

- **路径穿越防护不能丢**。本次放宽的是「允许多深」，不是「允不允许出界」。`.resolve()` 与祖先判定必须同时在场——写实现时别顺手删掉任何一个。
- **`app/common/storage.py` 只碰文件系统，不碰数据库、不碰请求上下文**（该模块 docstring 的既有约束）。加 `subdir` 参数时不要引入 `flask.request` 或 session。
- **不改 `access` 语义**。`public`/`private` 的可听范围判定（`audio_service.get_playable`）一个字节都不动。
- **表结构真源是 `schema.sql`**，本次只改注释、不改 DDL，因此**不需要动 `app/models/`**，也**不要引入 Alembic**。
- **脚本与后台任务用 `with session_scope() as s:`**（进出都管事务）；**请求内用 `get_db()`**。两者不可互换。
- **无测试框架**：验证方式是临时脚本 + `curl` + `psql` + 浏览器。临时脚本用完即弃，不进仓库（唯一进仓库的脚本是 `scripts/fix_demo_audio_paths.py`）。
- **直提 main，不开分支**。
- 跑脚本一律用 `.venv/bin/python`（PATH 上的 `python3` 是 pyenv 的，不是项目 venv）。

---

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `app/common/storage.py` | 改 | 存储原语：`save()` 落盘位置 / `resolve()` 路径解析与守卫 |
| `app/services/audio_service.py` | 改 | `save_upload` 加 `subdir` 透传 |
| `app/api/demo_library.py` | 改 | 示范库上传的调用点，传 `subdir="demos"` |
| `app/api/audio_analyze.py` | **不改** | B1 学生录音上传，走默认（根目录） |
| `schema.sql` | 改注释 | 把 `file_path` 的列约定写明确 |
| `app/services/analyze_service.py` | 改 | 错误消息不再回显 `file_path` |
| `scripts/fix_demo_audio_paths.py` | 新建 | 数据修正脚本，幂等可重放 |
| `DOC_ISSUES.md` | 改 | 第 40 条补上「代码已修」的状态 |

---

## Task 1: `storage` 原语——`resolve()` 放宽守卫、`save()` 加 `subdir`

**Files:**
- Modify: `app/common/storage.py`

**Interfaces:**
- Consumes: 无（本任务是最底层）
- Produces:
  - `storage.resolve(stored_name: str) -> Path`（签名不变，语义放宽）
  - `storage.save(file: FileStorage, *, subdir: str | None = None) -> tuple[str, int]`（返回值改为 `relative_to(upload_dir).as_posix()`，形如 `"demos/<hex>.wav"` 或 `"<hex>.wav"`）

- [ ] **Step 1: 先写验证脚本，确认现在的失败方式**

创建 `/tmp/check_storage.py`：

```python
# -*- coding: utf-8 -*-
"""临时验证脚本：storage.resolve 的守卫与 save 的落点。用完即弃。"""
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
ROOT = Path("/Users/meiyazhao/Documents/lianshu/operaAI")
sys.path.insert(0, str(ROOT))

from werkzeug.datastructures import FileStorage          # noqa: E402

from app.common import storage                           # noqa: E402
from app.common.errors import BusinessError              # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"{'OK  ' if ok else 'FAIL'} {label:38} got={got!r:28} want={want!r}")
    if not ok:
        fails.append(label)


# ---- resolve 守卫 ----
# 软链样本：uploads/ 下放一个指向 /tmp 的软链，用来验「软链逃逸仍被挡」
link = ROOT / "uploads" / "__esc_test"
link.unlink(missing_ok=True)
link.symlink_to("/tmp")

for name, want in [
    ("abc.wav",           "pass"),
    ("demos/abc.wav",     "pass"),
    ("../etc/passwd",     "400"),
    ("/etc/passwd",       "400"),
    ("",                  "400"),
    (".",                 "400"),
    ("__esc_test/x.wav",  "400"),
]:
    try:
        storage.resolve(name)
        got = "pass"
    except BusinessError:
        got = "400"
    check(f"resolve({name!r})", got, want)

link.unlink(missing_ok=True)

# ---- save 落点 ----
def mkfile():
    return FileStorage(stream=io.BytesIO(b"RIFF0000"), filename="t.wav")


rel, size = storage.save(mkfile())
check("save() 返回相对路径、无目录", "/" in rel, False)
check("save() 落在 uploads/ 根", (ROOT / "uploads" / rel).is_file(), True)

rel2, _ = storage.save(mkfile(), subdir="demos")
check("save(subdir='demos') 前缀", rel2.startswith("demos/"), True)
check("save(subdir='demos') 落在 demos/", (ROOT / "uploads" / rel2).is_file(), True)

try:
    storage.save(mkfile(), subdir="../evil")
    check("save(subdir='../evil') 被拒", "pass", "400")
except BusinessError:
    check("save(subdir='../evil') 被拒", "400", "400")

for r in (rel, rel2):
    (ROOT / "uploads" / r).unlink(missing_ok=True)

print("\n" + ("ALL PASS" if not fails else f"失败 {len(fails)} 项: {fails}"))
sys.exit(0 if not fails else 1)
```

- [ ] **Step 2: 跑它，确认它现在就是失败的**

Run: `.venv/bin/python /tmp/check_storage.py`
Expected: `FAIL`。至少这三项不符：`resolve('demos/abc.wav')` 期望 pass 但得到 400；`save(subdir='demos')` 报 `TypeError: save() got an unexpected keyword argument 'subdir'`（脚本会当场崩在这里——这本身就是失败的证据）；`save(subdir='../evil')` 同理。

> 脚本在 `save()` 处抛异常就说明 Task 1 还没做，符合预期。先跑一遍把「改之前是什么样」记下来。

- [ ] **Step 3: 改 `resolve()`**

把 `app/common/storage.py` 的 `resolve` 整个函数替换为：

```python
def resolve(stored_name: str) -> Path:
    """存储路径 → 磁盘绝对路径，并确保没有跑出 uploads/ 之外。

    stored_name 是 audio_files.file_path 的值：**相对 uploads/ 的路径**，
    可以带一层目录（如 demos/<uuid>.wav），但不含 uploads/ 前缀。

    file_path 虽然由 save() 生成、理论上干净，但它是从数据库读回来的——
    手工改库或历史脏数据都可能让 ../ 混进来，所以在取用处再挡一道。

    守卫判「root 必须是 path 的祖先」而不是「父目录正好是 root」：后者会把
    uploads/demos/ 这类子目录一并拒掉（DOC_ISSUES 第 40 条）。放宽的是深度，
    不是边界——下面的 .resolve() 会跟随软链，祖先判定因此同时挡住
    ../ 逃逸与指向 root 之外的软链。**两者缺一不可，别删任何一个。**
    """
    root = settings.upload_dir.resolve()
    path = (root / stored_name).resolve()
    if root not in path.parents:
        raise BusinessError(400, "非法的音频文件名")
    return path
```

- [ ] **Step 4: 改 `save()`**

把 `app/common/storage.py` 的 `save` 整个函数替换为：

```python
def save(file: FileStorage, *, subdir: str | None = None) -> tuple[str, int]:
    """把上传流落盘，返回 (存储路径, 字节数)。

    存储名用 uuid 重新生成，不沿用客户端文件名——客户端文件名既可能重名，
    也可能带 ../ 或控制字符。原始名另存在 audio_files.original_name 里备查。

    subdir 是相对 uploads/ 的子目录：示范库音频传 "demos"，学生录音不传。
    **由调用方显式给，不从 access 之类的字段推导**——access 在接口层是客户端
    可控的，拿它选目录会在「教师上传示范但没显式传 public」时把示范音频落进
    学生录音目录（DOC_ISSUES 第 40 条）。

    返回值即写进 audio_files.file_path 的值，形如 "demos/<hex>.wav" 或
    "<hex>.wav"——相对 uploads/、不带 uploads/ 前缀，与列约定一致（见 schema.sql）。
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise BusinessError(400, f"不支持的音频格式：{ext or '未知'}")

    root = settings.upload_dir.resolve()
    dest_dir = (root / subdir).resolve() if subdir else root
    # subdir 目前只由本仓库的代码常量传入，理论上干净；但判定与 resolve() 同源，
    # 一并挡住，免得将来有人把它接到请求参数上
    if dest_dir != root and root not in dest_dir.parents:
        raise BusinessError(400, "非法的存储子目录")

    stored_name = f"{uuid.uuid4().hex}{ext}"
    dest = dest_dir / stored_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    file.save(dest)

    size = dest.stat().st_size
    if size == 0:
        # 空文件多半是前端录音没拿到数据就提交了。留着会在分析阶段
        # 变成一个更难懂的错误，这里直接拒掉并清理。
        dest.unlink(missing_ok=True)
        raise BusinessError(400, "上传的文件为空")

    return dest.relative_to(root).as_posix(), size
```

- [ ] **Step 5: 同步模块 docstring 里那句「只存文件名」**

`app/common/storage.py` 开头的 docstring 现在是：

```
**库里 audio_files.file_path 只存文件名，不存绝对路径**：这样数据库与部署
```

改成：

```
**库里 audio_files.file_path 只存相对 uploads/ 的路径，不存绝对路径**：
可以带一层目录（示范音频是 demos/<uuid>.wav）。这样数据库与部署
```

（后半句「环境解耦」等原文保留不动。）

- [ ] **Step 6: 跑验证脚本，确认全绿**

Run: `.venv/bin/python /tmp/check_storage.py`
Expected: 每一行都是 `OK`，末行 `ALL PASS`，退出码 0。

**如果 `resolve('__esc_test/x.wav')` 这项没被拒，说明软链逃逸的防护坏了——停下来查，不要往下走。**

- [ ] **Step 7: 确认没留下垃圾文件**

Run: `git status --short && ls uploads/ | grep -c '^__esc_test$' || true`
Expected: 只有 `M app/common/storage.py`；`__esc_test` 计数为 0（脚本自己会清）。**若 `uploads/` 下有脚本遗留的 uuid wav，手动删掉**——脚本已 try/finally 之外清理，但异常路径下可能漏。

- [ ] **Step 8: 提交**

```bash
git add app/common/storage.py
git commit -m "feat: storage 支持 uploads/ 下的子目录

resolve() 守卫由 path.parent != root 放宽为 root in path.parents：
允许子目录，但仍挡住 ../ 逃逸、绝对路径与指向 root 之外的软链。
save() 加 subdir 参数，返回值改为相对 uploads/ 的路径（demos/<hex>.wav），
落点由调用方显式给、不从 access 推导（见 DOC_ISSUES 第 40 条）。

DOC_ISSUES 第 40 条。"
```

---

## Task 2: 把 `subdir` 接到示范库上传

**Files:**
- Modify: `app/services/audio_service.py:25-65`
- Modify: `app/api/demo_library.py:41`

**Interfaces:**
- Consumes: `storage.save(file, *, subdir=None)`（Task 1）
- Produces: `audio_service.save_upload(..., subdir: str | None = None, ...)` —— 其余参数与返回值不变

- [ ] **Step 1: `save_upload` 加参数并透传**

`app/services/audio_service.py` 的签名（第 25-33 行）改为：

```python
def save_upload(
    db: Session,
    *,
    uploader_id: int,
    is_teacher: bool,
    access: str,
    file: FileStorage,
    subdir: str | None = None,
    commit: bool = True,
) -> AudioFile:
```

docstring 在 `access 默认 private（学生录音）。…` 那段之后、`commit=False` 那段之前插入：

```
    subdir 是相对 uploads/ 的落盘子目录：示范库音频传 "demos"，学生录音不传。
    显式传入、不从 access 推导——access 在接口层是客户端可控的
    （request.form.get("access", "private")），拿它选目录会在「教师上传示范
    但没传 public」时把示范音频落进学生录音目录（见 DOC_ISSUES 第 40 条）。
```

第 53 行改为：

```python
    stored_name, size = storage.save(file, subdir=subdir)
```

- [ ] **Step 2: 示范库调用点传 `"demos"`**

`app/api/demo_library.py` 第 41 行起的调用块，在 `access=request.form.get("access", "private"),` 之后加一行：

```python
        # 示范音频落 uploads/demos/，与学生录音（uploads/ 根）分开。
        # 显式给而不用 access 推导，理由见 audio_service.save_upload 的 docstring。
        subdir="demos",
```

改完这一段应该是：

```python
    audio = audio_service.save_upload(
        db,
        uploader_id=current_user_id(),
        is_teacher=session.get("role") == "teacher",
        access=request.form.get("access", "private"),
        # 示范音频落 uploads/demos/，与学生录音（uploads/ 根）分开。
        # 显式给而不用 access 推导，理由见 audio_service.save_upload 的 docstring。
        subdir="demos",
        file=file,
        commit=False,
    )
```

**`app/api/audio_analyze.py:43` 的 B1 调用点不要动**——学生录音走默认值（根目录）。

- [ ] **Step 3: 写临时脚本，端到端验一次 `save_upload` 的落点**

创建 `/tmp/check_save_upload.py`：

```python
# -*- coding: utf-8 -*-
"""临时验证：save_upload 的 subdir 真的落到了 demos/。用完即弃，会自己清理。"""
import io
import sys
from pathlib import Path

ROOT = Path("/Users/meiyazhao/Documents/lianshu/operaAI")
sys.path.insert(0, str(ROOT))

from werkzeug.datastructures import FileStorage          # noqa: E402

from app.config import settings                          # noqa: E402
from app.db import session_scope                         # noqa: E402
from app.models.audio import AudioFile                   # noqa: E402
from app.services import audio_service                   # noqa: E402

TEACHER_ID = int(sys.argv[1])
created = []

with session_scope() as s:
    for subdir, want_prefix in (("demos", "demos/"), (None, "")):
        fs = FileStorage(stream=io.BytesIO(b"RIFF0000"), filename="t.wav")
        audio = audio_service.save_upload(
            s, uploader_id=TEACHER_ID, is_teacher=True,
            access="public", file=fs, subdir=subdir,
        )
        created.append(audio.id)
        p = settings.upload_dir / audio.file_path
        print(f"subdir={subdir!r:8} file_path={audio.file_path!r:44} "
              f"前缀{'对' if audio.file_path.startswith(want_prefix) and '/' not in audio.file_path[len(want_prefix):] else '错'} "
              f"文件{'在' if p.is_file() else '不在'}")
        assert audio.file_path.startswith(want_prefix) or subdir is None
        assert p.is_file(), f"文件不在：{p}"
        if subdir == "demos":
            assert audio.file_path.startswith("demos/"), audio.file_path

# 清理：删行 + 删文件
with session_scope() as s:
    for aid in created:
        a = s.get(AudioFile, aid)
        if a is None:
            continue
        (settings.upload_dir / a.file_path).unlink(missing_ok=True)
        s.delete(a)

print("\nOK：两条都落在预期位置，清理完成")
```

Run（`TEACHER_ID` 取库里任一教师 id）：

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -At -c "SELECT id FROM users WHERE role='teacher' ORDER BY id LIMIT 1;"
.venv/bin/python /tmp/check_save_upload.py <上一步查到的 id>
```

Expected: 两行都是「前缀对 文件在」，末行 `OK：两条都落在预期位置，清理完成`。

- [ ] **Step 4: 确认清理干净**

Run: `git status --short && ls uploads/demos/`
Expected: 只列出 `M app/api/demo_library.py`、`M app/services/audio_service.py`；`uploads/demos/` 下**仍然只有** `muguaying_yuanmenwai.wav`（脚本建的临时文件已删）。

- [ ] **Step 5: 提交**

```bash
git add app/services/audio_service.py app/api/demo_library.py
git commit -m "feat: 示范库上传落 uploads/demos/

save_upload 加 subdir 透传；demo_library 的调用点传 subdir=\"demos\"。
落点由调用方显式给、不从 access 推导（access 在接口层客户端可控）。
B1 学生录音上传不动，仍走 uploads/ 根。

DOC_ISSUES 第 40 条。"
```

---

## Task 3: 把列约定写明确，并堵掉一处路径回显

> 本任务的两项都小且独立。**第二项（错误消息）是本轮的可选项**，若评审时要砍，删掉 Step 3 即可，不影响其余任务。

**Files:**
- Modify: `schema.sql:48`
- Modify: `app/services/analyze_service.py:180`

**Interfaces:**
- Consumes: 无
- Produces: 无（纯注释与文案）

- [ ] **Step 1: 改 `schema.sql` 的列注释**

第 48 行现在：

```sql
  file_path VARCHAR(255) NOT NULL,       -- uploads/ 相对路径
```

改成：

```sql
  file_path VARCHAR(255) NOT NULL,       -- 相对 uploads/ 的路径，可含一层目录（如 demos/<uuid>.wav），不带 uploads/ 前缀
```

**只改这一句注释，DDL 一个字节都不动。**

- [ ] **Step 2: 确认模型不用跟着改**

Run: `.venv/bin/python scripts/check_db.py`
Expected: 输出里**没有** `audio_files` 相关的差异。该脚本本就有既有漂移记录在案（见 `DOC_ISSUES`），别把既有差异当成本次改坏的。

- [ ] **Step 3: `analyze_service` 的错误消息不再回显 `file_path`**

`app/services/analyze_service.py:180` 现在：

```python
        raise BusinessError(404, f"音频文件已丢失：{audio.file_path}")
```

改成：

```python
        # 不回显 file_path：它可能带 demos/ 这类服务端目录结构，而这条消息
        # 是直接给前端看的（见 app/common/errors.py 的 handler）
        raise BusinessError(404, f"音频文件已丢失（audio id={audio.id}）")
```

- [ ] **Step 4: 提交**

```bash
git add schema.sql app/services/analyze_service.py
git commit -m "docs: 写明确 file_path 的列约定，错误消息不再回显路径

schema.sql 那句「uploads/ 相对路径」两种读法都成立，第 40 条那批脏值
正是这么进来的。analyze_service 的 404 文案会把 demos/ 这层目录结构
透给前端，改为只报 audio id。"
```

---

## Task 4: 数据修正脚本并执行

**Files:**
- Create: `scripts/fix_demo_audio_paths.py`

**Interfaces:**
- Consumes: `storage.resolve()`（Task 1）
- Produces: 无（一次性数据修正，幂等）

- [ ] **Step 1: 写脚本**

创建 `scripts/fix_demo_audio_paths.py`：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把示范曲目关联的 audio_files.file_path 规范成 demos/<文件名>。

背景（DOC_ISSUES 第 40 条）：示范音频该放 uploads/demos/，学生录音平铺在
uploads/。库里那批示范音频的 file_path 是按「相对项目根」手工插的
（uploads/demos/x.wav），storage.resolve() 解不出来，B5 播放、Demucs 解析、
分析三条链路全断。storage 的守卫修好后，还要把值改成「相对 uploads/」的形态。

用法（在项目根目录执行）：
    .venv/bin/python scripts/fix_demo_audio_paths.py --dry-run
    .venv/bin/python scripts/fix_demo_audio_paths.py

规则是「teacher_demos.audio_id 关联的每一行都应在 demos/ 下」，所以原本是
裸名的（demo 15 那条）也会被归到 demos/——即便它的文件并不存在。
幂等：已经是目标形态的行跳过，可重复执行。
"""

import argparse
import sys
from pathlib import Path

# scripts/ 不是包，直接跑时 sys.path[0] 是 scripts/，import 不到 app/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select                                    # noqa: E402

from app.common import storage                                   # noqa: E402
from app.common.errors import BusinessError                      # noqa: E402
from app.db import session_scope                                 # noqa: E402
from app.models.audio import AudioFile                           # noqa: E402
from app.models.demo import TeacherDemo                          # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写库")
    args = ap.parse_args()

    changed = 0
    with session_scope() as s:
        rows = s.execute(
            select(AudioFile, TeacherDemo.id)
            .join(TeacherDemo, TeacherDemo.audio_id == AudioFile.id)
            .order_by(AudioFile.id)
        ).all()

        if not rows:
            print("没有 teacher_demos 关联的音频，什么都不用做。")
            return 0

        for audio, demo_id in rows:
            target = f"demos/{Path(audio.file_path).name}"
            if audio.file_path == target:
                print(f"跳过   audio {audio.id:3} 已是 {target}")
                continue

            # 改完解不解得出来、文件在不在，当场说清楚——
            # 不然下一个人会问「改完了怎么还是不出声」
            try:
                path = storage.resolve(target)
                detail = f"文件在（{path}）" if path.is_file() else f"文件不在（{path}）"
            except BusinessError as e:
                detail = f"解析失败：{e.message}"

            print(f"改     audio {audio.id:3}  demo {demo_id:3}  "
                  f"{audio.file_path}  ->  {target}   {detail}")
            if not args.dry_run:
                audio.file_path = target
            changed += 1

    verb = "将改" if args.dry_run else "已改"
    print(f"\n{verb} {changed} 行。")
    if args.dry_run:
        print("（--dry-run，没有写库）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 先 dry-run 看清楚要改什么**

Run: `.venv/bin/python scripts/fix_demo_audio_paths.py --dry-run`
Expected: 5 行「改」，分别是 audio 74/75/76/77/78，形如：

```
改     audio  74  demo  15  090e52c9fb8642ab95d3c7e431e0e2b5.wav  ->  demos/090e52c9fb8642ab95d3c7e431e0e2b5.wav   文件不在（...）
改     audio  75  demo  16  uploads/demos/muguaying_yuanmenwai.wav  ->  demos/muguaying_yuanmenwai.wav   文件在（...）
...
```

**audio 75 那行必须是「文件在」**——它是本轮唯一能真正出声的一条。若显示「文件不在」，停下来查，别往下走。
末行 `将改 5 行。`

- [ ] **Step 3: 真跑**

Run: `.venv/bin/python scripts/fix_demo_audio_paths.py`
Expected: 同样的 5 行，末行 `已改 5 行。`

- [ ] **Step 4: 再跑一次，确认幂等**

Run: `.venv/bin/python scripts/fix_demo_audio_paths.py`
Expected: 5 行全变成「跳过」，末行 `已改 0 行。`

- [ ] **Step 5: 用 psql 复核**

Run:

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -At -F'|' -c "
SELECT a.id, a.file_path FROM teacher_demos t JOIN audio_files a ON a.id = t.audio_id ORDER BY t.id;"
```

Expected: 5 行的 `file_path` 全部是 `demos/<文件名>` 形态，**没有一个带 `uploads/` 前缀**。

- [ ] **Step 6: 提交**

```bash
git add scripts/fix_demo_audio_paths.py
git commit -m "feat: 加示范音频路径修正脚本并执行

teacher_demos.audio_id 关联的 5 行 file_path 由 uploads/demos/… 与裸名
统一成 demos/…。幂等可重放，换机器重建库后能再跑一遍。

DOC_ISSUES 第 40 条。"
```

---

## Task 5: 端到端验证与状态收尾

**Files:**
- Modify: `DOC_ISSUES.md`（第 40 条）

**Interfaces:**
- Consumes: Task 1–4 的全部产物
- Produces: 无

- [ ] **Step 1: B5 逐条实测**

先拿 Cookie（后端跑在 8877，或经 nginx 的 80；下面用 8877）：

```bash
rm -f /tmp/sa_cookie.txt
curl -s -c /tmp/sa_cookie.txt -X POST http://127.0.0.1:8877/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"stu001","password":"xiyun@2026"}' -o /dev/null -w "login=%{http_code}\n"

for id in 74 75 76 77 78; do
  printf "audio %s -> " "$id"
  curl -s -b /tmp/sa_cookie.txt -o /tmp/audio_$id.bin -w "%{http_code}\n" "http://127.0.0.1:8877/api/audio/$id"
done
```

Expected（这是本轮的核心验收）：

| id | 期望 | 说明 |
|---|---|---|
| 75 | **200** | 首次真的能取到示范音频 |
| 74 / 76 / 77 / 78 | 404 | 路径已对，文件本身仍缺失 |

再验 75 拿到的是真音频而非错误页：

```bash
file /tmp/audio_75.bin && ls -l /tmp/audio_75.bin
```

Expected: `RIFF (little-endian) data, WAVE audio`，大小约 19.7MB。

- [ ] **Step 2: 浏览器实测（本轮第一次真的能听到声音）**

用 `/browse`，以 `stu001` / `xiyun@2026` 登录 `http://127.0.0.1/sing_along.html`：

1. 选 demo 16《穆桂英挂帅》→ 点「▶️ 播放示范」
2. **日志里不应再出现「示范音频加载失败：后端未能提供该音频」**
3. 进度条随时间推进，`timeCurrent` / `timeTotal` 显示真实秒数（`timeTotal` 应约 19.7s 上下，不是 0.00s）
4. 点「⏹️ 停止」→ 进度条归零、按钮复位
5. 选 demo 17 → 点播放 → **仍走失败降级**（日志出现失败提示、按钮复位），因为它的文件缺失

> 第 5 条是刻意的：**改完只有 demo 16 一首能出声**。演示口径里要说清，别被当成随机偶发。

- [ ] **Step 3: 回归 B1 学生录音**

浏览器里用 `stu001` 在 `pitch_comparison.html` 上传一段音频（或直接 curl B1）：

```bash
curl -s -b /tmp/sa_cookie.txt -X POST http://127.0.0.1:8877/api/audio/upload \
  -F "audio=@/tmp/audio_75.bin" | python3 -m json.tool
```

Expected: 返回统一信封，`data.url` 形如 `/api/audio/<新 id>`。然后：

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -At -F'|' -c "
SELECT id, file_path, access FROM audio_files ORDER BY id DESC LIMIT 1;"
```

Expected: `file_path` 是**裸名**（没有 `demos/` 前缀），`access` 为 `private`——学生录音仍平铺在 `uploads/` 根。

再取一次确认可播放：

```bash
curl -s -b /tmp/sa_cookie.txt -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8877/api/audio/<上一步的新 id>"
```

Expected: `200`（该学生是上传者本人，private 也应可听）。

- [ ] **Step 4: 结构一致性闸门**

Run: `.venv/bin/python scripts/check_db.py`
Expected: 与 Task 3 Step 2 的结果一致，**没有新增差异**。

- [ ] **Step 5: 复查没有越界改动**

```bash
git status --short
git log --oneline -5
git diff --stat HEAD~4
```

Expected: 改动只落在 `app/common/storage.py`、`app/services/audio_service.py`、`app/api/demo_library.py`、`app/services/analyze_service.py`、`schema.sql`、`scripts/fix_demo_audio_paths.py`、`DOC_ISSUES.md`、`docs/`。**不要出现 `app/models/`、`app-d.py`、`requirements.txt`、其它页面 HTML 的改动。**

- [ ] **Step 6: 更新 `DOC_ISSUES.md` 第 40 条**

在第 40 条末尾（`---` 之前）追加一节：

```markdown
### 40.6 修复进展（2026-10-09）

代码侧与数据侧已修，见 `docs/superpowers/specs/2026-10-09-upload-storage-subdir-design.md`
与 `docs/superpowers/plans/2026-10-09-upload-storage-subdir.md`：

- `storage.resolve()` 守卫由 `path.parent != root` 放宽为 `root in path.parents`
  （允许子目录，`..` 与软链逃逸仍挡）；`storage.save()` 加 `subdir` 参数。
- `save_upload` 透传 `subdir`；示范库上传传 `"demos"`，B1 学生录音走默认。
- `schema.sql` 的列注释写明确；`scripts/fix_demo_audio_paths.py` 把 5 行
  `file_path` 统一成 `demos/<文件名>`。
- **实测结果**：audio 75（demo 16）B5 返回 **200**，跟唱页能真正播出声音；
  74/76/77/78 仍 404——**它们缺的是文件本身，与本次修复无关**（见 40.2 ②）。

**仍未解决**：76/77/78 的音频源文件不在仓库里，补文件需要素材。
在那之前，「播放示范」只有 demo 16 一首有效，其余仍走前端失败降级。
```

- [ ] **Step 7: 提交**

```bash
git add DOC_ISSUES.md
git commit -m "docs: DOC_ISSUES 第 40 条补修复进展——代码与数据已修，B5 对 demo 16 返回 200

resolve() 放宽守卫 + save() 加 subdir + 5 行数据统一成 demos/…。
74/76/77/78 仍 404 是因为缺文件本身，与本次修复无关。"
```

---

## Self-Review

**Spec 覆盖**（逐节对回 `docs/superpowers/specs/2026-10-09-upload-storage-subdir-design.md`）：

| spec 节 | 落在哪个任务 |
|---|---|
| §3.1 `resolve()` 祖先判定 | Task 1 Step 3、Step 6 |
| §3.2 `save()` 加 `subdir` | Task 1 Step 4、Step 6 |
| §3.3 `save_upload` 透传 | Task 2 Step 1 |
| §3.4 `schema.sql` 列约定 | Task 3 Step 1 |
| §3.5 `analyze_service` 错误消息 | Task 3 Step 3 |
| §3.6 数据修正脚本 | Task 4 |
| §3.7 `parse_service` 自动受益 | Task 1 Step 3（同一函数，无独立步骤） |
| §5 容错口径的拒绝清单 | Task 1 Step 1（含软链样本）、Step 6 |
| §7 验证方式 1–6 | Task 1 Step 6、Task 2 Step 3、Task 5 Step 1–4 |
| §8 风险 | Task 1 Step 6 的停止条件、Task 5 Step 2 的第 5 条 |

**Placeholder 扫描**：无 TBD / TODO / 「类似上文」；每个改动步骤都给了完整代码或完整命令与预期输出。

**类型与命名一致性**：

- `storage.save(file, *, subdir=None)` 在 Task 1 定义、Task 2 Step 1 调用，参数名一致。
- `save_upload(..., subdir=None, ...)` 在 Task 2 Step 1 定义、Step 2 与 Step 3 的脚本调用，位置参数与关键字一致。
- 返回 `relative_to(root).as_posix()` 在 Task 1 定义，Task 4 脚本按「相对 uploads/」消费，一致。
- `TeacherDemo` / `AudioFile` 的导入路径已在写计划前核对（`app/models/demo.py`、`app/models/audio.py`）。

**风险复述**：Task 1 Step 6 与 Task 5 Step 2 各有一条「停下来查」的停止条件，分别守路径穿越防护与「只有 demo 16 能出声」这个容易被误读为偶发的事实。

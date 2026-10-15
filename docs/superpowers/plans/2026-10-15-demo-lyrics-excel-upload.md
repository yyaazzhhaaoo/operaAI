# 上传示范附带逐字数据（Excel）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 示范库上传接口增加一个选填的 Excel 字段，把教师提供的逐字声学数据（字 / 音高 / 起止时间 / 技巧提示 / 反推时值）写进 `segments.lyrics_json`，并在这种情况下跳过 Demucs 解析。

**Architecture:** 新增一个纯函数模块 `app/services/lyrics_excel.py`（xlsx 字节流 → 段 dict 列表，不碰 DB / flask），由 `app/api/demo_library.py` 的上传路由在落盘之前调用；有 Excel 时走 `library_service.demo_library_add_with_segments`（建 demo + 写 segments + 回填音频时长，一次提交），没有 Excel 时原路不变（投 `demucs` 队列）。前端弹窗加一个选填文件框，`task_id` 为空时不弹「处理中」也不轮询。

**Tech Stack:** Python 3.11 / Flask / SQLAlchemy / PostgreSQL / openpyxl（新增）/ Celery（不改）/ 原生 JS 单文件页面

**设计真源：** `docs/superpowers/specs/2026-10-15-demo-lyrics-excel-upload-design.md`（下称 spec，`§N` 指它的章节）

## Global Constraints

- **全部产物用简体中文**：注释、报错文案、toast、commit message、文档。代码标识符保持英文。
- **注释按 `~/.claude/skills/human-comments/SKILL.md`**：默认不写；只留解释「看不出来的 why / 坑 / 约束」的**一行短碎片**，不复述代码、不叙述改动历史。本计划给出的代码块里已带好该有的注释，**照抄，不要自行加注释**。
- **`requirements.txt` 每行必须钉死 `==`**，新增依赖写进「直接依赖」分组并加中文尾注；**不引入 `pyproject.toml`**。
- **`/api` 前缀只在 `app/api/__init__.py` 的 `url_prefix` 里写一次**，路由一律写相对路径。
- **事务边界在 service 层**：请求内用 `get_db()`（不提交，靠 `teardown_appcontext` 收尾），worker / 脚本用 `session_scope()`。示范上传这条链路**只允许一次 `commit()`**。
- **不改 `schema.sql`**，不动 `app/models/`。`segments.lyrics_json` 本来就装得下。
- **不引入测试框架**。验证一律「临时脚本（放 `/tmp`）+ curl + psql」，脚本不提交进仓库。
- **不迁移、不修改库里已有的 `teacher_demos.id=16`**（手工测试数据，spec §2.2）。
- 后端跑在 **8877**，当前已在运行（PyCharm 调试会话的 reloader 会自动加载 `.py` 改动，**不要杀它**）。改了 `.env` 才需要重启，本计划不动 `.env`。
- psql 走容器：`docker exec -i -e PGPASSWORD=xiyun docker_postgres psql -U xiyun -d xiyun ...`
- 验证资产（都已在仓库根目录）：`穆桂英挂帅_逐字声学数据_4.3.xlsx`、`uploads/demos/muguaying_yuanmenwai.wav`
- 种子账号：`teacher01` / `xiyun@2026`
- 工作目录：`/Users/meiyazhao/Documents/lianshu/operaAI`，venv 是 `.venv`。临时脚本用 `PYTHONPATH=. .venv/bin/python /tmp/xxx.py` 跑（`-I` 会让 `import app...` 失败，别加）。

---

### Task 1: `openpyxl` 依赖 + `lyrics_excel` 解析（段与时间）

**Files:**
- Modify: `requirements.txt`
- Create: `app/services/lyrics_excel.py`
- Verify: `/tmp/verify_lyrics_excel_t1.py`（临时，不入库）

**Interfaces:**
- Consumes: `app.common.errors.BusinessError(code, message)`（已有）
- Produces:
  - `lyrics_excel.parse_segments(blob: bytes) -> list[dict]`，返回 `[{"seq": int, "title": str, "duration": float | None, "lyrics": list[dict]}]`，按 `seq` 升序
  - `lyrics` 每个元素形状 `{"word": str, "midi": int | None, "start": float | None, "end": float | None, "note": str | None, "tip": str | None}`（`note` 在 Task 1 恒为 `None`，Task 2 才填）
  - `start` / `end` 是**段内相对**秒数；`duration` 是该页末字相对 `end`
  - 模块常量：`NOTE_CANDIDATES`（Task 2 用）

- [ ] **Step 1: 加依赖**

在 `requirements.txt` 第 43 行（`# --- 数据库：PostgreSQL（数据库设计-V1.1）---` 段之后、`# --- 生产部署` 之前）插入新分组：

```
# --- 逐字声学数据（上传示范时附带的 Excel）---
openpyxl==3.1.5             # 只读 .xlsx；纯 Python，Mac/Linux 都装得上
```

在 `# --- 其它 ---` 分组（`packaging==26.3` 那两行下面）加它的传递依赖：

```
et_xmlfile==2.0.0           # openpyxl 的传递依赖，一并钉死
```

然后安装：

```bash
.venv/bin/pip install -r requirements.txt
.venv/bin/pip show openpyxl et_xmlfile | grep -E '^(Name|Version)'
```

Expected: 两个包都显示刚写的版本，且 `pip check` 无输出（`No broken requirements found.`）。

- [ ] **Step 2: 写模块**

Create `app/services/lyrics_excel.py`：

```python
# -*- coding: utf-8 -*-
"""上传示范时附带的逐字声学数据（Excel）解析。

纯函数：不碰数据库、不碰 flask、不引用 request——脱离整个应用也能单独喂一个
xlsx 调用（项目没有测试框架，验证靠临时脚本）。

输入是教师按《8-数据准备清单-V1.0》4.3 节模板做的表：一页 = 一段，表头
`字序 | 字 | 音高 | 起始时间(s) | 结束时间(s) | 演唱技巧提示`。输出直接对齐
`segments` 的列：`[{seq, title, duration, lyrics}]`，`lyrics` 里每个字是
`{word, midi, start, end, note, tip}`——正是 `segments.lyrics_json` 的列注释
形状，也是 C3 `_normalize_lyrics` 的读入口径。

**时间必须转成段内相对秒数**：跟唱页拿 `start` 与「本段已播放到第几秒」比
（spec 2.3），原样存全局时间的话第 5 段往后的字永远匹配不上、不会高亮。
"""

import io
import re

import openpyxl

from app.common.errors import BusinessError

SHEET_RE = re.compile(r"^第\s*(\d+)\s*段(?:_|-)?(.*)$")
MIDI_RE = re.compile(r"^\s*(\d+)")
# 表头可能带单位后缀（`起始时间(s)`），比对列名时剥掉
UNIT_SUFFIX_RE = re.compile(r"[（(].*?[)）]\s*$")

COL_WORD = "字"
COL_MIDI = "音高"
COL_START = "起始时间"
COL_END = "结束时间"
COL_TIP = "演唱技巧提示"
REQUIRED_COLS = (COL_WORD, COL_MIDI, COL_START, COL_END)


def parse_segments(blob: bytes) -> list[dict]:
    """xlsx 字节流 → `[{seq, title, duration, lyrics}]`，按 seq 升序。

    失败一律抛 `BusinessError(400, ...)`：这张表是教师自己做的，报错文案会
    原样给他看，「第3段 缺少列：起始时间」比「服务器内部错误」有用得多。
    """
    workbook = _load(blob)
    pages = []
    for name in workbook.sheetnames:
        matched = SHEET_RE.match(name.strip())
        if matched is not None:
            pages.append((int(matched.group(1)), matched.group(2).strip(" _-"), workbook[name]))
    if not pages:
        raise BusinessError(400, "逐字数据里没有找到『第N段_…』格式的数据页")

    # 页在表里的顺序不保证就是段序，按页名里的 N 排
    pages.sort(key=lambda page: page[0])
    return [_parse_page(seq, title, sheet) for seq, title, sheet in pages]


def _parse_page(seq: int, title: str, sheet) -> dict:
    rows = [list(row) for row in sheet.iter_rows(values_only=True)]
    cols = _header_cols(rows[0] if rows else [])
    for name in REQUIRED_COLS:
        if name not in cols:
            raise BusinessError(400, f"第{seq}段 缺少列：{name}")

    lyrics = [c for c in (_char(row, cols) for row in rows[1:]) if c is not None]

    starts = [c["start"] for c in lyrics if c["start"] is not None]
    if not starts:
        # 整页没标时间（如第 1、2 段，那些字唱在被剪掉的开头里）：字照存、
        # 时间全空，duration 也给 None——前端对段长非有限值有「时长未知」分支。
        duration = None
    else:
        base = min(starts)
        for char in lyrics:
            char["start"] = _rel(char["start"], base)
            char["end"] = _rel(char["end"], base)
        ends = [char["end"] for char in lyrics if char["end"] is not None]
        # 该页最后一个有时间的字的 end（已转相对）就是段长。中间缺时间的字
        # 只是没有自己的 start/end，不影响这个值（spec 3.3）。
        duration = ends[-1] if ends else None

    return {"seq": seq, "title": title or f"第 {seq} 段", "duration": duration, "lyrics": lyrics}


def _char(row: list, cols: dict[str, int]) -> dict | None:
    word = _cell(row, cols.get(COL_WORD))
    if not isinstance(word, str) or not word.strip():
        return None
    tip = _cell(row, cols.get(COL_TIP))
    return {
        "word": word.strip(),
        "midi": _midi(_cell(row, cols.get(COL_MIDI))),
        "start": _num(_cell(row, cols.get(COL_START))),
        "end": _num(_cell(row, cols.get(COL_END))),
        # 时值由时长反推，要拿到全曲的拍长才能算，parse_segments 里统一填
        "note": None,
        "tip": tip.strip() if isinstance(tip, str) and tip.strip() else None,
    }


def _header_cols(header: list) -> dict[str, int]:
    """表头名 → 列号。按名字定位而不认死列号：教师在前面加一列「备注」不该让
    整张表作废。同名列取第一个，重复列不去猜。
    """
    cols: dict[str, int] = {}
    for index, name in enumerate(header):
        if isinstance(name, str) and name.strip():
            cols.setdefault(UNIT_SUFFIX_RE.sub("", name.strip()), index)
    return cols


def _cell(row: list, index: int | None):
    return row[index] if index is not None and index < len(row) else None


def _num(value) -> float | None:
    """时间列不一定是数字——可能是文字 `不在修剪版中`（spec 2.1），一律当缺时间。"""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _midi(value) -> int | None:
    """音高列形如 `56 (G#3)`：只取 MIDI 号。括号里的音名由前端 midiToNote
    算出来（spec 4），不重复存。
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(round(value))
    matched = MIDI_RE.match(value) if isinstance(value, str) else None
    return int(matched.group(1)) if matched else None


def _rel(value: float | None, base: float) -> float | None:
    """转段内相对时间。round(3) 与 parse_service._split_segments 的 duration
    同精度——浮点减法会给出 3.9800000000000004 这种值，落进 JSONB 很难看。
    """
    return None if value is None else round(value - base, 3)


def _load(blob: bytes):
    try:
        return openpyxl.load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
    except Exception as exc:
        # 坏文件由 openpyxl 底下的 zip 层抛什么类型不定（BadZipFile / KeyError /
        # InvalidFileException 都见过），逐个列举不如一律转 400——传错文件是
        # 教师的常见操作，不该回 500。
        raise BusinessError(400, "逐字数据文件无法解析，请确认是 .xlsx") from exc
```

- [ ] **Step 3: 用真实 xlsx 验证**

```bash
cat > /tmp/verify_lyrics_excel_t1.py <<'PY'
import sys
from app.services import lyrics_excel

pages = lyrics_excel.parse_segments(open(sys.argv[1], "rb").read())

assert len(pages) == 10, len(pages)
assert [p["seq"] for p in pages] == list(range(1, 11))
assert pages[0]["title"] == "辕门外三声炮如同雷震", pages[0]["title"]
assert pages[9]["title"] == "谁料想我五十三岁又管三军", pages[9]["title"]

total = sum(len(p["lyrics"]) for p in pages)
assert total == 79, total
untimed = sum(1 for p in pages for c in p["lyrics"] if c["start"] is None)
assert untimed == 24, untimed

durations = [p["duration"] for p in pages]
assert durations == [None, None, 3.98, 21.04, 4.97, 5.81, 9.4, 3.97, 3.09, 20.28], durations

# 时间已转段内相对：第 4 段首字是 0.0（Excel 里是 3.98）
assert pages[3]["lyrics"][0] == {
    "word": "当", "midi": 63, "start": 0.0, "end": 0.91,
    "note": None, "tip": "平稳行腔，咬字清楚",
}, pages[3]["lyrics"][0]
# 第 3 段是混合情形：前 3 字无时间，基准 0.0 来自「冠」
assert [c["start"] for c in pages[2]["lyrics"]] == [None, None, None, 0.0, 0.73, 1.92, 2.45]
assert pages[2]["lyrics"][-1]["word"] == "鬓" and pages[2]["lyrics"][-1]["end"] == 3.98
# 第 1、2 段整页无时间
assert all(c["start"] is None and c["end"] is None for c in pages[0]["lyrics"] + pages[1]["lyrics"])

print("Task 1 OK:", total, "字 /", untimed, "字无时间 / 段时长", durations)
PY
PYTHONPATH=. .venv/bin/python /tmp/verify_lyrics_excel_t1.py 穆桂英挂帅_逐字声学数据_4.3.xlsx
```

Expected: `Task 1 OK: 79 字 / 24 字无时间 / 段时长 [None, None, 3.98, 21.04, 4.97, 5.81, 9.4, 3.97, 3.09, 20.28]`

- [ ] **Step 4: 验证三条报错分支**

```bash
printf 'not an xlsx at all' > /tmp/bad.xlsx
PYTHONPATH=. .venv/bin/python -c "
from app.services import lyrics_excel
from app.common.errors import BusinessError
for blob, expect in [(open('/tmp/bad.xlsx','rb').read(), '无法解析')]:
    try:
        lyrics_excel.parse_segments(blob); print('失败：没抛异常')
    except BusinessError as e:
        print(e.code, e.message); assert e.code == 400 and expect in e.message
"
```

Expected: `400 逐字数据文件无法解析，请确认是 .xlsx`

- [ ] **Step 5: Commit**

```bash
git add requirements.txt app/services/lyrics_excel.py
git commit -m "feat: 逐字声学数据 Excel 解析（段与段内相对时间）"
```

---

### Task 2: `note` 反推（按曲自适应拍长）

**Files:**
- Modify: `app/services/lyrics_excel.py`
- Verify: `/tmp/verify_lyrics_excel_t2.py`（临时，不入库）

**Interfaces:**
- Consumes: Task 1 的 `_parse_page` / `_char`（形状不变）
- Produces:
  - `_estimate_beat(lengths: list[float]) -> float`
  - `_quantize(length: float, beat: float) -> str | None`
  - `_length(char: dict) -> float | None`
  - `parse_segments` 的返回值里 `lyrics[i]["note"]` 变成 `NOTE_*` 标签或 `None`
  - 模块常量 `MIN_BEAT_SAMPLES = 5`、`DEFAULT_BEAT_SEC = 1.9`、`BEAT_MIN/BEAT_MAX = 0.5/3.0`、`MAX_RATIO = 1.5`

- [ ] **Step 1: 加常量与 logger**

import 区改成：

```python
import io
import logging
import math
import re
import statistics

import openpyxl
```

`REQUIRED_COLS = (COL_WORD, COL_MIDI, COL_START, COL_END)` 之后加：

```python
logger = logging.getLogger(__name__)

# ===== 拍长与时值 =====
#
# 档位 = 前端词表（annotation.html 的 NOTE_LABELS / NOTE_DOT_LABELS）的 11 个
# 标签，值是「几拍」。**词表里没有 NOTE_DOT_1**，1.5 拍这一档不存在，所以词表
# 最长只表达到 1 拍。
NOTE_CANDIDATES = [
    ("NOTE_32", 1 / 32), ("NOTE_DOT_32", 1.5 / 32),
    ("NOTE_16", 1 / 16), ("NOTE_DOT_16", 1.5 / 16),
    ("NOTE_8", 1 / 8), ("NOTE_DOT_8", 1.5 / 8),
    ("NOTE_4", 1 / 4), ("NOTE_DOT_4", 1.5 / 4),
    ("NOTE_2", 1 / 2), ("NOTE_DOT_2", 1.5 / 2),
    ("NOTE_1", 1.0),
]
MIN_BEAT_SAMPLES = 5     # 少于这么多个有时间的字就不估了，中位数没有意义
DEFAULT_BEAT_SEC = 1.9   # ⚠️ 未经真实素材标定，性质同 parse_service.TOP_DB
BEAT_MIN, BEAT_MAX = 0.5, 3.0
MAX_RATIO = 1.5          # 超出词表能表达的最长档
```

- [ ] **Step 2: 在 `parse_segments` 里填 note**

把 `parse_segments` 末尾的

```python
    pages.sort(key=lambda page: page[0])
    return [_parse_page(seq, title, sheet) for seq, title, sheet in pages]
```

改成

```python
    pages.sort(key=lambda page: page[0])
    parsed = [_parse_page(seq, title, sheet) for seq, title, sheet in pages]

    # 拍长按整曲估（一段只有几个字，单段估会抖），估出来只记日志——字时长
    # 本来就在库里，任何时候都能重算，不必入库也不必加列。
    lengths = [x for x in (_length(c) for p in parsed for c in p["lyrics"]) if x is not None]
    beat = _estimate_beat(lengths)
    logger.info("逐字数据估出拍长 %.2fs（%d 个字参与）", beat, len(lengths))

    for page in parsed:
        for char in page["lyrics"]:
            length = _length(char)
            char["note"] = None if length is None else _quantize(length, beat)
    return parsed
```

- [ ] **Step 3: 加三个函数**

在 `_rel` 之后、`_load` 之前插入：

```python
def _length(char: dict) -> float | None:
    start, end = char["start"], char["end"]
    # end <= start 的字（教师填错、或时长为 0）拿不到档位，也不该进拍长估计
    if start is None or end is None or end <= start:
        return None
    return end - start


def _estimate_beat(lengths: list[float]) -> float:
    """这一曲的一拍秒数 = 中位字长 × 2（把中位数的那个字当半拍）。

    **别改回「遍历候选拍长、逐个把全体字量化一遍、取拟合最优」**：候选档位在
    log2 尺度上按八度周期重复（每个档 r 都有 r/2 的正牌档与 r×1.5 的附点档），
    所以任何只由字长算出来的目标函数都分辨不出 B 与 2B——实测那条网格搜索在
    0.3–3.0s 上收敛到上界 2.96s，即「最长那个字恰好算一拍」，是词表上端只到
    1 拍造成的边界伪解，不是曲速。八度只能由外部约定定下来；中位数同时天然
    抗离群（6.18s / 9.55s 的长拖腔推不动它）。推导见 spec 3.5。
    """
    if len(lengths) < MIN_BEAT_SAMPLES:
        return DEFAULT_BEAT_SEC
    # 字长本身是 round(3) 出来的，中位数会带上浮点尘埃（0.84 × 2 = 1.6800000000000015）
    median = round(statistics.median(lengths), 3)
    return min(max(2 * median, BEAT_MIN), BEAT_MAX)


def _quantize(length: float, beat: float) -> str | None:
    """字时长 → 时值档位。

    距离取对数尺度：档位是等比数列，用线性距离会让长档一侧的边界偏得离谱。
    比例超出词表能表达的最长档（1.5 拍）就留 None——长拖腔不属于常规时值，
    库里那份手工标的也是这么处理的（spec 3.5）。
    """
    ratio = length / beat
    if ratio > MAX_RATIO:
        return None
    target = math.log2(ratio)
    return min(NOTE_CANDIDATES, key=lambda item: abs(target - math.log2(item[1])))[0]
```

- [ ] **Step 4: 用真实 xlsx 验证**

```bash
cat > /tmp/verify_lyrics_excel_t2.py <<'PY'
import sys
from app.services import lyrics_excel as le

pages = le.parse_segments(open(sys.argv[1], "rb").read())
chars = [c for p in pages for c in p["lyrics"]]
lengths = [x for x in (le._length(c) for c in chars) if x is not None]

assert len(lengths) == 55, len(lengths)
beat = le._estimate_beat(lengths)
assert beat == 1.68, beat            # 中位字长 0.84 × 2

# 第 1、2 段整页没有时长 → 全部无 note
assert all(c["note"] is None for c in pages[0]["lyrics"] + pages[1]["lyrics"])
# 第 3 段前 3 字无时间 → 无 note；「冠」「压」「双」「鬓」有
assert [c["note"] for c in pages[2]["lyrics"]] == [None, None, None, "NOTE_2", "NOTE_DOT_2", "NOTE_DOT_4", "NOTE_1"]
assert pages[3]["lyrics"][0]["note"] == "NOTE_2"
assert pages[4]["lyrics"][0]["note"] == "NOTE_1"

# 超 1.5 拍的长拖腔留空
blanked = sorted(
    ((c["word"], round(c["end"] - c["start"], 3)) for c in chars
     if c["start"] is not None and c["end"] is not None and c["end"] > c["start"] and c["note"] is None),
    key=lambda item: item[1],
)
assert blanked == [("管", 2.99), ("啊", 3.44), ("披", 3.79), ("的", 6.18), ("军", 9.55)], blanked
# 24 个无时间的字 + 5 个超档的长音
assert sum(1 for c in chars if c["note"] is None) == 29

# 纯函数边界：样本不足走默认拍长；超长样本被夹住；超档留空
assert le._estimate_beat([0.5] * 4) == 1.9
assert le._estimate_beat([3.0] * 10) == 3.0
assert le._quantize(2.6, 1.68) is None
assert le._quantize(0.84, 1.68) == "NOTE_2"

print("Task 2 OK: B =", beat, "/ 留空", blanked, "/ 有 note 的字", sum(1 for c in chars if c["note"]))
PY
PYTHONPATH=. .venv/bin/python /tmp/verify_lyrics_excel_t2.py 穆桂英挂帅_逐字声学数据_4.3.xlsx
```

Expected: `Task 2 OK: B = 1.68 / 留空 [('管', 2.99), ('啊', 3.44), ('披', 3.79), ('的', 6.18), ('军', 9.55)] / 有 note 的字 50`

- [ ] **Step 5: 把 Task 1 脚本里那条断言同步过来**

`/tmp/verify_lyrics_excel_t1.py` 里第 4 段首字的期望 dict 现在有 `note` 了，把那条断言改成：

```python
assert pages[3]["lyrics"][0] == {
    "word": "当", "midi": 63, "start": 0.0, "end": 0.91,
    "note": "NOTE_2", "tip": "平稳行腔，咬字清楚",
}, pages[3]["lyrics"][0]
```

```bash
PYTHONPATH=. .venv/bin/python /tmp/verify_lyrics_excel_t1.py 穆桂英挂帅_逐字声学数据_4.3.xlsx
```

Expected: 仍打印 `Task 1 OK: 79 字 / 24 字无时间 / 段时长 [...]`。

- [ ] **Step 6: Commit**

```bash
git add app/services/lyrics_excel.py
git commit -m "feat: 逐字数据按曲自适应反推时值 note"
```

---

### Task 3: `replace_segments` 支持 `lyrics`

**Files:**
- Modify: `app/repositories/library_repo.py:59-86`
- Verify: `/tmp/verify_replace_segments.py`（临时，不入库）

**Interfaces:**
- Consumes: 无需
- Produces: `replace_segments(db, demo_id, segments)` 里每行的 `lyrics_json` 取 `s.get("lyrics")`，缺省 `None`——Demucs 那条路（`parse_service._split_segments` 产出的 dict 没有 `lyrics` 键）行为不变

- [ ] **Step 1: 改实现与注释**

把 `app/repositories/library_repo.py:59-86` 的 `replace_segments` 整体换成：

```python
def replace_segments(db: Session, demo_id: int, segments: list[dict]) -> None:
    """整批替换某 demo 的分段：先按 demo_id DELETE，再 INSERT。

    幂等的关键：同一 demo 重跑解析不会累积脏行（解析任务整体可重入）。
    不用「按 seq upsert」是因为段数可能变少（阈值调过、素材换过），
    upsert 会留下上一轮多出来的尾巴。

    参数是纯 dict（[{seq,title,duration,lyrics?}]）而不是 ORM 对象：分段可能
    在 worker 进程里用 numpy 算出来，那边根本没有 Session。

    lyrics 来自上传时附带的逐字数据（app/services/lyrics_excel.py）；没有它
    时（Demucs 那条路）为 None——第 20 条：音频本身给不出汉字。segments 表没有
    start/end 列，逐字的位置信息全在 lyrics_json 里。

    只 flush 不 commit；DELETE 由 Core 语句当场发出，必然排在 flush 的
    INSERT 之前，不会出现「新行插进去又被删掉」。
    """
    db.execute(delete(Segment).where(Segment.demo_id == demo_id))
    db.add_all([
        Segment(
            demo_id=demo_id,
            seq=s["seq"],
            title=s["title"],
            lyrics_json=s.get("lyrics"),
            duration=s["duration"],
        )
        for s in segments
    ])
    db.flush()
```

- [ ] **Step 2: 验证两条路**

```bash
cat > /tmp/verify_replace_segments.py <<'PY'
from sqlalchemy import delete, select
from app.db import session_scope
from app.models.demo import Segment, TeacherDemo
from app.repositories import library_repo

with session_scope() as db:
    demo = TeacherDemo(title="临时-验证 replace_segments", role=None, banshi=None, audio_id=None)
    db.add(demo)
    db.flush()
    demo_id = demo.id

    # Demucs 那条路：dict 里没有 lyrics 键
    library_repo.replace_segments(db, demo_id, [{"seq": 1, "title": "第 1 段", "duration": 2.5}])
    row = db.scalars(select(Segment).where(Segment.demo_id == demo_id)).one()
    assert row.lyrics_json is None, row.lyrics_json

    # Excel 那条路：带 lyrics
    lyrics = [{"word": "当", "midi": 63, "start": 0.0, "end": 0.91, "note": "NOTE_2", "tip": None}]
    library_repo.replace_segments(db, demo_id, [
        {"seq": 1, "title": "当年的铁甲", "duration": 21.04, "lyrics": lyrics},
    ])
    rows = db.scalars(select(Segment).where(Segment.demo_id == demo_id)).all()
    assert len(rows) == 1 and rows[0].duration == 21.04
    assert rows[0].lyrics_json == lyrics, rows[0].lyrics_json

with session_scope() as db:                       # 清理
    db.execute(delete(Segment).where(Segment.demo_id == demo_id))
    db.execute(delete(TeacherDemo).where(TeacherDemo.id == demo_id))

print("Task 3 OK: 缺 lyrics 时 NULL，带 lyrics 时原样落 JSONB，整批替换不累行")
PY
PYTHONPATH=. .venv/bin/python /tmp/verify_replace_segments.py
```

Expected: `Task 3 OK: 缺 lyrics 时 NULL，带 lyrics 时原样落 JSONB，整批替换不累行`

- [ ] **Step 3: 确认没有别处依赖旧行为**

```bash
grep -rn "replace_segments" app/ scripts/ 2>/dev/null
```

Expected: 只有 `library_repo` 的定义、`parse_service` 的调用、`library_service` 里 Task 5 要加的调用（此刻还没有），以及可能的脚本。**若有脚本传的是位置参数元组而不是 dict，先记下来**——本计划不改脚本。

- [ ] **Step 4: Commit**

```bash
git add app/repositories/library_repo.py
git commit -m "feat: replace_segments 落 lyrics_json"
```

---

### Task 4: `_master_duration` 提升为 `audio_service.probe_duration`

**Files:**
- Modify: `app/services/audio_service.py`（加函数）
- Modify: `app/services/parse_service.py:36`（import）、`:246-265`（删函数）、`:322`（改调用）
- Verify: 命令行 + `grep`

**Interfaces:**
- Produces: `audio_service.probe_duration(path: Path) -> float | None`
- 删除：`parse_service._master_duration`（无其他调用方）

- [ ] **Step 1: 在 `audio_service` 里加函数**

`app/services/audio_service.py` 的 import 区改成（`import logging` 加在最前，`import librosa` 归入第三方那组）：

```python
import logging
from pathlib import Path

import librosa
from sqlalchemy.orm import Session
from werkzeug.datastructures import FileStorage
```

`ACCESS_PUBLIC = "public"` 之前加：

```python
logger = logging.getLogger(__name__)
```

在 `save_upload` 之后、`get_playable` 之前插入：

```python
def probe_duration(path: Path) -> float | None:
    """音频文件的真实全长（秒）。多数格式只读元数据，不解码。

    走 librosa.get_duration(path=...)：它先试 soundfile 的 sf.info()，对
    wav/mp3/flac/ogg 只读文件头；soundfile 打不开的容器（m4a / aac / webm，
    都在 storage.ALLOWED_EXT 里）会回退到 audioread，那条路径经 ffmpeg 把整个
    文件解一遍（秒级到几十秒）。所以这里是「通常很便宜」而非「一定零成本」。

    读不出来返回 None 而不是 0.0：0 是个会写进 audio_files.duration_sec 的
    「合法」值，列表页会如实显示成 0.0 秒，等于用一个假数据掩盖了读取失败。
    返回 None 时调用方跳过回填，列保持 NULL（前端显示「—」）。

    两个调用方（上传接口同步回填、解析任务 worker 回填）共用这一份实现——
    各写一份迟早会漂移。
    """
    try:
        return float(librosa.get_duration(path=str(path)))
    except Exception:
        logger.exception("读取音频时长失败：%s", path)
        return None
```

- [ ] **Step 2: `parse_service` 改调用**

- 第 36 行 `from app.services import vocal_service` → `from app.services import audio_service, vocal_service`
- 删掉第 246–265 行的 `_master_duration` 函数（连它下面的那个空行一起删），**保留**它下方 `# ===== 内部：后台执行（Celery）=====` 那个分节注释
- 第 321–322 行改成：

```python
    # 时长在读文件头这一步拿，与后面的分离无关，先取好省得回填时再开一次会话
    duration = audio_service.probe_duration(path)
```

- [ ] **Step 3: 验证**

```bash
grep -rn "_master_duration" app/ scripts/ ; echo "grep 退出码 $? （1 = 已经没有引用，符合预期）"
PYTHONPATH=. .venv/bin/python -c "
from app.services import audio_service, parse_service
from app.common import storage
p = storage.resolve('demos/muguaying_yuanmenwai.wav')
print('probe_duration =', audio_service.probe_duration(p))
print('文件不存在时 =', audio_service.probe_duration(p.with_name('nope.wav')))
print('parse_service 仍能导入:', parse_service.STATUS_PARSING)
"
```

Expected: `grep` 无输出、退出码 1；打印 `probe_duration = 111.9…`（一个 100~200 之间的浮点数），文件不存在时打印 `None` 并有一行 ERROR 日志，最后一行 `parse_service 仍能导入: parsing`。

- [ ] **Step 4: Commit**

```bash
git add app/services/audio_service.py app/services/parse_service.py
git commit -m "refactor: 音频时长探测提升到 audio_service.probe_duration"
```

---

### Task 5: 上传接口分支（service + api）

**Files:**
- Modify: `app/services/library_service.py`（`demo_library_add` 加 `commit` 参数；新增 `demo_library_add_with_segments`）
- Modify: `app/api/demo_library.py:26-65`
- Verify: curl + psql

**Interfaces:**
- Consumes: `lyrics_excel.parse_segments`（Task 1/2）、`replace_segments` 的 `lyrics`（Task 3）、`audio_service.probe_duration`（Task 4）
- Produces:
  - `library_service.demo_library_add(db, *, title, role=None, banshi=None, audio_id=None, commit=True) -> TeacherDemo`
  - `library_service.demo_library_add_with_segments(db, *, title, role=None, banshi=None, audio: AudioFile, segments: list[dict], commit=True) -> TeacherDemo`
  - 上传接口响应 `{"code":0,"message":"ok","data":{"demo_id": int, "task_id": str | None}}`

- [ ] **Step 1: `demo_library_add` 加 `commit` 参数**

`app/services/library_service.py:84-117`，签名加 `commit: bool = True`，末尾的 `db.commit()` 改成按参数提交，docstring 的对应段落改掉：

```python
def demo_library_add(
    db: Session,
    *,
    title: str,
    role: str | None = None,
    banshi: str | None = None,
    audio_id: int | None = None,
    commit: bool = True,
) -> TeacherDemo:
    """新增示范曲目。事务边界在本层，写操作显式 commit。

    audio_id 由调用方传入（audio_files flush 出来的自增主键），本层只负责把
    外键写进去，不反查、不补建。

    commit=True 时这次提交同时提交前一步 save_upload(commit=False) 留在同一
    会话里的 audio_files 行——示范曲目上传要的就是「两行一次提交」：任何一边
    失败，两边都留不下半条记录。commit=False 是给带逐字数据的上传用的：那条路
    还得先写 segments、回填时长，唯一提交点在 demo_library_add_with_segments。

    **解析任务的投递不在这里做**：submit() 需要 demo.id，而这条 commit 之后
    才轮到 api 层调 parse_service.submit()。若 redis 挂了导致 submit 失败，
    上传接口会回 500，但 teacher_demos 那行已经落库、segments 为空——此时
    详情页的派生状态恰好是 unparsed（「没解析过」），是一句实话，用户可以
    重新上传。这个顺序是刻意选的：先落库、后投任务。
    """
    demo = TeacherDemo(
        title=title,
        # 表单下拉框未选时提交的是空串，落库统一成 NULL：
        # 空串会让「按行当筛选」之类的查询多出一个无意义的取值。
        role=role or None,
        banshi=banshi or None,
        audio_id=audio_id,
    )
    library_repo.add_library(db, demo)
    if commit:
        db.commit()
    return demo


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
    """带逐字数据的示范上传：建 demo + 写 segments + 回填音频时长。

    **这里的 commit 是这条链路唯一的提交点**：调它之前不能有任何提交，否则
    解析失败就撤不干净。逐字数据的解析已经在调用方做完并先于落盘——坏文件
    连音频文件都不会落盘（spec 3.1、3.4）。

    与 Demucs 那条路的区别：段边界由唱词句给出，不再需要停顿切分，所以不投
    解析任务；时长也在同一事务里回填（worker 那条路是解析时回填）。
    """
    demo = demo_library_add(
        db, title=title, role=role, banshi=banshi, audio_id=audio.id, commit=False
    )
    library_repo.replace_segments(db, demo.id, segments)
    duration = audio_service.probe_duration(storage.resolve(audio.file_path))
    if duration is not None:
        library_repo.update_audio_duration(db, demo.id, duration)
    if commit:
        db.commit()
    return demo
```

同时在文件顶部的 import 区补三行（按字母序插进去），改完是：

```python
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common import storage
from app.common.errors import BusinessError
from app.models import TeacherDemo
from app.models.audio import AudioFile
from app.models.demo import Segment
from app.repositories import annotations_repo, library_repo
from app.services import audio_service, parse_service
```

注意 `parse_service` 现在也 import 了 `audio_service`——没有环，不用动。

- [ ] **Step 2: 上传路由分支**

`app/api/demo_library.py` 的 import 区第 23 行改成（**只加 `lyrics_excel`，不要加 `storage`**——路径解析在 service 层做，路由层不碰文件系统）：

```python
from app.services import audio_service, library_service, lyrics_excel, parse_service
```

模块 docstring 第 4 行同步改成：

```
    POST /api/demo/library/upload                     登录  上传示范音频（可附带逐字数据 Excel）
```

`demo_library_upload` 整个函数换成：

```python
@api_bp.route("/demo/library/upload", methods=["POST"])
@login_required
def demo_library_upload():
    """上传示范音频：落盘 + 建两行，返回 {demo_id, task_id}。

    带 `excel` 字段时按逐字数据建段、**不投 Demucs 任务**（task_id 为 null）；
    不带时原路不变，投 demucs 队列由 worker 切分（spec 3.1）。

    鉴权只要求登录（本轮「权限先不管」的决策，见 spec 第 2 节）。`access`
    仍按角色取值——`audio_service.save_upload` 只允许教师设 public。
    """
    file = request.files.get("audio")
    if file is None or not file.filename:
        raise BusinessError(400, "缺少音频文件（multipart 字段名应为 audio）")

    # 解析排在落盘之前：逐字数据有问题就整批回滚，连音频文件都不落盘（spec 3.4）
    excel = request.files.get("excel")
    segments = None
    if excel is not None and excel.filename:
        segments = lyrics_excel.parse_segments(excel.read())

    db = get_db()
    # commit=False：这一行先不提交，和下面 teacher_demos 那行合成一次事务，
    # 由 service 层末尾统一 commit（提交点见 service 层的说明）。
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

    # title 在库里是 NOT NULL，前端没填时退回文件名（不含扩展名）
    title = request.form.get("title") or Path(file.filename).stem
    if segments is None:
        demo = library_service.demo_library_add(
            db,
            title=title,
            role=request.form.get("role"),
            banshi=request.form.get("banshi"),
            audio_id=audio.id,
        )
        # 提交之后才投任务：submit() 需要 demo.id，而 redis 那条记录要在「两行都
        # 落定」之后才存在，否则任务可能先跑起来、查库时 demo 还没提交。
        return ok({"demo_id": demo.id, "task_id": parse_service.submit(db, demo)})

    demo = library_service.demo_library_add_with_segments(
        db,
        title=title,
        role=request.form.get("role"),
        banshi=request.form.get("banshi"),
        audio=audio,
        segments=segments,
    )
    # 状态不写 redis：详情/状态接口走 parse_service.status 的派生路径
    # （segments 有行 → parsed），前端即便轮询也是第一次就拿到 parsed（spec 3.1）。
    return ok({"demo_id": demo.id, "task_id": None})
```

（import 那行里如果 `storage` 用不上，就去掉它——路由层不碰文件路径。）

- [ ] **Step 3: 起服务确认改动被加载**

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8877/login.html
```

Expected: `200`。8877 上若有 PyCharm 调试会话，它的 reloader 已自动加载 `.py` 改动；若回非 200，`.venv/bin/python app-d.py` 自己起一个（端口被占时先确认不是别人的进程，**不要 kill**）。

- [ ] **Step 4: 带 Excel 上传一次**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
curl -s -c /tmp/ck.txt -H 'Content-Type: application/json' \
  -d '{"username":"teacher01","password":"xiyun@2026"}' \
  http://127.0.0.1:8877/api/auth/login
curl -s -b /tmp/ck.txt \
  -F "audio=@uploads/demos/muguaying_yuanmenwai.wav" \
  -F "excel=@穆桂英挂帅_逐字声学数据_4.3.xlsx" \
  -F "title=穆桂英挂帅·逐字验证" -F "access=public" \
  http://127.0.0.1:8877/api/demo/library/upload
```

Expected: 第二条回 `{"code":0,"message":"ok","data":{"demo_id":17,"task_id":null}}`（`demo_id` 是 17 或更大，取决于库现状——记下这个数，下面用它）。

- [ ] **Step 5: 查库与状态**

```bash
DEMO=17   # 换成上一步回的真实 demo_id
docker exec -i -e PGPASSWORD=xiyun docker_postgres psql -U xiyun -d xiyun -c \
  "select seq, title, duration, jsonb_array_length(lyrics_json) n, lyrics_json->0 first from segments where demo_id=$DEMO order by seq"
docker exec -i -e PGPASSWORD=xiyun docker_postgres psql -U xiyun -d xiyun -c \
  "select d.id, d.title, a.file_path, a.duration_sec from teacher_demos d join audio_files a on a.id=d.audio_id where d.id=$DEMO"
curl -s -b /tmp/ck.txt "http://127.0.0.1:8877/api/demo/library/$DEMO/parse/status"
curl -s -b /tmp/ck.txt "http://127.0.0.1:8877/api/demo/library/$DEMO" | head -c 400
```

Expected:
- 10 行，`seq` 1–10，`title` 是唱词（`辕门外三声炮如同雷震` …），`duration` 依次 `10 | 11 | 3.98 | 21.04 | 4.97 | 5.81 | 9.4 | 3.97 | 3.09 | 20.28`（前两段 NULL），`n` 是 `10 | 11 | 7 | 11 | 6 | 8 | 5 | 5 | 4 | 12`
- 第一行 `first` 形如 `{"tip": "平稳行腔，咬字清楚", "midi": 56, "note": null, "word": "辕", "start": null, "end": null}`
- `duration_sec` 是 111.9… 这样的真实时长（不是 NULL）
- 状态接口立刻回 `"status":"parsed","progress":100`
- 详情接口的 `segments` 数组有 10 个元素

- [ ] **Step 6: 坏文件不留痕**

```bash
printf 'not an xlsx' > /tmp/bad.xlsx
curl -s -b /tmp/ck.txt \
  -F "audio=@uploads/demos/muguaying_yuanmenwai.wav" \
  -F "excel=@/tmp/bad.xlsx" -F "title=坏文件验证" -F "access=public" \
  http://127.0.0.1:8877/api/demo/library/upload
docker exec -i -e PGPASSWORD=xiyun docker_postgres psql -U xiyun -d xiyun -tAc \
  "select count(*) from teacher_demos; select count(*) from audio_files; select count(*) from segments"
ls uploads/demos | wc -l
```

Expected: 回 `{"code":400,"message":"逐字数据文件无法解析，请确认是 .xlsx","data":null}`；三个计数与 Step 4 之后完全相同（没有新 demo / audio / segment）；`uploads/demos` 的文件数也没变（解析排在落盘之前）。

- [ ] **Step 7: 不带 Excel 的旧路不变**

```bash
curl -s -b /tmp/ck.txt \
  -F "audio=@uploads/demos/muguaying_yuanmenwai.wav" \
  -F "title=无 Excel 验证" -F "access=public" \
  http://127.0.0.1:8877/api/demo/library/upload
```

Expected: 回 `{"demo_id":<新 id>,"task_id":"<12 位 hex>"}`；`parse/status` 回 `"status":"parsing"`（worker 没起就是停在 parsing，这是预期）。

收尾：把这条「无 Excel 验证」记录删掉，免得列表里多一首没有分段的曲目：

```bash
docker exec -i -e PGPASSWORD=xiyun docker_postgres psql -U xiyun -d xiyun -c \
  "delete from segments where demo_id=<新 id>; delete from teacher_demos where id=<新 id>;"
```

Step 4 那条带逐字数据的记录**留着**——Task 7 要在浏览器里用它验证标注页。

- [ ] **Step 8: Commit**

```bash
git add app/services/library_service.py app/api/demo_library.py
git commit -m "feat: 上传示范可附带逐字数据 Excel，带 Excel 时跳过 Demucs"
```

---

### Task 6: 前端上传表单（`demo_library.html`）

**Files:**
- Modify: `demo_library.html:1405-1419`（弹窗）、`:1633-1635`（状态变量）、`:2030-2049`（重置与选中）、`:2053-2102`（上传）

**Interfaces:**
- Consumes: Task 5 的响应 `data.task_id`（有 Excel 时为 `null`）
- Produces: 新增字段名 `excel` 进同一个 `FormData`

- [ ] **Step 1: 弹窗加一行**

在 `demo_library.html` 的「音频文件」那个 `modal-row`（含 `id="fileDrop"`）之后、`<div class="modal-actions">` 之前插入：

```html
            <div class="modal-row">
                <label>逐字数据</label>
                <div class="file-drop" id="excelDrop" onclick="document.getElementById('excelInput').click()">
                    <div class="hint">可选：逐字声学数据 Excel<br><span style="color:var(--text-muted);font-size:11px">.xlsx，一页一段，表头含「字 / 音高 / 起始时间 / 结束时间」</span></div>
                    <div class="file-name" id="excelName" style="display:none"></div>
                </div>
                <input type="file" id="excelInput" accept=".xlsx" style="display:none" onchange="onExcelSelect(event)">
            </div>
```

- [ ] **Step 2: 状态变量与选中处理**

第 1633–1635 行

```js
        let activeDemoId = null,
            pollTimer = null,
            selectedFile = null;
```

改成

```js
        let activeDemoId = null,
            pollTimer = null,
            selectedFile = null,
            selectedExcel = null;
```

`showUploadModal()`（约 2030 行）里重置字段的那几行之后补：

```js
            selectedExcel = null;
            document.getElementById("excelName").style.display = "none";
            document.getElementById("excelName").textContent = "";
            document.getElementById("excelInput").value = "";
```

`onFileSelect` 之后加：

```js
        // **不参与 uploadTitle 的自动回填**：那个回填是音频文件名的逻辑
        // （见 onFileSelect），被 Excel 抢走会把曲目名填成表名
        function onExcelSelect(e) {
            const file = e.target.files[0];
            if (!file) return;
            selectedExcel = file;
            document.getElementById("excelName").textContent = file.name;
            document.getElementById("excelName").style.display = "";
        }
```

- [ ] **Step 3: `doUpload` 带上文件与分支**

`doUpload` 里 `form.append("audio", selectedFile);` 之后加：

```js
            if (selectedExcel) form.append("excel", selectedExcel);
```

把响应处理那段（从 `hideUploadModal();` 到 `startPolling(data.demo_id);`）换成：

```js
                hideUploadModal();
                if (data.task_id) {
                    // body.message 恒为 "ok"（信封顶层的固定文案），说不了任何事；
                    // 真正有意义的是 task_id —— 用户报障时能拿去 grep worker 日志。
                    showToast("success", "上传成功", `已提交解析任务 ${data.task_id}`);
                    processingFileName = selectedFile ? selectedFile.name : (title || "未命名文件");
                    showProcessingModal(processingFileName, data.demo_id);
                } else {
                    // 带逐字数据时不投 Demucs：段已经按唱词建好了，没有可轮询的任务
                    showToast("success", "上传成功", "已按逐字数据建段，解析完成");
                }
                activeDemoId = data.demo_id;
                await fetchDemos();
                await fetchDemoDetail(data.demo_id);
                if (data.task_id) startPolling(data.demo_id);
```

`catch` 那行的失败提示保持原样。

- [ ] **Step 4: 浏览器验证**

打开 `http://127.0.0.1:8877/demo_library.html`（用 `teacher01` 登录），点「上传新示范」：

1. 只选音频、不选 Excel → 走老路（弹「处理中」、轮询）。若 worker 没起会一直转，这是预期；关掉弹窗即可。
2. 同时选音频与 `uploads/demos/muguaying_yuanmenwai.wav` + 项目根目录那份 xlsx → toast 显示「已按逐字数据建段，解析完成」，**不弹**处理中弹窗，列表里出现新曲目，详情有 10 段。
3. 标题自动回填只跟音频文件名走，选 Excel 不改标题。

- [ ] **Step 5: Commit**

```bash
git add demo_library.html
git commit -m "feat: 上传示范弹窗增加逐字数据（可选）"
```

---

### Task 7: `annotation.html` 补 `start` 空值容错

**Files:**
- Modify: `annotation.html:655`、`:684`

**Interfaces:**
- Consumes: C3（`GET /api/segments/<id>`）返回的 `start` 可能是 `null`（无时间的字）
- Produces: 无

- [ ] **Step 1: 改两处**

`renderLyrics` 里：

```js
      html += `<div class="lyric-time">${item.start.toFixed(1)}s</div>`;
```

改成

```js
      // 缺时间的字 `null.toFixed` 会抛 TypeError、打断整个 renderLyrics，网格渲染到
      // 一半就停。判定用 Number.isFinite 而不是 !== null：NaN 也会输出 "NaN"（与 sing_along.html 同口径）
      html += `<div class="lyric-time">${Number.isFinite(item.start) ? item.start.toFixed(1) + "s" : "—"}</div>`;
```

`selectChar` 里：

```js
  document.getElementById("metaTime").textContent = `起止: ${item.start.toFixed(2)}s`;
```

改成

```js
  document.getElementById("metaTime").textContent =
    Number.isFinite(item.start) ? `起止: ${item.start.toFixed(2)}s` : "起止: —";
```

- [ ] **Step 2: 浏览器验证**

打开 `http://127.0.0.1:8877/annotation.html`，选 Task 5 建的示范（`穆桂英挂帅·逐字验证`）里的第 3 段：

1. 歌词网格完整渲染出 7 个字（改造前会停在「头」字之前、右侧一片空白）。
2. 「头」「戴」「金」显示 `—`，点它们右侧「起止」也显示 `—`。
3. 「冠」「压」等有时间的字照常显示秒数，标注类型按钮可点。

- [ ] **Step 3: Commit**

```bash
git add annotation.html
git commit -m "fix: 标注页对缺时间的字不再抛异常"
```

---

### Task 8: 文档同步

**Files:**
- Modify: `DOC_ISSUES.md`（第 20 条「当前处理」段 + 结尾的「待文档方确认」；第 18 条那段「待文档方确认」的第 2 问）
- Modify: `CLAUDE.md`（示范库解析链路一节）

**Interfaces:** 无代码接口

- [ ] **Step 1: 改 `DOC_ISSUES.md` 第 20 条**

把 452 行那句

```
**当前处理**：已落地——解析**不写 `lyrics_json`**，解析只落分段与时长，同时回填 `audio_files.duration_sec`。
```

改成

```
**当前处理**：已落地——解析**不写 `lyrics_json`**，解析只落分段与时长，同时回填 `audio_files.duration_sec`。**2026-10-15 起有第二条路**：上传示范时可附带一张按《8-数据准备清单》4.3 节模板做的 Excel，逐字数据由它写进 `lyrics_json`，该路跳过 Demucs（段边界由唱词句给出）。设计见 `docs/superpowers/specs/2026-10-15-demo-lyrics-excel-upload-design.md`。**注意两处口径**：① `note` 是**由字长反推的启发式值**（拍长取该曲字长中位数 × 2），不是乐谱时值，拿到真谱面数据后应由那份覆盖；② 不带 Excel 上传时该列仍为 NULL，第 20 条的结论只在这条分支上被推翻。
```

并把结尾那句「**待文档方确认**：一期是否需要在上传表单加一个戏词录入（或上传 .lrc/.txt）的入口——这是让逐字时间轴有数据的**唯一**可行路径，且它本来就是 PRD 给一期定的做法。」改成：

```
**待文档方确认**：① 一期「戏词由老师或助教提前录入」的载体定为**上传 Excel**（而不是表单里逐字手填或 .lrc/.txt），这条链路已实现；② 逐字**时间轴**仍要求教师标注或从音频推出——Excel 模板里时间列允许填「不在修剪版中」，这类字入库时 `start`/`end` 为 `null`，前端跳过其高亮。
```

- [ ] **Step 2: 改第 18 条里对应的那句**

`DOC_ISSUES.md:348`：

```
2. 一期是否仍坚持「老师/助教提前录入戏词」的做法——若是，本次解析链路产出的**只有分段与时长，没有戏词**（`segments.lyrics_json` 留 NULL），这与产品预期是否一致（详见第 20 条）；
```

改成：

```
2. 一期「老师/助教提前录入戏词」这一做法已落地为**上传示范时附带逐字数据 Excel**（2026-10-15，见第 20 条与 `docs/superpowers/specs/2026-10-15-demo-lyrics-excel-upload-design.md`）：带 Excel 时逐字数据直接入库并跳过 Demucs，不带时 `segments.lyrics_json` 仍留 NULL、只产分段与时长；
```

- [ ] **Step 3: 改 `CLAUDE.md`**

在示范库一节 `TOP_DB` 那条（第 86 行）之后插入一条：

```markdown
- **上传示范时可附带逐字数据 Excel（选填，`multipart` 字段名 `excel`）**：带了就按 Excel 的页建段（一页一段）、逐字数据写 `segments.lyrics_json`，**跳过 Demucs**（响应 `task_id` 为 `null`，前端不弹处理中、不轮询）；不带则原路不变（投 `demucs` 队列、`lyrics_json` 仍为 NULL）。解析在**落盘之前**做，坏文件连音频文件都不落盘，整条链路的唯一提交点是 `library_service.demo_library_add_with_segments` 末尾那次 `commit`。三处口径别踩：① Excel 的全局时间必须转**段内相对**再入库，跟唱页拿 `start` 与「本段已播放秒数」比（`sing_along.html:1172`）；② `note` 是**由字长反推的启发式值**，拍长取该曲字长中位数 × 2（`lyrics_excel._estimate_beat`）——**不要改回网格搜索**，档位阶梯按八度周期重复、拟合目标分辨不出 B 与 2B，实测会被钉在上界 2.96 s 的伪解上，推导见 spec 3.5；③ 无时间的字 `start`/`end` 为 `null`，`annotation.html` 已按 `Number.isFinite` 容错显示 `—`。解析器是 `app/services/lyrics_excel.py`（纯函数、不碰 DB），依赖 `openpyxl`。
```

- [ ] **Step 4: 检查文档描述与代码一致**

```bash
grep -n "task_id" app/api/demo_library.py | head -3
grep -n "excel" app/api/demo_library.py | head -5
grep -c "lyrics_excel" app/services/library_service.py app/api/demo_library.py
```

Expected: `task_id` 出现在两条 return 上；`excel` 出现在取字段与解析调用两处；第三行两文件各计数 ≥ 0（`library_service` 为 0 也正常——它不直接调解析器）。

- [ ] **Step 5: Commit**

```bash
git add DOC_ISSUES.md CLAUDE.md
git commit -m "docs: 记录上传示范附带逐字数据 Excel 这条链路"
```

---

## Self-Review

**Spec 覆盖**

| spec 节 | 落在哪个 Task |
|---|---|
| §3.1 上传接口分支（task_id 为 null、状态不写 redis） | Task 5 Step 2、Step 5 |
| §3.2 页 → segments 行 | Task 1 Step 2 |
| §3.3 逐字字段映射 + 段内相对 + 段时长 | Task 1 Step 2/3 |
| §3.4 失败与回滚（400、唯一提交点、必需列、容忍单位后缀） | Task 1 Step 2/4、Task 5 Step 1/6 |
| §3.5 `note` 反推与拍长自适应 | Task 2 |
| §3.6 新模块 `lyrics_excel.py` + `openpyxl` | Task 1 |
| §3.7 `replace_segments` 支持 `lyrics` | Task 3 |
| §3.8 `probe_duration` 提到 `audio_service` | Task 4 |
| §3.9 前端上传表单 | Task 6 |
| §3.10 `annotation.html` 容错 | Task 7 |
| §7 验证 1–5 | Task 1/2（1）、Task 5（2、3、4）、Task 7（5） |
| §8 文档同步 | Task 8 |
| §6 非目标（不改 schema / 详情页 / 不补传接口 / 不动 demo 16 / 不支持 .xls） | 全计划未涉及，Global Constraints 里已写死 |

**与 spec 的两处差异（已回改 spec）**：§3.4 的「唯一提交点」由 `demo_library_add` 改成 `demo_library_add_with_segments`；§3.5 的网格搜索改成中位数锚定（实测退化，见 Task 2 的注释）。

**Placeholder 扫描**：无 TBD / TODO；每个改代码的 Step 都给了完整代码；curl 与 psql 都给了确切命令与期望输出。

**类型一致性**：`parse_segments` 返回键 `seq/title/duration/lyrics`（Task 1）↔ `replace_segments` 读 `s["seq"]/s["title"]/s["duration"]/s.get("lyrics")`（Task 3）↔ 上传路由把整份传给 `demo_library_add_with_segments(segments=...)`（Task 5）；逐字键 `word/midi/start/end/note/tip`（Task 1/2）↔ `library_service._normalize_lyrics` 的读入口径（既有代码）。`demo_library_add` 的 `commit` 参数（Task 5 Step 1）与 `save_upload(commit=False)`（既有）同名同义。

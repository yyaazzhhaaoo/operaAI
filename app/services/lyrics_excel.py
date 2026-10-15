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

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
import logging
import math
import re
import statistics

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


def _load(blob: bytes):
    try:
        return openpyxl.load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
    except Exception as exc:
        # 坏文件由 openpyxl 底下的 zip 层抛什么类型不定（BadZipFile / KeyError /
        # InvalidFileException 都见过），逐个列举不如一律转 400——传错文件是
        # 教师的常见操作，不该回 500。
        raise BusinessError(400, "逐字数据文件无法解析，请确认是 .xlsx") from exc

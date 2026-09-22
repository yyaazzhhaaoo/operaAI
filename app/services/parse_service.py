# -*- coding: utf-8 -*-
"""示范库解析任务的业务逻辑（DOC_ISSUES 第 16–20 条）。

异步模型：上传接口建任务后立刻返回 task_id，真正的 Demucs 分离交给 Celery
worker 在**另一个进程**里跑，进度落在 redis（parse_task_repo），
前端 `GET /api/demo/library/<id>/parse/status` 每 3 秒轮询。

与 analyze_service 有三处**刻意**不一致：

1. 任务只收 demo_id，不收磁盘路径——路径、上传者、原有时长都由任务自己查库取。
   示范库这条链路从头到尾都在跟数据库打交道，把路径塞进消息只会多一处状态不一致。
2. 状态词表按**前端**（parsing/parsed/error，第 18 条），不是 B 组的 queued/done/failed。
3. 解析走**专用 demucs 队列**（一次 8–15 分钟，与秒级的 B 组同队列会把
   pitch_comparison.html 拖住）。代价是 worker 必须带 -Q demucs，见 app/worker.py。

本层不引用 flask.session / flask.request：Celery 任务跑在另一个进程里，
请求上下文和会话都不会跟过去。
"""

import logging

import librosa
import numpy as np

logger = logging.getLogger(__name__)

# ===== 状态词表（第 18 条：按前端，不是 B 组的 queued/done/failed）=====
#
# demo_library.html 的 startPolling 判的是 `st.status === "parsed" || "error"`，
# 所以这两个值不能改。unparsed 是本设计新增的第四个取值，**只可能出现在
# status() 的派生路径上**（redis 里那条 TTL 过期之后）。
STATUS_PARSING = "parsing"
STATUS_PARSED = "parsed"
STATUS_ERROR = "error"
STATUS_UNPARSED = "unparsed"

# ===== 阶段与进度 =====
#
# 区间刻意对齐前端 renderParseFlow 的完成阈值「progress >= t + 15」：
# 前端步骤 t = 0 / 20 / 50 / 80 / 100，所以三个阶段取下界 20 / 50 / 80 上报时，
# 恰好是「上一步变成 ✅、本步变成 🔄」，五个步骤会依次亮起。
#
# 上界（45 / 75 / 95）只是文档性的：_enter_stage 取的是 [0]，没有阶段内插值。
# 分离阶段不插值是有意的——apply_model 不提供分片回调，要细粒度进度只能自己
# 按 30 秒切片循环调用，代价是段边界丢掉跨片上下文、分离质量下降。取舍是**不切**，
# 改用 message 说清耗时预期（见 _parse）。
STAGE_SEPARATE = "人声分离"
STAGE_SEGMENT = "唱段切分"
STAGE_SAVE = "结果入库"
STAGES = [STAGE_SEPARATE, STAGE_SEGMENT, STAGE_SAVE]
STAGE_RANGE = {
    STAGE_SEPARATE: (20, 45),
    STAGE_SEGMENT: (50, 75),
    STAGE_SAVE: (80, 95),
}

# ===== 唱段切分参数 =====
#
# TOP_DB 是「多低算静音」的阈值（dB，相对峰值），librosa.effects.split 的默认值是 60。
# 这里取 30 比默认激进得多，依据是**输入已经过 Demucs 分离**：伴奏残留很少，
# 默认的 60 会把换气、拖腔的尾音一并判成静音，把一句唱腔切碎。
#
# ⚠️ 30 是**未经真实素材标定**的初始值（本轮开发不含验证环节）。调参时改这一个数
# 即可：值越小切得越碎（段数变多），越大越容易把相邻唱句并成一段。
TOP_DB = 30.0
MIN_GAP_SEC = 0.35   # 间隙短于这个就当同一段（字与字之间本就有停顿）
MIN_SEG_SEC = 1.0    # 短于这个的碎段直接丢（多是分离残留的爆破音）
FRAME_LENGTH = 2048  # 与 analyze_service 的 FRAME_LENGTH 一致
HOP_LENGTH = 512     # 16000/512 ≈ 32ms 一帧，比 analyze 的 HOP 细，切分要的是位置精度

# ===== 时长回填 =====

TRUNCATE_NOTE = "音频超过 3 分钟，仅解析了前 3 分钟"


# ===== 唱段切分（纯函数，不碰 redis / 不碰数据库，可单独调）=====

def _split_segments(y: np.ndarray, sr: int) -> list[dict]:
    """把 16k 单声道人声轨按停顿切成唱段，返回 [{seq, title, duration}]。

    四步（spec 4.3）：取有声区间 → 合并近邻 → 丢弃碎段 → 空结果回退成整条一段。

    最后那步回退是刻意的：任何输入都要有分段、都要能走到 `parsed` 终态。
    没有它，一段全静音的人声轨（分离失败、纯伴奏）会让 segments 一行不落，
    而前端还在轮询一个永远不会到来的 `parsed`。

    duration 只落时长、不落起止时间（第 2 节已定：不加 start_sec 列），
    所以前端只能显示「第 N 段 · 6.6s」，做不了「点击定位到该段」。
    """
    intervals = librosa.effects.split(
        y, top_db=TOP_DB, frame_length=FRAME_LENGTH, hop_length=HOP_LENGTH
    )
    merged = _merge_intervals(intervals, int(MIN_GAP_SEC * sr))
    kept = [(int(s), int(e)) for s, e in merged if (e - s) >= MIN_SEG_SEC * sr]
    if not kept:
        kept = [(0, len(y))]

    return [
        {"seq": i, "title": f"第 {i} 段", "duration": round((e - s) / sr, 3)}
        for i, (s, e) in enumerate(kept, start=1)
    ]


def _merge_intervals(intervals, min_gap: int) -> list[tuple[int, int]]:
    """把间隙小于 min_gap（单位：采样点）的相邻区间并成一段。

    intervals 是 librosa.effects.split 的产物，已按起点升序、互不相交，
    所以一趟线性扫描就够，不需要排序。
    """
    merged: list[tuple[int, int]] = []
    for start, end in intervals:
        if merged and start - merged[-1][1] < min_gap:
            merged[-1] = (merged[-1][0], int(end))
        else:
            merged.append((int(start), int(end)))
    return merged

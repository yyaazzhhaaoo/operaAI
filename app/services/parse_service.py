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
# 区间刻意对齐前端 renderParseFlow 的完成阈值「progress >= t + 15」——t 是前端每个
# 步骤自己的阈值，progress 到 t 时该步显示 🔄、到 t + 15 时变 ✅。三个阶段上报的
# 都是下界（20 / 50 / 80），效果是「上一步恰好变 ✅、本步变 🔄」，步骤条会一步步往下走。
#
# **但别指望所有步骤都亮成 ✅**：本管线只有这三次阶段上报（外加终态的 100），而最后
# 一步的阈值是 100、要 115 才变 ✅，它在整个任务生命周期里都不会变 ✅——终态一到前端
# 就切到结果视图，看不到那一步，不必为此补一次多余的上报。
#
# 上面这几个 STAGE_* 是**本层内部**的阶段名（写进 redis 的 stage 字段），不是前端步骤
# 条上的文案，两者不必逐字对应。前端步骤的条数与名称见 demo_library.html 的
# renderParseFlow，这里不复制那份清单，免得两处各写一份、改一处漏一处。
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
# TOP_DB 是「多低算静音」的阈值（dB，相对**峰值**帧），librosa.effects.split 的默认值是 60。
# 判据是 `db > -top_db`（见 librosa.effects._signal_to_frame_nonsilent），所以这个数
# **越小、被判成静音的帧越多、切出来的段越多**；越大越容易把相邻唱句并成一段。
#
# 取 30（比默认的 60 小）就是主动往「多判静音」这一侧压：比峰值低 30~60dB 的内容
# ——换气声、拖腔的尾音——会被判成静音，从而成为切分点。这正是「按停顿切段」要的，
# 停顿本来就包含换气。敢压这么低的前提是**输入已经过 Demucs 分离**：伴奏残留少、
# 噪声底低，压低阈值也不会把背景噪声误判成停顿。反过来若用默认的 60，换气会留在
# 「有声」一侧，相邻唱句会粘成一段。
#
# ⚠️ 30 是**未经真实素材标定**的初始值（本轮开发不含验证环节）。调参时只改这一个数。
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

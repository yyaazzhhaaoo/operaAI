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
import uuid
from pathlib import Path

import librosa
import numpy as np
from celery import shared_task
from sqlalchemy.orm import Session

from app.common import storage
from app.common.errors import BusinessError
from app.db import session_scope
from app.models.demo import TeacherDemo
from app.repositories import audio_repo
from app.repositories import library_repo
from app.repositories import parse_task_repo as task_repo
from app.services import vocal_service

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


# ===== 提交 =====

def submit(db: Session, demo: TeacherDemo) -> str:
    """上传之后建任务并投进 demucs 队列，立即返回 task_id。

    只收一个已经落库的 demo。**不在这里校验音频文件在不在磁盘上**——B 组
    （analyze_service.submit）会提前查，是因为它的失败要当场回 4xx 给用户；
    这条链路的形态是「上传返回 200 → 前端轮询」，文件丢失的合理表达是任务
    落成 error（前端弹「解析失败」），而不是上传接口报一个跟上传无关的错。
    """
    task_id = uuid.uuid4().hex[:12]
    task_repo.create(
        demo.id,
        status=STATUS_PARSING,
        progress=0,
        # 排队阶段没有对应的 stage（前端的第 1 步「音频上传」在提交前就完成了），
        # 留空而不是硬塞一个 STAGE_*，否则 stage 与 progress 会互相矛盾。
        stage="",
        message="任务已创建，排队中",
        # 不传 demo_id：create 的第一个位置参数就叫这个名字，重传会撞成
        # TypeError；记录里的那个字段由 create 从键参数写入（见其 docstring）。
        task_id=task_id,
    )
    _dispatch(demo.id, task_id)
    return task_id


def status(db: Session, demo_id: int) -> dict:
    """解析进度快照。redis 里有任务就用它的；没有则按 segments 派生。

    派生这条路径是为 TTL 过期（1 小时）之后兜底：否则详情页会在上传 1 小时后
    显示成「没解析过」，而库里明明躺着分段。派生只可能给出 parsed / unparsed
    两种，且**不带真实的进度**——已经没有任务在跑了，这里给的 0 / 100 只是
    让前端的进度条有个确定形状。一个例外：任务还排在 demucs 队列里（未开工）
    时并不会续期 redis 键，TTL 过期后它也会被派生成 unparsed（显示「尚未解析」）；
    这会自愈——任务一开工 update() 就重建 redis 键，分段落库后状态自然变回 parsed。

    demo 不存在时抛 404：这条接口是按 demo_id 查的，调用方拿一个不存在的 id
    来问，答案是「没有这条示范曲目」而不是「它没解析过」。
    """
    if library_repo.get_demo(db, demo_id) is None:
        raise BusinessError(404, "示范曲目不存在")

    task = task_repo.get(demo_id)
    if task is None:
        parsed = bool(library_repo.list_segments(db, demo_id))
        return {
            "status": STATUS_PARSED if parsed else STATUS_UNPARSED,
            "progress": 100 if parsed else 0,
            "stage": "",
            "message": "解析完成" if parsed else "尚未解析",
        }

    return {
        "status": task.get("status") or STATUS_UNPARSED,
        "progress": task.get("progress", 0),
        "stage": task.get("stage") or "",
        "message": task.get("message") or "",
    }


# ===== 内部：阶段上报 =====

def _enter_stage(demo_id: int, stage: str, message: str) -> None:
    """上报「进入某阶段」，供前端轮询。

    progress 取该阶段区间的**下界**，语义是「当前正在这个阶段」，
    理由与 analyze_service._enter_stage 相同（那边有完整推导）：
    用完整个区间会让进度条在阶段内部空转，下一个阶段才跳。

    写 redis 失败不在这里兜：任务状态写不进去是致命问题（前端将永远查不到
    这个任务），应该让异常冒到 run_parse 去记日志并落成 error。
    """
    task_repo.update(
        demo_id,
        status=STATUS_PARSING,
        progress=STAGE_RANGE[stage][0],
        stage=stage,
        message=message,
    )


# ===== 内部：入参解析 =====

def _require_demo(db: Session, demo_id: int) -> tuple[TeacherDemo, Path]:
    """取示范曲目并还原出磁盘路径，确认文件真的还在。

    库里登记过、磁盘上却没有，通常是被手工清过 uploads/ 或换了挂载点。
    这种要当 BusinessError 报出来（任务落 error 时 message 直接给用户看），
    而不是让后面 Demucs 抛一个读文件的原生异常。
    """
    demo = library_repo.get_demo(db, demo_id)
    if demo is None:
        raise BusinessError(404, f"示范曲目不存在（teacher_demos.id={demo_id}）")
    if demo.audio_id is None:
        raise BusinessError(400, "该示范曲目没有绑定音频，无法解析")

    audio = audio_repo.get_by_id(db, demo.audio_id)
    if audio is None:
        raise BusinessError(404, "示范曲目绑定的音频记录不存在")

    path = storage.resolve(audio.file_path)
    if not path.is_file():
        raise BusinessError(404, "音频文件已丢失")
    return demo, path


def _master_duration(path: Path) -> float | None:
    """音频文件的真实全长（秒）。多数格式只读元数据，不解码。

    走 librosa.get_duration(path=...)：它先试 soundfile 的 sf.info()，对
    wav/mp3/flac/ogg 只读文件头；soundfile 打不开的容器（m4a / aac / webm，
    都在 storage.ALLOWED_EXT 里）会回退到 audioread，那条路径经 ffmpeg 把整个
    文件解一遍（秒级到几十秒）。所以这里是「通常很便宜」而非「一定零成本」。

    读不出来返回 None 而不是 0.0：0 是个会写进 audio_files.duration_sec 的
    「合法」值，列表页会如实显示成 0.0 秒，等于用一个假数据掩盖了读取失败。
    返回 None 时调用方跳过回填，列保持 NULL（前端显示「—」）。

    这个值是**文件真实时长**，不是 MAX_AUDIO_SEC 截断后的长度——列表页显示的
    时长必须如实（spec 4.3），分段只覆盖前 3 分钟这件事由任务完成消息另行说明。
    """
    try:
        return float(librosa.get_duration(path=str(path)))
    except Exception:
        logger.exception("读取音频时长失败：%s", path)
        return None


# ===== 内部：后台执行（Celery）=====

def _dispatch(demo_id: int, task_id: str) -> None:
    """把解析任务投进 **demucs 队列**，立即返回。

    queue="demucs" 是必须的：一条解析占 8–15 分钟，与秒级的 B 组分析同队列
    会把 pitch_comparison.html 拖住。**代价是 worker 必须带 -Q demucs**，
    否则这个队列没人消费、解析永远停在 parsing（CLAUDE.md 与 app/worker.py
    两处都记了这个坑）。

    消息里只传 demo_id：路径、原有时长都由任务自己查库取，理由见模块文档。

    task_id 显式指定成我们自己的 id，不让 Celery 另生成一个——日志里两者对得上号。
    broker 连不上时这里会抛（kombu 的 OperationalError），由全局错误处理器转成
    500；此时 redis 里那条 parsing 记录没人会改，1 小时后随 TTL 过期，前端
    详情页会走 status() 的派生路径显示成 unparsed，不会卡在「解析中」。
    """
    run_parse.apply_async(args=(demo_id,), task_id=task_id, queue="demucs")


@shared_task(name="parse.run")
def run_parse(demo_id: int) -> None:
    """Celery 任务体，worker 进程里的入口。

    **任何异常都必须落成 error 状态**（与 analyze_service.run_analysis 同构）：
    任务抛出的异常若不在这里兜住，前端会一直轮询一个不会到终态的任务——比报错
    更难排查。Celery 自己也会记一份失败，但那份在 worker 日志里，前端看不到。
    """
    try:
        _parse(demo_id)
    except Exception as exc:
        logger.exception("示范库解析任务 %s 失败", demo_id)
        # 可以透给用户的两种文案：BusinessError 的 message 本来就是写给用户看的
        # （见 common/errors.py，全局 handler 也原样返回），NotImplementedError
        # 是开发期的占位说明。其余异常一概不泄漏内部细节——路径、连接串、
        # torch 的报错都不该出现在前端。
        if isinstance(exc, (BusinessError, NotImplementedError)):
            message = str(exc)
        else:
            message = "解析失败，请稍后重试"
        try:
            task_repo.update(demo_id, status=STATUS_ERROR, message=message)
        except Exception:
            # 连状态都写不进去（redis 挂了），只能记日志。**不能让异常逃逸**：
            # 逃出去 Celery 会把这条消息当失败重投，无限重试。
            logger.exception("解析任务 %s 的失败状态写入 redis 也失败了", demo_id)


def _parse(demo_id: int) -> None:
    """解析管线主体：人声分离 → 唱段切分 → 结果入库。

    跑在 worker 进程里，没有请求上下文，所以自己开 session_scope()，不走 get_db()。
    会话**分两段开、中间不留连接**：Demucs 要跑 8–15 分钟，攥着连接不放会把
    连接池（pool_size=5）白占一个。中间那段纯计算不碰数据库。
    """
    # --- 取路径（短会话）---
    with session_scope() as db:
        _, path = _require_demo(db, demo_id)

    # 时长在读文件头这一步拿，与后面的分离无关，先取好省得回填时再开一次会话
    duration = _master_duration(path)

    # --- 人声分离（8–15 分钟，进度停在 20%）---
    _enter_stage(demo_id, STAGE_SEPARATE, "正在分离人声，单条约需 8–15 分钟，请勿关闭页面…")
    y = vocal_service.separate_vocal(path)

    # --- 唱段切分（秒级，进度 50%）---
    _enter_stage(demo_id, STAGE_SEGMENT, "正在按停顿切分唱段…")
    segments = _split_segments(y, vocal_service.SR)

    # --- 结果入库（毫秒级，进度 80%）---
    _enter_stage(demo_id, STAGE_SAVE, "正在写入分段与时长…")
    with session_scope() as db:
        library_repo.replace_segments(db, demo_id, segments)
        if duration is not None:
            library_repo.update_audio_duration(db, demo_id, duration)

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

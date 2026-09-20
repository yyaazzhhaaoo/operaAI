# -*- coding: utf-8 -*-
"""B2–B4 分析任务的业务逻辑（《5-接口清单》3.1 协议 / 3.2 结果契约）。

异步模型：B2 建任务后立刻返回 task_id，真正的算法交给 Celery worker 在**另一个
进程**里跑（worker 入口是 app/worker.py），进度与结果落在 redis
（analyze_task_repo），B3/B4 只读。

本层不引用 flask.session / flask.request。Celery 任务更要注意这一点——它跑在
另一个进程里，请求上下文和数据库会话都不会跟过去，所以任务只收磁盘路径与纯数据、
只用 redis。逐字歌词就是这么传的：submit() 在请求内读出来，任务只收一个 list。

音高提取 / DTW / 评分的参考实现是 app-d.py 的 extract_pitch 与 /analyze
（过渡用的演示实现，B1–B5 落地后整块删除）。这里刻意照搬它的参数与公式而
不另起一套：那组阈值是拿真实录音调过的，另换一套既没有依据，也会让演示页
和 B4 的结果对不上。**但输出必须重新整形**——demo 返回 teacher/student/
aligned/score，与文档 3.2 的 overall/dimensions/timeline/regions/words 不同构。
"""

import logging
import math
import uuid
from dataclasses import dataclass
from pathlib import Path

import librosa
import numpy as np
from celery import shared_task
from fastdtw import fastdtw
from scipy.spatial.distance import euclidean
from sqlalchemy.orm import Session

from app.common import storage
from app.common.errors import BusinessError
from app.models.audio import AudioFile
from app.repositories import analyze_task_repo as task_repo
from app.repositories import audio_repo
from app.schemas.audio import AnalyzeSubmitIn

logger = logging.getLogger(__name__)

# 文档 3.1 规定的 stage 取值与进度区间。分析管线实现时必须落在这些取值上，
# 前端的进度条按 STAGE_RANGE 渲染。
#
# 六个阶段各起一个常量名，管线里不写字符串字面量：STAGES / STAGE_RANGE 都以
# 这些常量为键，写错一个名字会在 _enter_stage() 里当场 KeyError，而不是静默
# 变成一个前端认不出的阶段。
STAGE_UPLOAD = "上传完成"
STAGE_SEPARATE = "人声分离"
STAGE_PITCH = "音高提取"
STAGE_OCTAVE = "八度修正"
STAGE_ALIGN = "时间对齐"
STAGE_SCORE = "评分计算"
STAGES = [STAGE_UPLOAD, STAGE_SEPARATE, STAGE_PITCH, STAGE_OCTAVE, STAGE_ALIGN, STAGE_SCORE]
STAGE_RANGE = {
    STAGE_UPLOAD: (0, 5), STAGE_SEPARATE: (5, 20), STAGE_PITCH: (20, 55),
    STAGE_OCTAVE: (55, 70), STAGE_ALIGN: (70, 85), STAGE_SCORE: (85, 100),
}

# ===== 分析管线参数 =====
#
# 这套数值与 app-d.py 一致，演示页还在用同一批参数；要调就两边一起调。

SR = 16000                  # 统一重采样到 16k：pyin 在人声基频上够用，且比 44.1k 快一档
HOP = 1024                  # 帧移（16000 / 1024 ≈ 64ms 一帧）
FRAME_LENGTH = 2048
MAX_AUDIO_SEC = 180         # 只分析前 3 分钟：整出戏动辄十几分钟，全量跑不划算
MIN_FRAMES = 10             # 少于这么多帧算不出任何统计量，直接报错而不是产出一堆 nan
MIN_VOCAL_SEC = 1.0         # 裁掉开唱静音后至少要有这么长，否则退回整段

# 开唱点检测（_detect_onset）
IGNORE_FIRST_SEC = 0.5      # 开头这么久的信号一律不看：按键、呼吸、翻谱都在这里
ONSET_ENERGY_RATIO = 0.08   # 超过峰值能量这个比例才算「有声音」
ONSET_MIN_SUSTAIN_SEC = 0.2  # 且要连续持续这么久，单帧的爆破音不算

ALIGN_STEP = 5              # 精细 DTW 的取样步长（帧）。全帧对齐在 3 分钟音频上是
                            # 2800×2800 的代价矩阵，取样后降到 560，精度损失有限
OCTAVE_STEP = 10            # 八度扫描的步长，比精细对齐再粗一档（要跑 5 次）
OCTAVE_CANDIDATES = (-2, -1, 0, 1, 2)
OCTAVE_TOLERANCE = 400.0    # 逐字折八度的容差：中位偏差落在 1200±400 才认定是翻八度
DEFAULT_REF_HZ = 261.63     # 教师侧一个有效基频都没有时的兜底基准（中央 C）
MAX_TIMELINE_POINTS = 1500  # 时间轴抽稀上限，控制 redis 里 result 的体积

# 段落着色阈值，与文档 3.2 的前端着色规则一致：绿 <20 / 黄 20–50 / 红 >50
LEVEL_GREEN, LEVEL_YELLOW, LEVEL_RED = "green", "yellow", "red"
GREEN_MAX = 20.0
YELLOW_MAX = 50.0
REGION_WINDOW_SEC = 2.0     # 没有逐字数据时的滑窗长度
REGION_GAP_SEC = 0.3        # 合并相邻同色字的时间上限（字与字之间本就有停顿）


# ===== B2 提交 =====

def submit(db: Session, data: AnalyzeSubmitIn) -> str:
    """B2：解析出教师/学生两条音轨，建任务并投给 Celery，立即返回 task_id。"""
    student = _require_audio(db, data.student_audio_id, "学生录音")

    if data.teacher_audio_id is not None:
        teacher = _require_audio(db, data.teacher_audio_id, "教师示范")
        # 模式一直接比对两条音轨，没有歌词来源，逐字结果只能为空。
        lyrics = None
    else:
        teacher = audio_repo.get_segment_teacher_audio(db, data.segment_id)
        if teacher is None:
            raise BusinessError(404, "片段不存在或未绑定示范音频")
        # 逐字时间轴在 segments.lyrics_json 里。**在请求内读出来、以纯数据交给
        # 线程**——后台线程没有请求上下文，本模块的约定是线程里不碰数据库
        # （见模块文档）。歌词只是几十条 dict，随线程参数传走即可。
        segment = audio_repo.get_segment(db, data.segment_id)
        lyrics = segment.lyrics_json if segment else None

    # 文件在不在磁盘上要提前查：放进线程里再发现的话，响应已经返回 200，
    # 用户只能看到一个失败的任务，白等一轮轮询。
    t_path = _require_file(teacher)
    s_path = _require_file(student)

    task_id = uuid.uuid4().hex[:12]
    task_repo.create(
        task_id,
        status="queued",
        progress=0,
        stage=STAGE_UPLOAD,
        message="任务已创建，排队中",
        result=None,
    )
    _dispatch(task_id, t_path, s_path, lyrics)
    return task_id


# ===== B3 进度 / B4 结果 =====

def status(task_id: str) -> dict:
    """B3：进度快照（文档 3.1 第 2 步的响应体）。"""
    task = task_repo.get(task_id)
    if task is None:
        raise BusinessError(404, "任务不存在或已过期")
    return {
        "status": task.get("status"),
        "progress": task.get("progress", 0),
        "stage": task.get("stage"),
        "message": task.get("message"),
    }


def result(task_id: str) -> dict:
    """B4：完整结果（文档 3.2 契约）。

    未完成时回 409 而不是把半成品给出去——前端按 3.1 应当先轮询 B3，
    拿到 done 才调 B4；直接调到这里说明调用顺序错了。
    """
    task = task_repo.get(task_id)
    if task is None:
        raise BusinessError(404, "任务不存在或已过期")

    state = task.get("status")
    if state == "failed":
        raise BusinessError(409, task.get("message") or "分析失败")
    if state != "done":
        raise BusinessError(409, "任务尚未完成，请先轮询 /analyze/status")

    return task["result"]


# ===== 内部：入参解析 =====

def _require_audio(db: Session, audio_id: int, label: str) -> AudioFile:
    audio = audio_repo.get_by_id(db, audio_id)
    if audio is None:
        raise BusinessError(404, f"{label}不存在（audio_files.id={audio_id}）")
    return audio


def _require_file(audio: AudioFile) -> Path:
    """把登记记录还原成磁盘路径，并确认文件真的还在。

    库里登记过、磁盘上却没有，通常是被手工清过 uploads/ 或换了挂载点。
    这种要当 404 报出来，而不是让分析线程在后面炸成一个 500。
    """
    path = storage.resolve(audio.file_path)
    if not path.is_file():
        raise BusinessError(404, f"音频文件已丢失：{audio.file_path}")
    return path


# ===== 内部：后台执行（Celery） =====

def _dispatch(task_id: str, t_path: Path, s_path: Path, lyrics: list | None) -> None:
    """把分析任务投进 Celery 队列，立即返回。

    参数一律先转成纯数据：消息要序列化成 JSON 跨进程送给 worker，Path 不是
    JSON 类型，ORM 对象更是完全过不去——所以这里传的是路径字符串，而不是
    上面那几个 AudioFile。

    task_id 显式指定成我们自己的 id，不让 Celery 另生成一个：B3/B4 认的是 redis
    里 analyze:task:<id> 这个键，两套 id 并存只会让排查时对不上号。

    broker 连不上时这里会抛（kombu 的 OperationalError），由全局错误处理器
    转成 500。此时 redis 里那条 status=queued 的记录没人会去改，1 小时后随
    TTL 自然过期——比让前端拿着一个永远查不到终态的 task_id 干等要好。
    """
    run_analysis.apply_async(
        args=(task_id, str(t_path), str(s_path), lyrics),
        task_id=task_id,
    )


@shared_task(name="analyze.run")
def run_analysis(task_id: str, t_path: str, s_path: str, lyrics: list | None) -> None:
    """Celery 任务体，worker 进程里的入口。

    **任何异常都必须落成 failed 状态**。任务抛出的异常若不在这里兜住，任务会
    永远停在 queued，前端按 3.1 一直轮询也拿不到终态——比报错更难排查。文档 3.1
    也要求 failed 时 message 给用户可读原因。

    Celery 自己也会记一份失败，但那份在 worker 日志和 result backend 里，前端
    看不到；B3 只能读到下面写进 redis 的这一份。两边都要有，别只留一边。
    """
    try:
        _analyze(task_id, Path(t_path), Path(s_path), lyrics)
    except Exception as exc:
        logger.exception("分析任务 %s 失败", task_id)
        # 可以透给用户的两种文案：BusinessError 的 message 本来就是写给用户看的
        # （见 common/errors.py，全局 handler 也是原样返回），NotImplementedError
        # 是开发期的占位说明。其余异常一概不泄漏内部细节（与 500 的处理一致）——
        # 路径、连接串、numpy 的报错都不该出现在前端。
        if isinstance(exc, (BusinessError, NotImplementedError)):
            message = str(exc)
        else:
            message = "分析失败，请稍后重试"
        try:
            task_repo.update(task_id, status="failed", message=message)
        except Exception:
            # 连状态都写不进去（redis 挂了），只能记日志——此时已无路可退。
            logger.exception("分析任务 %s 的失败状态写入 redis 也失败了", task_id)


def _analyze(task_id: str, t_path: Path, s_path: Path, lyrics: list | None) -> None:
    """B2 的算法主体，按 3.2 契约产出结果。

    后五个阶段与文档 3.1 的 stage 取值一一对应，每进入一个上报一次进度
    （第一个「上传完成」由 submit() 建任务时上报）。任何一步失败都直接抛——
    run_analysis 会兜住并落成 failed。

    时间轴基准说明：比较的轴取**教师轨**。两条录音的绝对时长不同、开唱点也
    不同，DTW 对齐后学生帧被映射到教师帧上，于是 teacher_pitch / student_pitch /
    deviation_cents 三条曲线共用教师的时间栅格，前端拿去画图时天然对齐。
    代价是三者都是「相对教师开唱点」的时间，不是原始文件里的绝对秒数。
    """
    # --- 人声分离 ---
    _enter_stage(task_id, STAGE_SEPARATE, "正在分离人声…")
    t_vocal, t_onset = _load_vocal(t_path, "教师示范")
    s_vocal, s_onset = _load_vocal(s_path, "学生录音")
    logger.info("任务 %s：开唱点 教师 %.2fs / 学生 %.2fs", task_id, t_onset, s_onset)

    # --- 音高提取 ---
    _enter_stage(task_id, STAGE_PITCH, "正在提取音高曲线…")
    t_track = _extract_pitch(t_vocal, "教师示范")
    s_track = _extract_pitch(s_vocal, "学生录音")

    # --- 八度修正 ---
    _enter_stage(task_id, STAGE_OCTAVE, "正在校正八度…")
    # 基准取教师的中位基频：绝对音高对教学没有意义，要看的是学生相对教师
    # 偏了多少，所以 0 cents 定在教师那条曲线上。
    voiced = t_track.f0[t_track.f0 > 0]
    ref_hz = float(np.median(voiced)) if voiced.size else DEFAULT_REF_HZ

    t_cents = _hz_to_cents(t_track.f0, ref_hz)
    s_cents_raw = _hz_to_cents(s_track.f0, ref_hz)
    # 学生比教师低八度唱是常态（男女声、行当不同），不先拉齐的话 DTW 会把
    # 一个八度的系统性偏移算成满盘音准错误。
    octave_shift = _best_octave(t_cents, s_cents_raw)
    s_cents = s_cents_raw + octave_shift * 1200.0
    logger.info("任务 %s：基准 %.2fHz，八度偏移 %+d", task_id, ref_hz, octave_shift)

    # --- 时间对齐 ---
    _enter_stage(task_id, STAGE_ALIGN, "正在做时间对齐…")
    mapping = _align_frames(t_cents, s_cents)      # 教师每帧 → 学生帧号
    s_aligned = s_cents[mapping]

    # --- 评分计算 ---
    _enter_stage(task_id, STAGE_SCORE, "正在计算评分…")
    dimensions = _dimensions(t_cents, s_aligned, t_track, s_track, mapping)
    words = _words(lyrics, t_track.times, t_cents, s_aligned, ref_hz, t_onset)
    result = {
        # overall 是五个维度的均值：文档 3.2 的例子（80/85/78/84/86 → 82.5）
        # 与算术平均只差 0.1，看不出另有加权，这里就按等权处理。
        "overall": round(float(np.mean(list(dimensions.values()))), 1),
        "dimensions": dimensions,
        "timeline": _timeline(t_track.times, t_cents, s_aligned, ref_hz),
        # regions 由逐字结果合并而来（没有歌词时退回滑窗），所以必须在 words 之后。
        "regions": _regions(words, t_track.times, s_aligned - t_cents),
        "words": words,
    }

    task_repo.update(
        task_id,
        status="done",
        progress=100,
        stage=STAGE_SCORE,
        message="分析完成",
        result=result,
    )
    logger.info("任务 %s 完成：overall=%s dimensions=%s", task_id, result["overall"], dimensions)


def _enter_stage(task_id: str, stage: str, message: str) -> None:
    """上报「进入某阶段」，供 B3 轮询。

    progress 取该阶段区间的**下界**，语义是「当前正在这个阶段」；前端按
    STAGE_RANGE 渲染进度条即可，不必自己再映射。用完整个区间会让进度条
    在阶段内部空转（下一个阶段才跳），取下界则每个阶段都有一次可见的推进。

    写 redis 失败不在这里兜：任务状态写不进去是致命问题（B3 将永远查不到
    这个任务），应该让异常冒到 run_analysis 去记日志，而不是装作没事继续跑。
    """
    task_repo.update(
        task_id,
        status="processing",
        progress=STAGE_RANGE[stage][0],
        stage=stage,
        message=message,
    )


# ===== 内部：信号处理 =====
#
# 这一节只跟 numpy / librosa 打交道，不碰 redis、不碰数据库，可以单独调。
# 参数与 app-d.py 的 extract_pitch 一致，改动需同步（见模块文档）。


@dataclass
class _Track:
    """一条音轨的逐帧声学特征，四个数组等长同栅格。"""

    times: np.ndarray       # 帧时间（秒，相对本轨开唱点）
    f0: np.ndarray          # 基频 Hz
    rms: np.ndarray         # 均方根能量，反映气息
    centroid: np.ndarray    # 频谱质心 Hz，反映咬字


def _load_vocal(path: Path, label: str) -> tuple[np.ndarray, float]:
    """加载音频 → HPSS 取出谐波分量 → 裁掉开唱前的静音。

    返回 (人声信号, 开唱时间秒数)。开唱时间是相对**原始文件**的，后面把
    lyrics_json 的绝对起止时间换算到分析时间轴上要用到它。
    """
    y, _ = librosa.load(str(path), sr=SR, mono=True, duration=MAX_AUDIO_SEC)
    if y.size == 0:
        raise BusinessError(400, f"{label}是空音频，无法分析")

    # 戏曲录音里伴奏与唱腔同频段，HPSS 取谐波分量能把伴奏压掉一部分，
    # 让 pyin 少抓错基频。margin=4.0 比默认的 1.0 分得更狠。
    harmonic, _ = librosa.effects.hpss(y, margin=4.0)

    onset = _detect_onset(harmonic)
    start = int(onset * SR)
    vocal = harmonic[start:] if start < len(harmonic) else harmonic
    if len(vocal) < SR * MIN_VOCAL_SEC:
        # 裁过头了，说明起始点判错（比如整段都是人声、或开头有杂音）。
        # 退回整段——宁可多给一点静音，也不要拿不足 1 秒的信号去提音高。
        vocal, onset = harmonic, 0.0
    return vocal, onset


def _detect_onset(y: np.ndarray) -> float:
    """按短时能量找出真正开唱的时刻（秒）。

    开头 IGNORE_FIRST_SEC 秒直接跳过：那里是录音起手的按键声、呼吸声、翻谱声，
    能量往往比人声还大，不跳过就会把它们当成人声起点。
    """
    hop = HOP
    skip = int(IGNORE_FIRST_SEC * SR)
    y = y[skip:] if skip < len(y) else y
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    if len(rms) == 0:
        return IGNORE_FIRST_SEC

    peak = float(np.max(rms))
    if peak < 1e-6:
        return IGNORE_FIRST_SEC       # 整段近乎无声

    # 连续 min_sustain 秒里六成以上帧超过峰值能量的 8%，才算唱起来了；
    # 只看单帧会被一个爆破音骗过去。
    above = (rms / peak) > ONSET_ENERGY_RATIO
    min_frames = max(1, int(ONSET_MIN_SUSTAIN_SEC * SR / hop))
    for i in range(len(above) - min_frames + 1):
        if float(np.mean(above[i:i + min_frames])) > 0.6:
            return float(librosa.frames_to_time(i, sr=SR, hop_length=hop) + IGNORE_FIRST_SEC)

    hit = np.where(above)[0]
    if hit.size:
        return float(librosa.frames_to_time(hit[0], sr=SR, hop_length=hop) + IGNORE_FIRST_SEC)
    return IGNORE_FIRST_SEC


def _extract_pitch(vocal: np.ndarray, label: str) -> _Track:
    """pyin 提取基频，并算出 RMS 与频谱质心两条辅助特征。"""
    f0, _, _ = librosa.pyin(
        vocal,
        fmin=librosa.note_to_hz("C2"),
        fmax=librosa.note_to_hz("C7"),
        sr=SR,
        hop_length=HOP,
        frame_length=FRAME_LENGTH,
    )
    times = librosa.frames_to_time(np.arange(len(f0)), sr=SR, hop_length=HOP)

    voiced = ~np.isnan(f0)
    if len(f0) < MIN_FRAMES or voiced.sum() < MIN_FRAMES:
        # 台词、环境噪声这类无基频的录音会走到这里。当场报出来，比让它带着
        # 一堆 NaN 往下走、最后在前端显示成 0 分要好懂。
        raise BusinessError(400, f"{label}里没有检测到足够的人声，请确认录音内容")

    # pyin 对清音帧给 NaN，线性插值补上：这些帧夹在浊音之间，插值比丢弃
    # 更能保持曲线连续（丢弃会让后面的 DTW 把两段不该相连的曲线接起来）。
    filled = np.interp(np.arange(len(f0)), np.where(voiced)[0], f0[voiced])
    filled = _smooth(filled, window=9)

    rms = _smooth(_stretch(librosa.feature.rms(y=vocal, hop_length=HOP)[0], len(f0)), window=5)
    centroid = _smooth(
        _stretch(librosa.feature.spectral_centroid(y=vocal, sr=SR, hop_length=HOP)[0], len(f0)),
        window=5,
    )
    return _Track(times=times, f0=filled, rms=rms, centroid=centroid)


def _smooth(series: np.ndarray, window: int) -> np.ndarray:
    """滑动平均。pyin 逐帧的抖动会让「音高变化率」（拖腔维度）全是噪声。"""
    if len(series) < window:
        return series
    return np.convolve(series, np.ones(window) / window, mode="same")


def _stretch(series: np.ndarray, n: int) -> np.ndarray:
    """把长度 m 的特征序列线性重采样到 n 帧。

    librosa 各特征默认 frame_length 不同（rms 与 pyin 用的就不一样），帧数
    可能差一帧，插到同一栅格后才能逐帧相减。
    """
    if len(series) == n:
        return series
    if len(series) == 0:
        return np.zeros(n)
    return np.interp(np.arange(n), np.arange(len(series)), series)


def _hz_to_cents(hz: np.ndarray, ref_hz: float) -> np.ndarray:
    """Hz → 相对 ref_hz 的音分（半音 = 100 cents，八度 = 1200）。"""
    hz = np.asarray(hz, dtype=float)
    # 0 Hz 会让 log2 变成 -inf，整条曲线被一个 -inf 带崩（min/median 全废）。
    hz = np.where(hz <= 0, 1e-6, hz)
    return 1200.0 * np.log2(hz / ref_hz)


def _dtw_path(a_cents: np.ndarray, b_cents: np.ndarray, step: int, dist=euclidean):
    """对两条音分序列做 fastdtw，返回 [(a 取样序号, b 取样序号), ...]。"""
    a_points = [(float(c),) for c in a_cents[::step]]
    b_points = [(float(c),) for c in b_cents[::step]]
    _, path = fastdtw(a_points, b_points, dist=dist)
    return path


def _octave_distance(a, b) -> float:
    """两个音高点之间的距离，折叠到半个八度以内——翻八度不计代价。

    对齐必须用这个而不是原始音分差。用原始差的话，学生某一整句翻了八度
    （代价 1200），DTW 为了躲开这 1200，宁肯把那句错配到别的小节上去，
    于是时间对齐跟着一起塌——实测过：某一句低八度会让相邻几个字的对齐
    全部错位。折叠之后 DTW 只看旋律轮廓（往上还是往下、拐在哪里），
    翻不翻八度都能对得上，八度本身交给八度修正那一步单独处理。
    """
    d = abs(float(a[0]) - float(b[0]))
    return min(d % 1200.0, 1200.0 - (d % 1200.0))


def _best_octave(t_cents: np.ndarray, s_cents: np.ndarray) -> int:
    """在 ±2 个八度里挑一个让学生整体最贴教师的偏移。

    判据是 DTW 对齐后的平均绝对偏差——先按粗略步长各比一遍，谁小听谁的。
    注意这里**不能**把偏差折叠到半个八度，折叠之后所有候选的差距会被抹平。
    """
    best_shift, best_diff = 0, float("inf")
    for shift in OCTAVE_CANDIDATES:
        shifted = s_cents + shift * 1200.0
        path = _dtw_path(t_cents, shifted, OCTAVE_STEP)
        diffs = [
            abs(float(t_cents[i * OCTAVE_STEP]) - float(shifted[j * OCTAVE_STEP]))
            for i, j in path
        ]
        mean_diff = float(np.mean(diffs)) if diffs else float("inf")
        logger.debug("八度候选 %+d：平均偏差 %.1f cents", shift, mean_diff)
        if mean_diff < best_diff:
            best_shift, best_diff = shift, mean_diff
    return best_shift


def _align_frames(t_cents: np.ndarray, s_cents: np.ndarray) -> np.ndarray:
    """DTW 精细对齐，返回长度为 len(t_cents) 的数组：教师第 i 帧对应学生第几帧。

    直接拿 DTW 路径上的点当结果是不行的——路径是多对多的，同一教师帧可能
    出现好几次，而 3.2 要求三条曲线共用一个时间栅格、逐点对齐。所以这里
    把路径压成「教师帧 → 学生帧」的单调映射，再线性插值铺满教师全部的帧
    （DTW 只在每 ALIGN_STEP 帧上算过，中间那些帧得插出来）。
    """
    path = _dtw_path(t_cents, s_cents, ALIGN_STEP, dist=_octave_distance)
    t_idx = np.array([i * ALIGN_STEP for i, _ in path], dtype=float)
    s_idx = np.array([j * ALIGN_STEP for _, j in path], dtype=float)

    # 多对一的教师帧只保留第一次出现，让 xp 严格递增——np.interp 要求如此。
    uniq, first = np.unique(t_idx, return_index=True)
    if uniq.size < 2:
        # 音频短到只剩一个取样点（MIN_FRAMES 之下已经拦过，这里只是兜底）：
        # 整段当作对齐到同一个学生帧，好过抛异常让用户看到一个失败的任务。
        return np.zeros(len(t_cents), dtype=int)

    mapped = np.interp(np.arange(len(t_cents)), uniq, s_idx[first])
    return np.clip(np.round(mapped).astype(int), 0, len(s_cents) - 1)


# ===== 内部：结果整形（文档 3.2） =====


def _dimensions(
    t_cents: np.ndarray,
    s_cents: np.ndarray,
    t_track: _Track,
    s_track: _Track,
    mapping: np.ndarray,
) -> dict:
    """五个维度得分。

    每个维度都是「学生相对教师的某个统计量的离散程度」，再过一条 logistic
    压到 0–100：越离散分越低，正好落在阈值上得 50 分。阈值与公式照搬
    app-d.py，那组数是拿真实录音调出来的。
    """
    # 音准：逐帧偏差先折叠到半个八度以内再取中位数。折叠是刻意的——学生
    # 唱低八度不该算音准错，算的是「有没有唱在调上」而不是绝对高度。
    diffs = np.abs(t_cents - s_cents)
    folded = np.minimum(diffs % 1200.0, 1200.0 - (diffs % 1200.0))
    pitch = _pitch_score(float(np.median(folded))) if folded.size else 0.0

    # 节奏：对齐中时间轴被拉伸/压缩的幅度，标准差越大说明越跟不上拍
    rhythm = _logistic(float(np.std(s_track.times[mapping] - t_track.times)), mid=1.0, k=2.0)
    # 气息：能量曲线的形状差
    breath = _logistic(float(np.std(s_track.rms[mapping] - t_track.rms)), mid=0.10, k=20.0)
    # 咬字：频谱质心的平均差（Hz），越小说明共鸣位置越接近
    articulation = _logistic(
        float(np.mean(np.abs(s_track.centroid[mapping] - t_track.centroid))), mid=600.0, k=0.005
    )
    # 拖腔：音高变化率的差——滑音、拖腔处理得连不连贯看这个
    t_deriv = np.abs(np.diff(t_cents))
    s_deriv = np.abs(np.diff(s_cents))
    n = min(len(t_deriv), len(s_deriv))
    melisma = (
        _logistic(float(np.mean(np.abs(t_deriv[:n] - s_deriv[:n]))), mid=80.0, k=0.03)
        if n else 0.0
    )

    return {"音准": pitch, "节奏": rhythm, "气息": breath, "咬字": articulation, "拖腔": melisma}


def _pitch_score(median_diff: float) -> float:
    """音准分：按中位偏差分段给分（app-d.py 的曲线，段与段之间是连续的）。"""
    if median_diff < 10:
        score = 100.0
    elif median_diff < 30:
        score = 95 - (median_diff - 10) * 1.0
    elif median_diff < 50:
        score = 75 - (median_diff - 30) * 1.0
    elif median_diff < 100:
        score = 55 - (median_diff - 50) * 0.4
    else:
        score = max(0.0, 35 - (median_diff - 100) * 0.2)
    return round(float(score), 1)


def _logistic(x: float, mid: float, k: float) -> float:
    """100 / (1 + e^(k(x−mid)))：x 远小于 mid 趋近 100 分，远大于趋近 0 分。"""
    return round(float(100.0 / (1.0 + np.exp((x - mid) * k))), 1)


def _timeline(
    times: np.ndarray, t_cents: np.ndarray, s_cents: np.ndarray, ref_hz: float
) -> dict:
    """三条共用时间栅格的曲线（文档 3.2 的 timeline）。

    长度按 MAX_TIMELINE_POINTS 抽稀：3 分钟音频有约 2800 帧，原样塞进 redis
    的 result 里会让 B4 的响应无谓地大一圈，而 128ms 一个点的分辨率对画曲线
    完全够用。
    """
    stride = max(1, math.ceil(len(times) / MAX_TIMELINE_POINTS))
    idx = np.arange(0, len(times), stride)
    kept, t_kept, s_kept = times[idx], t_cents[idx], s_cents[idx]

    return {
        # duration 取共用栅格的末端，必须与三条曲线的时间范围一致——
        # 前端拿它画横轴，给大了右边会空一截。
        "duration": round(float(times[-1]), 3),
        "teacher_pitch": _pitch_pairs(kept, t_kept, ref_hz),
        "student_pitch": _pitch_pairs(kept, s_kept, ref_hz),
        "deviation_cents": [
            [round(float(t), 3), round(float(d), 2)] for t, d in zip(kept, s_kept - t_kept)
        ],
    }


def _pitch_pairs(times: np.ndarray, cents: np.ndarray, ref_hz: float) -> list[list[float]]:
    """音分 → [时间, Hz] 数对。

    特意从音分换算回 Hz 而不是直接透传 f0：这样 teacher_freq / student_freq /
    deviation_cents 三者严格自洽（1200·log2(s/t) 正好等于 deviation），
    前端拿任意两个算第三个都对得上。
    """
    hz = ref_hz * 2.0 ** (cents / 1200.0)
    return [[round(float(t), 3), round(float(f), 2)] for t, f in zip(times, hz)]


def _words(
    lyrics: list | None,
    times: np.ndarray,
    t_cents: np.ndarray,
    s_cents: np.ndarray,
    ref_hz: float,
    teacher_onset: float,
) -> list[dict]:
    """逐字偏差（文档 3.2 的 words）。

    lyrics_json 的 start/end 是相对**示范音频原始文件**的绝对时间，而音高轨道
    是从开唱点开始的时间轴（静音已裁掉），所以要减掉 teacher_onset 才能对上。

    输出里的 start/end 同样是分析时间轴的秒数，与 timeline / regions 一致——
    三者会被前端画在同一张图上，混用两套时间基准必然错位。
    """
    words: list[dict] = []
    span_end = float(times[-1])
    for idx, item in enumerate(lyrics or []):
        try:
            start = float(item["start"]) - teacher_onset
            end = float(item["end"]) - teacher_onset
        except (KeyError, TypeError, ValueError):
            logger.warning("lyrics_json 第 %d 条没有可用的 start/end，跳过：%r", idx, item)
            continue

        # 钳到时间轴范围内。种子数据里第一个字的 start 就是 0.0，减去开唱点
        # 之后是负数——原样回给前端，前端会把这段区间画到坐标轴左边去。
        start = max(start, 0.0)
        end = min(end, span_end)

        mask = (times >= start) & (times <= end)
        if not mask.any():
            # 这个字落在分析区间之外（示范录音被裁掉了这一段，或歌词时间轴
            # 与音频对不上）。**跳过而不是给 0 分**——0 偏差等于满分，会把
            # 一个没测到的字渲染成唱得很准。index 是显式给的，中间缺号前端能认。
            logger.debug("第 %d 个字（%s）没有对应的音频帧，跳过", idx, item.get("word"))
            continue

        t_med = float(np.median(t_cents[mask]))
        s_med = float(np.median(s_cents[mask]))
        diff = s_med - t_med

        # 整字差近一个八度：全局八度修正是拿整首歌拟合的，学生某一两句翻低
        # （或翻高）时它顾不过来，这里按字再折一次。容差外的不动——那更可能是
        # 真的唱跑调了，而不是八度问题。
        shift = math.copysign(1200.0, diff) if abs(abs(diff) - 1200.0) <= OCTAVE_TOLERANCE else 0.0
        deviation = diff - shift

        words.append({
            "index": idx,
            "word": item.get("word"),
            "start": round(start, 3),
            "end": round(end, 3),
            "deviation_cents": round(deviation, 1),
            "teacher_freq": round(ref_hz * 2.0 ** (t_med / 1200.0), 2),
            "student_freq": round(ref_hz * 2.0 ** ((s_med - shift) / 1200.0), 2),
            "octave_fixed": shift != 0.0,
            # 超过红色阈值就提醒：前端按同一套阈值着色，两处判断必须一致。
            "warning": abs(deviation) > YELLOW_MAX,
        })
    return words


def _regions(words: list[dict], times: np.ndarray, deviation: np.ndarray) -> list[dict]:
    """着色片段（文档 3.2 的 regions，前端按 level 上色）。

    有歌词时按字合并：相邻、同色、间隔不超过 REGION_GAP_SEC 的字并成一段。
    模式一（直接比对两条音轨）拿不到歌词，退回固定时长滑窗——无论走哪种
    模式，前端都得有着色区间可用。
    """
    if not words:
        return _regions_by_window(times, deviation)

    regions: list[dict] = []
    acc: list[list[float]] = []          # 与 regions 一一对应：[偏差加权和, 时长和]

    for w in words:
        level = _level(abs(w["deviation_cents"]))
        span = max(w["end"] - w["start"], 1e-6)
        same_run = (
            regions
            and regions[-1]["level"] == level
            and w["start"] - regions[-1]["end"] <= REGION_GAP_SEC
        )
        if same_run:
            regions[-1]["end"] = w["end"]
            acc[-1][0] += abs(w["deviation_cents"]) * span
            acc[-1][1] += span
        else:
            regions.append({"start": w["start"], "end": w["end"], "level": level})
            acc.append([abs(w["deviation_cents"]) * span, span])

    # 合并时按时长加权累计，最后再取平均：直接平均若干段的平均值，在两段
    # 时长差很多时会明显偏向短的那段。合并只在同 color 的字之间发生，
    # 所以平均结果必然还落在同一个色带里，level 不用重算。
    return [
        {"start": r["start"], "end": r["end"], "level": r["level"],
         "avg_cents": round(total / span, 1)}
        for r, (total, span) in zip(regions, acc)
    ]


def _regions_by_window(times: np.ndarray, deviation: np.ndarray) -> list[dict]:
    """没有逐字数据时的兜底：按固定时长滑窗，每窗给一个平均偏差。"""
    regions: list[dict] = []
    lo = float(times[0])
    end = float(times[-1])
    while lo < end:
        hi = min(lo + REGION_WINDOW_SEC, end)
        mask = (times >= lo) & (times < hi)
        if mask.any():
            avg = float(np.mean(np.abs(deviation[mask])))
            regions.append({
                "start": round(lo, 3),
                "end": round(hi, 3),
                "level": _level(avg),
                "avg_cents": round(avg, 1),
            })
        lo = hi
    return regions


def _level(avg_cents: float) -> str:
    """偏差幅度 → 色档。阈值同文档 3.2：绿 <20 / 黄 20–50 / 红 >50。"""
    if avg_cents < GREEN_MAX:
        return LEVEL_GREEN
    if avg_cents <= YELLOW_MAX:
        return LEVEL_YELLOW
    return LEVEL_RED

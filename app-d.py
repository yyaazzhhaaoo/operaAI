#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
戏曲音准对比演示 - 完整后端
仅需: pip install flask flask-cors librosa numpy scipy fastdtw
"""

import os
import uuid
import time
import threading
from flask import Blueprint, request, jsonify, send_from_directory, url_for
from flask_cors import CORS
import librosa
import numpy as np
from fastdtw import fastdtw
from scipy.spatial.distance import euclidean
from sqlalchemy import select

# 数据库接入层与业务蓝图。Flask 实例改由 create_app() 统一装配（配置、数据库
# teardown、错误 handler、业务蓝图都在那里），本文件不再自己 new 实例、也不再
# 手动注册 teardown——这些 create_app() 里已经做过了。
from app import create_app
from app.api import API_PREFIX
from app.db import get_db
from app.models.user import User
from app.response import ok

# ===== 应用装配 =====
app = create_app()

# pitch_comparison.html 从 file:// 打开时对后端的请求是跨源请求，CORS 必须保留，
# 删了音准对比演示当场失效。
CORS(app)

# ===== 演示蓝图 =====
# 下面 4 条路由（上传/音频/进度/分析）是过渡物，B1–B5 真正实现后连同本文件的
# librosa 代码整块删除。它们必须挂在自己的 demo_bp 上，不能挂业务蓝图：
# 业务蓝图在 create_app() 里就已经注册了，而 Flask 规定 register_blueprint()
# 之后不能再往该蓝图加路由（会抛 AssertionError）。另起一个蓝图后，
# 「先定义路由、再注册」的约束变成局部的——注册紧跟自己的路由定义，
# 不必追溯到远处的 create_app()。
#
# 前缀复用同一个 API_PREFIX 常量，不写字面量。
demo_bp = Blueprint("demo", __name__, url_prefix=API_PREFIX)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ===== 进度存储 =====
progress_store = {}
progress_lock = threading.Lock()


def update_progress(job_key, msg):
    """记录分析进度"""
    with progress_lock:
        if job_key not in progress_store:
            progress_store[job_key] = []
        progress_store[job_key].append({"time": time.time(), "msg": msg})
        if len(progress_store[job_key]) > 200:
            progress_store[job_key] = progress_store[job_key][-100:]


def clear_progress(job_key):
    """清理进度记录"""
    with progress_lock:
        progress_store.pop(job_key, None)


def smooth_series(data, window=9):
    data = np.array(data)
    if len(data) < window:
        return data.tolist()
    kernel = np.ones(window) / window
    return np.convolve(data, kernel, mode='same').tolist()


def detect_voice_onset(y, sr, hop_length=1024, energy_ratio=0.08, min_sustain=0.2, ignore_first_sec=0.5):
    skip_samples = int(ignore_first_sec * sr)
    if skip_samples >= len(y):
        skip_samples = 0
    y = y[skip_samples:]
    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    if len(rms) == 0:
        return float(ignore_first_sec)
    rms_max = np.max(rms)
    if rms_max < 1e-6:
        return float(ignore_first_sec)
    rms_norm = rms / rms_max
    threshold = energy_ratio
    above = rms_norm > threshold
    min_frames = int(min_sustain * sr / hop_length)
    for i in range(len(above) - min_frames + 1):
        if np.mean(above[i:i+min_frames]) > 0.6:
            onset_frame = i
            onset_time = librosa.frames_to_time(onset_frame, sr=sr, hop_length=hop_length)
            return float(onset_time + ignore_first_sec)
    first = np.where(above)[0]
    if len(first) > 0:
        t = librosa.frames_to_time(first[0], sr=sr, hop_length=hop_length)
        return float(t + ignore_first_sec)
    return float(ignore_first_sec)


def extract_pitch(path, sr=16000, hop_length=1024, job_key=None):
    filename = os.path.basename(path)
    if job_key:
        update_progress(job_key, f"正在加载音频: {filename}")
    y, sr = librosa.load(path, sr=sr, mono=True, duration=180)
    if job_key:
        update_progress(job_key, f"音频时长: {len(y)/sr:.1f}秒")
    
    # 1. HPSS 分离人声
    y_harmonic, _ = librosa.effects.hpss(y, margin=4.0)
    if job_key:
        update_progress(job_key, "HPSS 分离伴奏...")
    
    # 2. 检测人声起始点
    voice_start = detect_voice_onset(y_harmonic, sr, hop_length, ignore_first_sec=0.5)
    if job_key:
        update_progress(job_key, f"检测到人声起始: {voice_start:.2f}秒")
    
    start_sample = int(voice_start * sr)
    if start_sample < len(y_harmonic):
        y_vocal = y_harmonic[start_sample:]
    else:
        y_vocal = y_harmonic
        voice_start = 0.0
    if len(y_vocal) < sr * 1.0:
        if job_key:
            update_progress(job_key, "裁剪后过短，使用原音频")
        y_vocal = y_harmonic
        voice_start = 0.0

    # 3. 提取音高 (F0)
    if job_key:
        update_progress(job_key, "提取音高...")
    f0, _, _ = librosa.pyin(
        y_vocal,
        fmin=librosa.note_to_hz('C2'),
        fmax=librosa.note_to_hz('C7'),
        sr=sr,
        hop_length=hop_length,
        frame_length=2048
    )
    times = librosa.frames_to_time(np.arange(len(f0)), sr=sr, hop_length=hop_length)
    
    # 填充 NaN
    valid = ~np.isnan(f0)
    if valid.sum() > 2:
        f0_filled = np.interp(
            np.arange(len(f0)),
            np.where(valid)[0],
            f0[valid],
            left=f0[valid][0],
            right=f0[valid][-1]
        )
    else:
        f0_filled = np.zeros_like(f0)
    f0_filled = smooth_series(f0_filled, window=9)

    # ========== 🆕 4. 提取能量特征 (RMS) ==========
    # 计算均方根能量，反映气息
    rms = librosa.feature.rms(y=y_vocal, hop_length=hop_length)[0]
    # 将 RMS 插值到与 f0 相同的长度（因为帧数可能略有不同）
    rms_interp = np.interp(
        np.arange(len(f0)),
        np.linspace(0, len(rms) - 1, len(f0)),
        rms
    )
    rms_interp = smooth_series(rms_interp, window=5)

    # ========== 🆕 5. 提取频谱质心 (Spectral Centroid) ==========
    # 反映咬字清晰度
    sc = librosa.feature.spectral_centroid(y=y_vocal, sr=sr, hop_length=hop_length)[0]
    sc_interp = np.interp(
        np.arange(len(f0)),
        np.linspace(0, len(sc) - 1, len(f0)),
        sc
    )
    sc_interp = smooth_series(sc_interp, window=5)

    if job_key:
        update_progress(job_key, f"提取完成, 共 {len(f0_filled)} 帧")

    # 返回时增加 rms_interp 和 sc_interp
    return times.tolist(), f0_filled, float(voice_start), rms_interp, sc_interp


def hz_to_cents(hz_array, ref_hz):
    hz_array = np.array(hz_array)
    hz_array = np.where(hz_array <= 0, 1e-6, hz_array)
    return 1200 * np.log2(hz_array / ref_hz)


# ===== 路由 =====
#
# 演示路由挂的是上面定义的 demo_bp，不写 @app.route——/api 前缀只在
# app/api/__init__.py 的 API_PREFIX 常量里定义一次（这里由 demo_bp 复用），
# 一律写相对路径。前缀由应用自己认、不由 nginx 改写：nginx 只把 /api/ 放行
# 转发，这样「经 nginx 访问」和「直连 8877 调试」走的是同一套路径。
#
# 根路由 "/" 留在 Flask 实例上、不进蓝图——它不算接口：没有任何前端页面调用它，
# 它是 CLAUDE.md 记的「通过 app/ 包查 users 表」的数据库接入示例。
#
# 注意别和《5-接口清单》的业务接口混淆：B1 是 POST /api/audio/upload、
# 这里的是 POST /api/upload，两条路径不同、互不冲突，将来可并存。

@app.route("/")
def index():
    """直接访问根路径返回 index.html"""
    # return send_from_directory(".", "index.html")

    # 请求内取会话。同一个请求里多次调用 get_db() 拿到的是同一个 Session，
    # 不需要自己 commit/close——teardown 会收尾（只读查询本来也不用提交）。
    db = get_db()
    users = db.scalars(select(User).order_by(User.id)).all()

    # data 直接就是数据本身——数组、对象、单个值都行，不要在外面再包一层 {"users": ...}
    return ok([
        {
            "id": u.id,
            "username": u.username,
            "role": u.role,
            "display_name": u.display_name,
            "is_active": u.is_active,
        }
        for u in users
    ])

@demo_bp.route("/upload", methods=["POST"])
def upload():
    try:
        if "audio" not in request.files:
            return jsonify({"error": "no file"}), 400
        f = request.files["audio"]
        ext = os.path.splitext(f.filename)[1] or ".wav"
        uid = str(uuid.uuid4())[:8] + ext
        path = os.path.join(UPLOAD_DIR, uid)
        f.save(path)
        if not os.path.exists(path):
            raise Exception("文件保存后未找到")
        # 用 url_for 生成下载地址，而不是手写 "/api/audio/..."：
        # 前缀由蓝图的 url_prefix 带出来，将来改前缀这里不用跟着改。
        # 默认返回相对路径（/api/audio/xxx），前端拼 ${API}${j.url} 正好用。
        return jsonify({"id": uid, "url": url_for("demo.audio", filename=uid)})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@demo_bp.route("/audio/<path:filename>")
def audio(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@demo_bp.route("/progress")
def get_progress():
    job_key = request.args.get("job")
    if not job_key:
        return jsonify({"error": "需要 job 参数"}), 400
    with progress_lock:
        logs = list(progress_store.get(job_key, []))
    return jsonify({"logs": logs})


@demo_bp.route("/analyze")
def analyze():
    t_id = request.args.get("t")
    s_id = request.args.get("s")
    job_key = request.args.get("job") or f"{t_id}_{s_id}"

    if not t_id or not s_id:
        return jsonify({"error": "需要 t 和 s 参数"}), 400

    t_path = os.path.join(UPLOAD_DIR, t_id)
    s_path = os.path.join(UPLOAD_DIR, s_id)

    if not os.path.exists(t_path) or not os.path.exists(s_path):
        return jsonify({"error": "文件不存在"}), 404

    clear_progress(job_key)
    update_progress(job_key, f"开始分析: 老师={t_id}, 学生={s_id}")

    update_progress(job_key, "【老师】分析中...")
    t_times, t_f0, t_onset, t_rms, t_sc = extract_pitch(t_path, job_key=job_key)

    update_progress(job_key, "【学生】分析中...")
    s_times, s_f0, s_onset, s_rms, s_sc = extract_pitch(s_path, job_key=job_key)

    # 转为 numpy 数组方便计算
    t_f0_arr = np.array(t_f0)
    s_f0_arr = np.array(s_f0)
    t_rms_arr = np.array(t_rms)
    s_rms_arr = np.array(s_rms)
    t_sc_arr = np.array(t_sc)
    s_sc_arr = np.array(s_sc)

    ref_hz = float(np.median(t_f0_arr[t_f0_arr > 0]))
    if ref_hz <= 0 or np.isnan(ref_hz):
        ref_hz = 261.63

    t_cents = hz_to_cents(t_f0_arr, ref_hz).tolist()
    s_cents_original = hz_to_cents(s_f0_arr, ref_hz).tolist()

    # 八度归一化
    update_progress(job_key, "八度归一化...")
    best_octave = 0
    best_mean_diff = float('inf')
    t_pts_quick = [(i, t_cents[i]) for i in range(0, len(t_cents), 5)]

    for octave_shift in [-2, -1, 0, 1, 2]:
        offset = octave_shift * 1200
        s_shifted = [c + offset for c in s_cents_original]
        s_pts_quick = [(i, s_shifted[i]) for i in range(0, len(s_shifted), 5)]
        _, path = fastdtw(
            [(c,) for _, c in t_pts_quick],
            [(c,) for _, c in s_pts_quick],
            dist=euclidean
        )
        diffs = [abs(t_pts_quick[ti][1] - s_pts_quick[si][1]) for ti, si in path]
        mean_diff = np.mean(diffs)
        update_progress(job_key, f"  八度偏移 {octave_shift:+d} -> 平均偏差 {mean_diff:.1f} cents")
        if mean_diff < best_mean_diff:
            best_mean_diff = mean_diff
            best_octave = octave_shift

    s_cents = [c + best_octave * 1200 for c in s_cents_original]
    update_progress(job_key, f"选择最佳八度偏移: {best_octave:+d} 个八度")

    # DTW 精细对齐
    update_progress(job_key, "开始精细 DTW 对齐...")
    step = 5
    t_points = [(i, t_cents[i]) for i in range(0, len(t_cents), step)]
    s_points = [(i, s_cents[i]) for i in range(0, len(s_cents), step)]

    _, path = fastdtw(
        [(c,) for _, c in t_points],
        [(c,) for _, c in s_points],
        dist=euclidean
    )
    update_progress(job_key, f"DTW 完成, 对齐点: {len(path)}")

    aligned = []
    for ti, si in path:
        t_idx, t_c = t_points[ti]
        s_idx, s_c = s_points[si]
        diff = abs(t_c - s_c)
        aligned.append({
            "t_time": t_times[t_idx],
            "s_time": s_times[s_idx],
            "t_cents": float(t_c),
            "s_cents": float(s_c),
            "diff": float(diff),
            "t_f0": float(t_f0_arr[t_idx]),
            "s_f0": float(s_f0_arr[s_idx]),
            # 🆕 保存能量和频谱特征
            "t_rms": float(t_rms_arr[t_idx]),
            "s_rms": float(s_rms_arr[s_idx]),
            "t_sc": float(t_sc_arr[t_idx]),
            "s_sc": float(s_sc_arr[s_idx])
        })
    
    # ===== 评分计算（必须放在维度计算之前） =====
    diffs = [a["diff"] for a in aligned]
    folded_diffs = [min(d % 1200, 1200 - (d % 1200)) for d in diffs]
    median_diff = float(np.median(folded_diffs))

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

    update_progress(job_key, f"评分: {score:.1f} 分")
    
    # ===== 3. 🆕 基于实际特征计算维度得分 =====
    
    # 3.1 节奏得分：基于时间差的标准差
    time_diffs = [a["s_time"] - a["t_time"] for a in aligned]
    rhythm_std = np.std(time_diffs)
    # 假设标准差 0.05秒以内为满分，0.5秒为0分（系数20）/ 改进：使用 Sigmoid 式归一化，使得 0.05秒以内接近满分，0.3秒以上接近0分
    # rhythm_score = max(0, min(100, 100 - rhythm_std * 20))
    rhythm_score = 100 / (1 + np.exp((rhythm_std - 1.0) * 2.0))
    rhythm_score = round(float(rhythm_score), 1)
    
    # 3.2 气息得分：基于 RMS 能量差值的标准差 RMS 通常在 0~1 之间，0.05 以内算优秀
    rms_diffs = [a["s_rms"] - a["t_rms"] for a in aligned]
    rms_std = np.std(rms_diffs)
    # 归一化处理，假设能量差 0.1 以内为满分（系数 200）
    breath_score = 100 / (1 + np.exp((rms_std - 0.10) * 20))
    breath_score = round(float(breath_score), 1)

    # 3.3 咬字得分：基于频谱质心差值的均值
    sc_diffs = [abs(a["s_sc"] - a["t_sc"]) for a in aligned]
    sc_mean_diff = np.mean(sc_diffs)
    # 频谱质心单位是 Hz，200Hz以内算优秀
    articulation_score = 100 / (1 + np.exp((sc_mean_diff - 600) * 0.005))
    articulation_score = round(float(articulation_score), 1)

    # 3.4 拖腔得分：基于音高变化率（导数）的差值
    # 注：导数数组长度比原始少1，需要对齐处理
    t_cents_arr = np.array([a["t_cents"] for a in aligned])
    s_cents_arr = np.array([a["s_cents"] for a in aligned])
    t_deriv = np.abs(np.diff(t_cents_arr))
    s_deriv = np.abs(np.diff(s_cents_arr))
    # 截取相同长度
    min_len = min(len(t_deriv), len(s_deriv))
    deriv_diff = np.mean(np.abs(t_deriv[:min_len] - s_deriv[:min_len]))
    # 导数差 15 cents/帧以内算优秀
    melisma_score = 100 / (1 + np.exp((deriv_diff - 80) * 0.03))
    melisma_score = round(float(melisma_score), 1)

    # 音准得分复用之前的评分
    pitch_score = round(float(score), 1)
    
    # ===== 调试：打印各维度的原始特征值 =====
    print(f"[调试] 节奏特征: rhythm_std = {rhythm_std:.3f} -> 得分: {rhythm_score:.1f}")
    print(f"[调试] 气息特征: rms_std = {rms_std:.3f} -> 得分: {breath_score:.1f}")
    print(f"[调试] 咬字特征: sc_mean_diff = {sc_mean_diff:.1} -> 得分: {articulation_score:.1f}")
    print(f"[调试] 拖腔特征: deriv_diff = {deriv_diff:.1f} -> 得分: {melisma_score:.1f}")
        
    # 组装维度字典（使用真实计算值）
    dimensions = {
        "音准": pitch_score,
        "节奏": round(rhythm_score, 1),
        "气息": round(breath_score, 1),
        "咬字": round(articulation_score, 1),
        "拖腔": round(melisma_score, 1)
    }
    
    update_progress(job_key, f"维度评分: {dimensions}")

    update_progress(job_key, f"分析完成！老师开唱: {t_onset:.2f}s, 学生开唱: {s_onset:.2f}s")

    return jsonify({
        "teacher": {"times": t_times, "cents": t_cents, "f0": t_f0},
        "student": {"times": s_times, "cents": s_cents, "f0": s_f0},
        "aligned": aligned,
        "score": round(float(score), 1),
        "dimensions": dimensions,
        "ref_hz": round(ref_hz, 2),
        "teacher_onset": t_onset,
        "student_onset": s_onset,
        "octave_shift": best_octave
    })


# demo_bp 必须在上面所有 @demo_bp.route 之后再注册。
# Blueprint.route() 并不当场注册路由，只是把注册动作记进 deferred_functions，
# 等 register_blueprint() 时才真正执行。反过来写（先 register、后定义路由）
# 会当场抛 AssertionError（Flask 3.1.3 实测）：
#   "The setup method 'route' can no longer be called on the blueprint 'demo'"
# 紧跟自己的路由定义放，是为了让这个顺序局部可见。
app.register_blueprint(demo_bp)


if __name__ == "__main__":
    print("=" * 50)
    print("戏曲音准对比演示服务器已启动")
    print("访问: http://localhost:8877")
    print("=" * 50)
    app.run(host="0.0.0.0", port=8877, debug=True, threaded=True)
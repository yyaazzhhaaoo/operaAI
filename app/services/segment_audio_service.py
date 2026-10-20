# -*- coding: utf-8 -*-
"""把示范整曲按分段边界切成每段一个音频（spec 2026-10-20）。

两步分工：slice_files 只碰文件系统，attach 只碰数据库。Celery worker 里
两步之间必须关掉会话——解码写盘 1–3 秒，攥着连接会把连接池白占一个。
"""

import io
import logging
from pathlib import Path

import librosa
import soundfile as sf
from sqlalchemy.orm import Session

from app.common import storage
from app.models.demo import Segment
from app.repositories import audio_repo

logger = logging.getLogger(__name__)

# 与 analyze_service 采同样的口径：分析链路就按 16k 单声道读参考轨，
# 切出来的段直接喂进去不用再重采样
SR = 16000
ACCESS_PUBLIC = "public"


def slice_files(
    source_path: Path, bounds: list[tuple[int, float, float]]
) -> list[dict]:
    """按 [(seq, start_sec, end_sec)] 切整曲，返回
    [{seq, file_path, file_size, duration_sec}]。

    切的是**原始整曲**（含伴奏），不是 Demucs 分离出的人声：分析侧本来就对
    输入做 HPSS 压伴奏，换成人声轨会改变现有分析口径。
    """
    usable = [(seq, float(s), float(e)) for seq, s, e in bounds if e > s]
    if not usable:
        return []

    limit = max(e for _, _, e in usable) + 1.0
    y, _ = librosa.load(str(source_path), sr=SR, mono=True, duration=limit)

    slices: list[dict] = []
    for seq, start, end in usable:
        chunk = y[int(start * SR):int(end * SR)]
        if chunk.size == 0:
            continue
        buf = io.BytesIO()
        sf.write(buf, chunk, SR, format="WAV", subtype="PCM_16")
        stored_path, size = storage.save_bytes(buf.getvalue(), subdir="segments")
        slices.append({
            "seq": seq,
            "file_path": stored_path,
            "file_size": size,
            "duration_sec": round(chunk.size / SR, 3),
        })
    return slices


def attach(
    db: Session,
    *,
    demo_title: str,
    uploader_id: int | None,
    slices: list[dict],
    segments: list[Segment],
) -> None:
    """给每份切片登记 audio_files，并挂到同 seq 的分段上。只 flush，不 commit。

    segments 必须是本次刚插入的那批（replace_segments 的返回值）——按 seq
    而不是 id 关联，调用方拿不到自增 id 的顺序保证。
    """
    by_seq = {s.seq: s for s in segments}
    for item in slices:
        segment = by_seq.get(item["seq"])
        if segment is None:
            continue
        audio = audio_repo.create(
            db,
            uploader_id=uploader_id,
            file_path=item["file_path"],
            original_name=f"{demo_title}_第{item['seq']}段.wav",
            file_size=item["file_size"],
            access=ACCESS_PUBLIC,
        )
        audio.duration_sec = item["duration_sec"]
        segment.audio_id = audio.id
    db.flush()

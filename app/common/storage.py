# -*- coding: utf-8 -*-
"""音频落盘的唯一入口。

落盘根目录由 settings.upload_dir 决定（默认项目根的 uploads/，《5-接口清单》B1）。

**库里 audio_files.file_path 只存文件名，不存绝对路径**：这样数据库与部署
环境解耦（换机器、换挂载点不用改数据），也不会把服务器目录结构泄漏到接口
响应里。要拿磁盘路径一律走 resolve()，它顺带挡住路径穿越。

本模块只碰文件系统，不碰数据库、不碰请求上下文。
"""

import uuid
from pathlib import Path

from werkzeug.datastructures import FileStorage

from app.common.errors import BusinessError
from app.config import settings

# 与 librosa/soundfile 能解的格式对齐（部署手册 2.3 的 libsndfile1 + ffmpeg）。
# 白名单而非黑名单：不认识的扩展名一律拒，避免把 .php 之类的文件写进静态目录。
ALLOWED_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".webm"}


def save(file: FileStorage) -> tuple[str, int]:
    """把上传流落盘，返回 (存储文件名, 字节数)。

    存储名用 uuid 重新生成，不沿用客户端文件名——客户端文件名既可能重名，
    也可能带 ../ 或控制字符。原始名另存在 audio_files.original_name 里备查。
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise BusinessError(400, f"不支持的音频格式：{ext or '未知'}")

    stored_name = f"{uuid.uuid4().hex}{ext}"
    dest = settings.upload_dir / stored_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    file.save(dest)

    size = dest.stat().st_size
    if size == 0:
        # 空文件多半是前端录音没拿到数据就提交了。留着会在分析阶段
        # 变成一个更难懂的错误，这里直接拒掉并清理。
        dest.unlink(missing_ok=True)
        raise BusinessError(400, "上传的文件为空")

    return stored_name, size


def resolve(stored_name: str) -> Path:
    """存储文件名 → 磁盘绝对路径，并确保没有跑出 uploads/ 之外。

    file_path 虽然由本模块生成、理论上干净，但它是从数据库读回来的——
    手工改库或历史脏数据都可能让 ../ 混进来，所以在取用处再挡一道。
    """
    root = settings.upload_dir.resolve()
    path = (root / stored_name).resolve()
    if path.parent != root:
        raise BusinessError(400, "非法的音频文件名")
    return path

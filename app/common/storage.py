# -*- coding: utf-8 -*-
"""音频落盘的唯一入口。

落盘根目录由 settings.upload_dir 决定（默认项目根的 uploads/，《5-接口清单》B1）。

**库里 audio_files.file_path 只存相对 uploads/ 的路径，不存绝对路径**：
可以带一层目录（示范音频是 demos/<uuid>.wav）。这样数据库与部署
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


def save(file: FileStorage, *, subdir: str | None = None) -> tuple[str, int]:
    """把上传流落盘，返回 (存储路径, 字节数)。

    存储名用 uuid 重新生成，不沿用客户端文件名——客户端文件名既可能重名，
    也可能带 ../ 或控制字符。原始名另存在 audio_files.original_name 里备查。

    subdir 是相对 uploads/ 的子目录：示范库音频传 "demos"，学生录音不传。
    **由调用方显式给，不从 access 之类的字段推导**——access 在接口层是客户端
    可控的，拿它选目录会在「教师上传示范但没显式传 public」时把示范音频落进
    学生录音目录（DOC_ISSUES 第 40 条）。

    返回值即写进 audio_files.file_path 的值，形如 "demos/<hex>.wav" 或
    "<hex>.wav"——相对 uploads/、不带 uploads/ 前缀，与列约定一致（见
    schema.sql）。
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise BusinessError(400, f"不支持的音频格式：{ext or '未知'}")

    root = settings.upload_dir.resolve()
    dest_dir = (root / subdir).resolve() if subdir else root
    # subdir 目前只由本仓库的代码常量传入，理论上干净；但判定与 resolve() 同源，
    # 一并挡住，免得将来有人把它接到请求参数上
    if dest_dir != root and root not in dest_dir.parents:
        raise BusinessError(400, "非法的存储子目录")

    stored_name = f"{uuid.uuid4().hex}{ext}"
    dest = dest_dir / stored_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    file.save(dest)

    size = dest.stat().st_size
    if size == 0:
        # 空文件多半是前端录音没拿到数据就提交了。留着会在分析阶段
        # 变成一个更难懂的错误，这里直接拒掉并清理。
        dest.unlink(missing_ok=True)
        raise BusinessError(400, "上传的文件为空")

    return dest.relative_to(root).as_posix(), size


def resolve(stored_name: str) -> Path:
    """存储路径 → 磁盘绝对路径，并确保没有跑出 uploads/ 之外。

    stored_name 是 audio_files.file_path 的值：**相对 uploads/ 的路径**，
    可以带一层目录（如 demos/<uuid>.wav），但不含 uploads/ 前缀。

    file_path 虽然由 save() 生成、理论上干净，但它是从数据库读回来的——
    手工改库或历史脏数据都可能让 ../ 混进来，所以在取用处再挡一道。

    守卫判「root 必须是 path 的祖先」而不是「父目录正好是 root」：后者会把
    uploads/demos/ 这类子目录一并拒掉（DOC_ISSUES 第 40 条）。放宽的是深度，
    不是边界——下面的 .resolve() 会跟随软链，祖先判定因此同时挡住 ../ 逃逸
    与指向 root 之外的软链。**两者缺一不可，别删任何一个。**
    """
    root = settings.upload_dir.resolve()
    path = (root / stored_name).resolve()
    if root not in path.parents:
        raise BusinessError(400, "非法的音频文件名")
    return path

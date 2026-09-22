# -*- coding: utf-8 -*-
"""B 组音频接口的业务逻辑（《5-接口清单》B1、B5）。

本层不引用 flask.session / flask.request——会话读写只在 api/ 层发生，
所以这里的函数脱离请求上下文也能直接调用测试。

事务边界在本层：写操作显式 commit。
"""

from pathlib import Path

from sqlalchemy.orm import Session
from werkzeug.datastructures import FileStorage

from app.common import storage
from app.common.errors import BusinessError
from app.models.audio import AudioFile
from app.repositories import audio_repo

# 与 audio_files.access 列的取值域对齐（VARCHAR(10)）
ACCESS_PUBLIC = "public"
ACCESS_PRIVATE = "private"


def save_upload(
    db: Session,
    *,
    uploader_id: int,
    is_teacher: bool,
    access: str,
    file: FileStorage,
    commit: bool = True,
) -> AudioFile:
    """B1：落盘 + 写 audio_files 登记，返回记录。

    access 默认 private（学生录音）。public 是示范音频、所有登录用户可听，
    因此只允许教师设置——否则学生把自己的录音标成 public，就绕过了
    《6-登录与数据隔离方案》定的可听范围。

    commit=False 时只 flush（audio.id 已经能拿到，audio_repo.create 内部
    就是 flush），把提交交给调用方。示范曲目上传要走这条路：它紧接着还要建
    teacher_demos 一行，两行必须同生共死，而这个接口里只能有一次 commit。

    注意落盘在 flush 之前：回滚能撤掉 audio_files 那行，但撤不掉磁盘上已经
    写好的文件（见 common/storage.py 的 save）。调用方不必为此补偿——留下
    的是一个没有任何记录指向的孤儿文件，不会造成数据不一致。
    """
    if access not in (ACCESS_PUBLIC, ACCESS_PRIVATE):
        raise BusinessError(400, "access 只能是 public 或 private")
    if access == ACCESS_PUBLIC and not is_teacher:
        raise BusinessError(403, "只有教师可以上传公开示范音频")

    stored_name, size = storage.save(file)

    audio = audio_repo.create(
        db,
        uploader_id=uploader_id,
        file_path=stored_name,
        original_name=file.filename,
        file_size=size,
        access=access,
    )
    if commit:
        db.commit()
    return audio


def get_playable(
    db: Session,
    *,
    file_id: int,
    user_id: int,
    is_teacher: bool,
) -> tuple[Path, AudioFile]:
    """B5：按 access 规则判定可听，返回 (磁盘绝对路径, 登记记录)。

    《6-登录与数据隔离方案》第 4 节第 2 条：access=public（示范音频）所有
    登录用户可听；access=private（学生录音）仅上传者本人与教师可听。

    判定顺序是「记录存在 → 有无权限 → 文件还在不在」。文件存在性刻意放在
    权限之后：否则无权者能靠 404/403 的差别反推某个 id 对应的文件在不在。

    路径由本层解析（storage.resolve），api 层只拿到一个现成的 Path，不必
    碰 file_path 与 storage——那属于文件系统细节，不属于「组装响应」。
    """
    audio = audio_repo.get_by_id(db, file_id)
    if audio is None:
        raise BusinessError(404, "音频不存在")

    # access 列可空（历史脏数据），只有明确 public 才放开；uploader_id 也可空，
    # 为 None 时除教师外无人可听。取不到一律按 private 处理，宁可拒。
    if audio.access != ACCESS_PUBLIC:
        is_owner = audio.uploader_id is not None and audio.uploader_id == user_id
        if not (is_owner or is_teacher):
            raise BusinessError(403, "无权访问该音频")

    path = storage.resolve(audio.file_path)  # 内含路径穿越防护，非法即抛 400
    if not path.is_file():
        raise BusinessError(404, "音频文件已丢失")
    return path, audio

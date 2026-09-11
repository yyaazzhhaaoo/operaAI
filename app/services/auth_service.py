# -*- coding: utf-8 -*-
"""A 组认证接口的业务逻辑。

本层不引用 flask.session / flask.request——会话读写只在 api/ 层发生，
所以这里的函数脱离请求上下文也能直接调用测试。

事务边界在本层：写操作显式 commit（理由见 CLAUDE.md）。
仓储层只 flush，提交失败要在这里冒泡，不能在响应发出后才炸。
"""

from sqlalchemy.orm import Session

from app.common.errors import BusinessError
from app.common.security import hash_password, verify_password
from app.models.user import User
from app.repositories import user_repo


def login(db: Session, username: str, password: str) -> User:
    """校验用户名密码，返回用户。

    用户不存在与密码错误返回同一句文案，不泄漏账号是否存在。
    """
    user = user_repo.get_by_username(db, username)
    if user is None or not verify_password(user.password_hash, password):
        raise BusinessError(401, "用户名或密码错误")
    if not user.is_active:
        raise BusinessError(403, "账号已停用")
    return user


def get_user(db: Session, user_id: int) -> User:
    """按 id 取用户，供 A3/A4 从会话里的 user_id 反查。

    查不到说明账号已被删——对前端而言等价于登录失效。
    """
    user = user_repo.get_by_id(db, user_id)
    if user is None:
        raise BusinessError(401, "登录状态已失效")
    return user


def change_password(db: Session, user: User, old: str, new: str) -> None:
    """改密码。先验原密码，成功后写库并提交。"""
    if not verify_password(user.password_hash, old):
        raise BusinessError(401, "原密码不正确")
    user_repo.update_password(db, user, hash_password(new))
    db.commit()

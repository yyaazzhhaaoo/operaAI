# -*- coding: utf-8 -*-
"""A 组认证接口的入参/出参模型。

pydantic 已由 pydantic-settings 传递引入（2.13.5），零新增依赖。
校验失败抛 ValidationError，由 app/common/errors.py 的 handler 转成 422 中文文案。
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginIn(BaseModel):
    """A1 入参。上限对齐 users 表的列宽：username VARCHAR(50)。"""

    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class PasswordChangeIn(BaseModel):
    """A4 入参。

    《5-接口清单》未规定新密码强度，本项目取最短 8 位、且不得与旧密码相同
    （DOC_ISSUES.md 第 11 条）。
    """

    old: str = Field(min_length=1, max_length=128)
    new: str = Field(min_length=8, max_length=128)

    @field_validator("new")
    @classmethod
    def _not_same_as_old(cls, v, info):
        # old 声明在前，此处 info.data 里必定已有它
        if info.data.get("old") == v:
            raise ValueError("新密码不能与旧密码相同")
        return v


class UserOut(BaseModel):
    """A1 / A3 共用的出参。

    from_attributes=True 让它能直接吃 ORM 的 User 对象；
    字段是白名单，password_hash 不在其中，不可能被带出去。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    role: str

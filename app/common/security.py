# -*- coding: utf-8 -*-
"""密码哈希。

哈希算法只在这里指定一次，避免第二处再踩 werkzeug 3.x 的默认值变更
（DOC_ISSUES.md 第 8 条）。
"""

from werkzeug.security import check_password_hash, generate_password_hash

# 必须显式指定：werkzeug 3.x 的 generate_password_hash 默认算法已由 pbkdf2
# 改为 scrypt，输出 162 字符，超出 users.password_hash 的 VARCHAR(128)，
# 插入时报 "value too long"。pbkdf2:sha256 输出 103 字符。
# 《6-登录与数据隔离方案》要求的也正是 pbkdf2。
HASH_METHOD = "pbkdf2:sha256"


def hash_password(plain: str) -> str:
    """生成密码哈希（自带随机盐）。"""
    return generate_password_hash(plain, method=HASH_METHOD)


def verify_password(password_hash: str, plain: str) -> bool:
    """校验明文是否匹配哈希。

    算法与轮数从 password_hash 自身解析，所以 seed.sql 里既有的哈希
    （pbkdf2:sha256:1000000$...）无需特殊处理也能校验通过。
    """
    return check_password_hash(password_hash, plain)

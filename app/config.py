from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（app/ 的上一级）。用绝对路径，保证从任意工作目录启动都能读到 .env
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    database_url: str

    # Flask 会话签名密钥。刻意不给默认值——缺了它签名可被伪造，
    # 宁可启动即报错，也不要静默用一个空密钥跑起来。
    secret_key: str

    # 会话 Cookie 的 Secure 属性。默认 False 是刻意的：本地 nginx 走 HTTP，
    # 置 True 后浏览器会静默丢弃 Cookie，表现为「登录返回成功、之后每个请求都 401」，
    # 排查起来很绕。生产上 HTTPS 就绪后在 .env 加 SESSION_COOKIE_SECURE=true。
    session_cookie_secure: bool = False


settings = Settings()

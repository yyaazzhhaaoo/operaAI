from pathlib import Path
from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（app/ 的上一级）。用绝对路径，保证从任意工作目录启动都能读到 .env
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    database_url: str

    # Flask 会话签名密钥。刻意不给默认值——缺了它签名可被伪造，
    # 宁可启动即报错，也不要静默用一个空密钥跑起来。
    secret_key: str

    # 音频落盘根目录（《5-接口清单》B1：落盘 uploads/）。
    # 默认项目根的 uploads/，与 app-d.py 演示上传用的是同一个目录——两边
    # 曾经各写一份常量、各指一个地方，B2 因此在错误的目录里找文件而恒报 404。
    # 部署时可改 .env 的 UPLOAD_DIR 指向数据盘。
    upload_dir: Path = BASE_DIR / "uploads"

    # 会话 Cookie 的 Secure 属性。默认 False 是刻意的：本地 nginx 走 HTTP，
    # 置 True 后浏览器会静默丢弃 Cookie，表现为「登录返回成功、之后每个请求都 401」，
    # 排查起来很绕。生产上 HTTPS 就绪后在 .env 加 SESSION_COOKIE_SECURE=true。
    session_cookie_secure: bool = False

    # --- Redis ---
    # Celery 的 broker 与任务状态共用一台实例，但**刻意分库**：broker 是待办
    # 队列，消息被 worker 取走即消费；而任务状态（analyze_task_repo 写的
    # analyze:task:<id>）要留 1 小时给 B3/B4 轮询。混在一个库里，一次 FLUSHDB
    # 就会顺手把在跑的任务状态一起清掉。
    #
    # host/port/password 这三项 app/redis_client.py 也在读（它另有自己的连接池
    # 超时与重试参数，所以没有并进 Settings）。两边读的是同一份 .env，值不会漂；
    # 这里只是让 Celery 的连接串也能从 .env 出来，而不是把口令写死在代码里。
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_password: str = ""
    celery_broker_db: int = 0

    @property
    def celery_broker_url(self) -> str:
        """Celery 的 broker 与 result backend 连接串。

        密码过一道 quote()：redis 口令是自定的，出现 @ / : / # 这类字符时直接
        拼进 URL 会被当成主机名或片段的一部分，连接必然失败。.env 里现在这个
        口令是纯字母数字，但不能靠这个运气。
        """
        auth = f":{quote(self.redis_password, safe='')}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.celery_broker_db}"


settings = Settings()

from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase,sessionmaker
from app.config import settings
engine = create_engine(settings.database_url,pool_size=5,max_overflow=10,pool_pre_ping=True,
                       pool_recycle=1800,echo=False)
SessionLocal = sessionmaker(expire_on_commit=False,autocommit=False, autoflush=False, bind=engine)
class Base(DeclarativeBase):
    pass


@contextmanager
def session_scope():
    """脚本与后台任务（celery）用的会话，自带事务边界。

    正常退出自动提交，抛异常则回滚，无论哪条路径都关闭会话（连接归还池子）。

    与 get_db() 的区别：本函数给**请求之外**的代码用，进出都管事务；
    get_db() 给 **Flask 请求内**用，只借出会话、不管提交，且依赖
    init_app() 注册的 teardown 收尾。两者不可互换。
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_app(app):
    """把会话生命周期挂到 Flask 应用上，请求结束统一关闭。

    需与 get_db() 配对使用。当前 app-d.py 尚未接入数据库，此处先备好，
    等 /api 蓝图建立后调用一次即可。
    """
    @app.teardown_appcontext
    def _close_session(exc):
        from flask import g
        session = g.pop("db_session", None)
        if session is not None:
            session.close()


def get_db():
    """Flask 请求内取会话（同一个请求复用同一个 Session）。

    前提：应用已调用 init_app(app) 注册 teardown，否则会话不会被关闭。
    """
    from flask import g
    if "db_session" not in g:
        g.db_session = SessionLocal()
    return g.db_session

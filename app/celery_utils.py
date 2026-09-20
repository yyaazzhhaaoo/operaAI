"""Celery 与 Flask 的集成（Flask 文档推荐的集成模式）。

要点是 FlaskTask：Celery 默认直接调用任务的 run()，任务里没有 Flask 的应用
上下文，`current_app` / `get_db()` 全都拿不到。包一层 `with app.app_context()`
之后任务里才能用 Flask 那一套。

本项目的分析任务目前只用得上 redis 和磁盘路径（见 analyze_service 的模块文档），
还不需要这个上下文；但包着它代价近零，而少了它将来要想在任务里查一次库就得返工。
"""

from celery import Celery, Task


def celery_init_app(app) -> Celery:
    """按 `app.config["CELERY"]` 装配 Celery，挂到 `app.extensions["celery"]`。

    配置从 app.config 取而不是直接从 settings 取，是为了让测试能用
    `create_app({"CELERY": {"task_always_eager": True}})` 把任务改成在请求线程里
    同步跑完，不必起一个 worker。
    """

    class FlaskTask(Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app = Celery(app.name, task_cls=FlaskTask)
    celery_app.config_from_object(app.config["CELERY"])
    # set_default() 让 @shared_task 认到这个实例。测试里 create_app() 会被反复
    # 调用，后建的 app 覆盖掉 default 正是想要的行为——否则测试传进来的 eager
    # 配置不会生效。生产一个进程只建一次，无所谓。
    celery_app.set_default()
    app.extensions["celery"] = celery_app
    return celery_app

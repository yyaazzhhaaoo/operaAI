"""Celery worker 的启动入口。

在项目根目录、激活 venv 之后：

    celery -A app.worker:celery_app worker --loglevel=info --concurrency=2

为什么单独一个文件：`celery -A` 需要**模块级**能找到一个 Celery 实例，
而 app/__init__.py 里只有 create_app() 这个工厂，没有现成的实例可指。Celery
官方推荐的做法（Flask 文档里的 make_celery.py）就是在 web 应用之外另放一个
入口模块，两边互不干扰。

`--concurrency` 按机器核数给：librosa 提音高是纯 CPU 密集，默认的 prefork 池
每个子进程吃满一个核，开多了只会互相抢 CPU、让每个任务都变慢。

**不要用 `--pool=gevent`**。部署手册写的是 gunicorn + gevent + celery，其中
gevent 是给 gunicorn（I/O 并发）用的，不是给 worker 的：gevent 池下面 CPU 密集
任务照样串行，还平白多一层调度开销。
"""

from app import create_app

flask_app = create_app()
celery_app = flask_app.extensions["celery"]

"""Celery worker 的启动入口。

在项目根目录、激活 venv 之后：

    celery -A app.worker:celery_app worker --loglevel=info --concurrency=2

另外，**示范库解析任务走的是独立的 `demucs` 队列**（`parse_service._dispatch`
里 `apply_async(queue="demucs")`）。不带 `-Q demucs` 的 worker 不消费这个队列：

    celery -A app.worker:celery_app worker -Q demucs --concurrency=1 --loglevel=info

漏掉的症状是「上传成功但解析永远停在 parsing」——前端一直轮询，没有任何报错。
`--concurrency=1` 而不是 B 组的 2：`torch.set_num_threads(4)`（`demucs_threads`）
已经把 4 个核吃满，再开第二个进程只会互相抢核，两处数值要一起看
（见 `app/config.py` 里 `demucs_threads` 的注释）。

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

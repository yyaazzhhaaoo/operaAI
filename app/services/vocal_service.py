# -*- coding: utf-8 -*-
"""Demucs 人声分离引擎（示范库解析链路用）。

对外只暴露 separate_vocal()：给一个音频文件路径，返回 16kHz 单声道的人声信号。

**本模块的 torch / demucs 全部是函数内惰性 import，模块顶层一行都没有。**
Demucs 依赖 PyTorch，而 PyTorch 自 2.2.2 起不再发布 macOS x86_64 轮子，
`requirements.txt` 里那几行也带 `; sys_platform == "linux"` 标记——也就是说
Mac 上根本装不到。若把 import 提到顶层，`app/api/` 的 import 链会在 Intel Mac
上直接抛 ModuleNotFoundError，整个 Flask 应用起不来：一个功能不可用会升级成
整个项目本地跑不了。惰性 import 下 Mac 上的表现是「应用照常启动，只有解析任务
失败并落成 error」，这是可接受的降级。
"""

import os
from pathlib import Path

import numpy as np

from app.common.errors import BusinessError
from app.config import settings

# 与 analyze_service 的采样率约定对齐（那边的 SR / MAX_AUDIO_SEC）。
#
# 这两处**刻意各写一份而不是互相 import**：vocal_service 是更底层的音频工具，
# 将来 analyze_service 的 HPSS 若也换成 Demucs，就会形成
# analyze_service → vocal_service → analyze_service 的循环 import。
# 代价是这两个数要一起改——与项目里「app-d.py 那套参数要两边一起调」同理。
SR = 16000                  # 统一重采样到 16k，与 pyin 的输入约定一致
MAX_AUDIO_SEC = 180         # 只处理前 3 分钟，与 B 组分析的上限一致

MODEL_NAME = "htdemucs"     # 四轨模型（drums/bass/other/vocals），CPU 上精度与耗时平衡最好
VOCAL_STEM = "vocals"

# 进程级模型缓存。Celery prefork 下每个子进程各持一份（fp32 约 170MB），
# 这是刻意接受的：每次任务重新 get_model 会重新读盘 + 反序列化，几秒起步。
_model = None
_threads_ready = False


def _prepare_runtime():
    """在 import torch 之前设好环境变量，并定下线程数。

    两件事都必须发生在 `import demucs` 之前：

    1. HF_HOME / TORCH_HOME —— demucs 4.1.0 的 get_model 先走 HuggingFace Hub
       （huggingface_hub.hf_hub_download，缓存受 HF_HOME 控制），失败后回退
       legacy 远程仓库（torch.hub.load_state_dict_from_url，缓存受 TORCH_HOME
       控制，见 demucs/pretrained.py 的 get_model）。两个库都在 **import 期**
       就把缓存目录求值成了模块级常量，之后再改这个变量不会生效，权重仍会
       落到 ~/.cache。部署机上跑 worker 的账号（常是 root 或独立服务账号）
       家目录可能是个小分区，落在那儿迟早撑爆。本机实测国际源全部超时，
       所以实际命中的是回退路径——预置权重（scripts/fetch_demucs_weights.sh）
       正是按 torch.hub 的缓存布局放的。
    2. 线程数 —— 见下。
    """
    global _threads_ready

    model_dir = Path(settings.demucs_model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)

    # 权重目录。**两个环境变量都设**，因为不确定 demucs 4.1.0 走哪条取数路径
    # （Step 4 探查过，但两种布局的差异只影响放文件的子目录，不影响根目录）：
    #   TORCH_HOME → torch.hub 的 load_state_dict_from_url 取
    #                $TORCH_HOME/hub/checkpoints/<文件名>
    #   HF_HOME    → HuggingFace Hub 取 $HF_HOME/hub/...
    # 权重由 scripts/fetch_demucs_weights.sh 预置（放在 torch.hub 那套布局下），
    # 离线部署靠人工拷贝。两个都指向 settings.demucs_model_dir，所以缓存不会
    # 散到 ~/.cache 去——部署机上跑 worker 的账号家目录可能是个小分区。
    #
    # 必须在本模块 import demucs 之前设好：两个库都在 import 期把缓存目录
    # 求值成了模块级常量，之后再改这个变量不生效。
    os.environ.setdefault("TORCH_HOME", str(model_dir))
    os.environ.setdefault("HF_HOME", str(model_dir))

    if _threads_ready:
        return

    import torch

    # 单条音频内部的算子并行度。**必须与 worker 的 --concurrency 相乘不超过
    # 物理核数**：部署定档是 4 核 + concurrency=1，所以这里吃满 4。
    torch.set_num_threads(settings.demucs_threads)

    # inter-op 是「算子之间」的并行，demucs 的计算图是串行的，开多了只是
    # 徒增调度开销。这个函数**全进程只能调一次**，第二次会抛 RuntimeError，
    # 所以拿 _threads_ready 兜住——celery worker 里每个子进程都会走到这里。
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass

    _threads_ready = True


def _get_model():
    """取（并缓存）htdemucs 模型。"""
    global _model
    if _model is not None:
        return _model

    from demucs.pretrained import get_model

    # get_model 会在缓存缺失时联网下载。断网、或离线部署时权重没预置到位，
    # 这里抛的是 requests / huggingface_hub 的网络异常，交给调用方落成 error。
    _model = get_model(MODEL_NAME)
    _model.eval()
    return _model


def separate_vocal(path: Path, *, max_sec: float = MAX_AUDIO_SEC) -> np.ndarray:
    """分离出人声轨，返回 16kHz 单声道信号。

    用 `get_model` + `apply_model` 而不是 4.1.0 新增的 `demucs.api.Separator`：
    Separator 是个薄封装，自己管音频读取（走 torchaudio/ffmpeg）。而本项目已有
    librosa、且 B 组分析全程用 librosa 读音频，自己读能保证两条链路的解码行为
    一致；4.1.0 又把 torchaudio 摘出了推理路径，绕开它反而少一个变数。

    CPU 参数上只给 shifts=1：demucs CLI 默认是 5，即同一段音频跑 5 遍取平均，
    质量有提升但耗时正好是 5 倍，在 4 核 CPU 上不可接受。
    """
    import librosa
    import torch
    from demucs.apply import apply_model

    _prepare_runtime()
    model = _get_model()

    if not Path(path).is_file():
        raise BusinessError(404, "音频文件不存在，无法解析")

    # 按模型自己的采样率读（htdemucs 是 44100），重采样留到分离之后做：
    # 先降到 16k 会把高频泛音丢掉，反而影响分离质量。
    # mono=False 保留立体声——htdemucs 是立体声模型，喂单声道会掉精度。
    wav, _ = librosa.load(str(path), sr=model.samplerate, mono=False, duration=max_sec)
    if wav.size == 0:
        raise BusinessError(400, "音频是空的，无法解析")

    wav = torch.from_numpy(np.asarray(wav)).float()
    if wav.dim() == 1:                  # 单声道文件读出来是一维
        wav = wav.unsqueeze(0)
    if wav.shape[0] == 1:               # 复制成两轨，满足模型的立体声输入要求
        wav = wav.repeat(2, 1)
    elif wav.shape[0] > 2:              # 多声道只取前两轨
        wav = wav[:2]

    # apply_model 自己要一个 batch 维，返回 [B, 音轨数, 声道数, 采样数]。
    # 输入不做归一化：apply_model 内部会按 mix 的均值/标准差自己缩放再还原。
    # num_workers=0 是必须的——它开的是 DataLoader 多进程，会和上面设的
    # torch 线程数抢核，CPU 上实测反而更慢。
    sources = apply_model(
        model,
        wav[None],
        device="cpu",
        shifts=1,
        split=True,
        overlap=0.25,
        num_workers=0,
        progress=False,
    )[0]

    vocal = sources[model.sources.index(VOCAL_STEM)]
    if vocal.shape[0] > 1:              # 立体声人声轨混成单声道
        vocal = vocal.mean(dim=0)

    y = vocal.detach().numpy()

    # 分离是在 44.1k 上做的，这里降到 16k 与 pyin 的输入约定对齐。
    if model.samplerate != SR:
        y = librosa.resample(y, orig_sr=model.samplerate, target_sr=SR)

    return np.ascontiguousarray(y, dtype=np.float32)

# -*- coding: utf-8 -*-
"""LLM 调用的唯一出口。

只有这个模块知道模型部署在哪、怎么发请求、请求体长什么样。将来换模型、
加限频、开流式、加重试都只动这一个文件，coach_service 不用碰。

用 requests 直调而不引 openai SDK：本项目只有一个端点要调，而 SDK 会带进
httpx/anyio/distro/jiter/sniffio/tqdm 等约 8 个新依赖，按项目规矩（requirements.txt
每行钉死版本）要逐个钉，不划算。requests 已在 requirements.txt 钉好。
"""
import logging

import requests

from app.config import settings

logger = logging.getLogger(__name__)


class LlmError(Exception):
    """LLM 不可用：超时、连不上、非 200、响应结构异常、content 为空。

    service 层接住它转成 BusinessError(503)；让它带着原始信息向上冒，
    日志里能看到「到底哪一步坏了」，而不是一个笼统的「AI 不可用」。
    """


def chat(
    messages: list[dict],
    *,
    timeout: float | None = None,
    response_format: dict | None = None,
) -> str:
    """发一轮对话，返回 assistant 的文本内容。

    messages 是 OpenAI 格式：[{"role":"system"|"user"|"assistant","content":str}, ...]

    response_format 传了就在请求体里带上（guided decoding 强制结构化输出）。
    该部署已实测支持（2026-10-13 探测，HTTP 200 且 content 是合法 JSON）；
    若将来换到不支持的部署，传 None 走 prompt 约束那条路。
    """
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "max_tokens": 800,
        "temperature": 0.7,
        # Qwen3.x 是推理模型：默认把正文写进 reasoning 字段、content 返回 null。
        # 实测 max_tokens=32 时 content 直接是 null；加到 800 仍被思维链吃满
        # （finish_reason=length，一个字正文都没有）。教练场景要的是能直接展示
        # 给学生看的回复，必须显式关掉思考。
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if response_format is not None:
        payload["response_format"] = response_format

    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"

    # 超时拆成 (连接, 读取)：连不上是网络问题、该快速失败；生成慢是正常现象、
    # 给足余量。单值超时会让「网络不通」也要干等满 3 秒。
    t = timeout if timeout is not None else settings.llm_timeout
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=(2, t))
    except requests.RequestException as e:
        raise LlmError(f"LLM 请求失败：{e}") from e

    if resp.status_code != 200:
        raise LlmError(f"LLM 返回 HTTP {resp.status_code}：{resp.text[:200]}")

    try:
        body = resp.json()
        content = body["choices"][0]["message"].get("content")
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise LlmError(f"LLM 响应结构异常：{e}；原文={resp.text[:200]}") from e

    if not content or not content.strip():
        raise LlmError("LLM 返回空 content（enable_thinking 没生效？）")

    return content

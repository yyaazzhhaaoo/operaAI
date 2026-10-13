# -*- coding: utf-8 -*-
"""临时脚本：验证 llm_client 能真实调通内网模型。验完即删（见计划的 Task 8）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.services import llm_client

print("端点:", settings.llm_base_url, "模型:", settings.llm_model)

# 1. 最基本的往返
out = llm_client.chat([{"role": "user", "content": "用一句话说明什么是音准。"}])
print("1) 回复:", out)
assert out and "音准" in out, f"回复异常: {out!r}"

# 2. content 不为空 —— 这条专门盯「思考模式没关掉」这个坑：
#    开着的话模型把正文全写进 reasoning，content 是 null。
assert out.strip(), "content 为空，多半是 enable_thinking 没关掉"

# 3. 错误路径：连不上的地址要抛 LlmError，不能是裸的 requests 异常
import app.services.llm_client as m
orig = settings.llm_base_url
try:
    m.settings.llm_base_url = "http://127.0.0.1:1/v1"   # 必然连不上
    try:
        m.chat([{"role": "user", "content": "hi"}], timeout=1)
        raise AssertionError("连不上时应抛 LlmError")
    except m.LlmError as e:
        print("3) 不可达时抛出 LlmError ✓:", e)
finally:
    m.settings.llm_base_url = orig

print("全部通过")

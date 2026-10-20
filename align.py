import torch
from qwen_asr import Qwen3ForcedAligner

# 加载模型（首次运行会自动从 HuggingFace 下载）
model = Qwen3ForcedAligner.from_pretrained(
    "Qwen/Qwen3-ForcedAligner-0.6B",
    dtype=torch.bfloat16,
    device_map="cpu" # 如果只用 CPU，可以改成 "cpu"
)
with open("../穆桂英挂帅.txt", "r", encoding="utf-8") as f:
    text_content = f.read().strip()
# 填入你的音频路径和唱词
results = model.align(
    audio="../穆桂英挂帅修剪版.wav",
    text=text_content,
    language="Chinese",
)

# 打印每个字的时间
for r in results[0]:
    print(f"{r.text}: {r.start_time:.2f}s - {r.end_time:.2f}s")

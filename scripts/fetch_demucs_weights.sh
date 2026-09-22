#!/usr/bin/env bash
# 戏韵AI — 取 htdemucs 权重到 models/demucs/（示范库解析链路用）
#
# 用法（项目根目录）：scripts/fetch_demucs_weights.sh
#     DEST=<目录> scripts/fetch_demucs_weights.sh    # 覆盖落盘位置
#
# 为什么不用官方地址：本机实测 dl.fbaipublicfiles.com 与 huggingface.co 均超时，
# 而 ModelScope 上的 pengzhendong/uvr-demucs 有同一份文件（同名、同字节数、
# sha256 前 8 位与文件名末段一致）。见 spec 6.1 的可达性实测表。
#
# 离线部署可跳过本脚本，改由人工拷贝——与 .gitignore 里那句注释一致
# （models/ 不进版本库：权重约 80MB 且随模型换代而变）。
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 落盘位置：demucs 的**本地模型仓库**布局，即 vocal_service 传给
# get_model(name, repo=...) 的那个目录（见 app/config.py 的 demucs_repo_dir）。
#
# **不要改回 $TORCH_HOME/hub/checkpoints 那套**：那只对 get_model(name) 的回退
# 分支有用，而那条路在离线机器上根本走不到——它得先从 HF 拿到 bag 描述文件
# （htdemucs.yaml）才轮到读 .th，而 yaml 在本地缓存里没有位置。2026-09-22 实测：
# 真离线机器上两条网络路径都不可达，光有 .th 永远起不来。另外 84MB 的权重放在
# torch.hub 那层缓存里其实也不会被读到，等于白占一份磁盘。
DEST="${DEST:-$ROOT/models/demucs/repo}"
FILE="955717e8-8726e21a.th"
BAG="htdemucs.yaml"
SIZE=84141911
SHA256_PREFIX=8726e21a
URL="${URL:-https://www.modelscope.cn/api/v1/models/pengzhendong/uvr-demucs/repo?Revision=master&FilePath=v3_v4_repo%2F${FILE}}"

mkdir -p "$DEST"
echo "→ $URL"
# -L 必须有：ModelScope 先回 302，不加 -L 会得到一个 350 字节的重定向正文
# 而不是 84MB 的权重，且 curl 退出码仍是 0——静默坏掉。
curl -sSL --fail -o "$DEST/$FILE" "$URL" || { echo "下载失败：$URL" >&2; exit 1; }

got_size=$(wc -c < "$DEST/$FILE" | tr -d ' ')
if [ "$got_size" != "$SIZE" ]; then
  echo "字节数不符：期望 $SIZE，实际 $got_size —— 多半是被重定向骗了或源换了" >&2
  rm -f "$DEST/$FILE"; exit 1
fi

# 闸门：文件名末段就是哈希前缀，对不上说明拿到的是同名替换件而不是官方权重
got_hash=$(sha256sum "$DEST/$FILE" | cut -c1-8)
if [ "$got_hash" != "$SHA256_PREFIX" ]; then
  echo "sha256 前缀不符：期望 $SHA256_PREFIX，实际 $got_hash" >&2
  rm -f "$DEST/$FILE"; exit 1
fi

# bag 描述文件是 get_model(name, repo=...) 的入口：没有它，同一个目录里躺着的
# .th 不会被认（LocalRepo 只提供签名，BagOnlyRepo 才认 htdemucs 这个名字）。
# 内容是个定值，与上面钉死的 FILE 一一对应，所以**刻意不下载**——21 字节的常量
# 比一次网络往返可靠，离线机器也免了第二个取数源。
sig="${FILE%.th}"   # 955717e8-8726e21a
sig="${sig%%-*}"    # 955717e8（官方文件的签名就是它）
printf "models: ['%s']\n" "$sig" > "$DEST/$BAG"

echo "✓ $DEST/$FILE  ($got_size 字节, sha256:$got_hash)"
echo "✓ $DEST/$BAG   (models: ['$sig'])"

#!/usr/bin/env bash
# 本机（4070 WSL）启动 Nosam+Mason 上 riichi.dev ranked——coop 默认开、自动重连、同起。
# 用法：bash online3p/live_start.sh          # 上 ranked
#      RIICHI_URL=.../ws/validate bash online3p/live_start.sh   # 改端点（调试）
#      LEVEL=7.5 AGGR=13 bash online3p/live_start.sh   # 剥削旋钮（不设=默认 8.0/12.0）
set -u
cd "$(dirname "$0")/.." || exit 1        # riichienv 仓根
REPO=$(pwd)
PY=$HOME/miniconda3/envs/mortal/bin/python
PP=$HOME/Mortal3/mortal:$HOME/qgrp:$REPO
CK=$HOME/qgrp3p_run/qgrp3p_v3_ftb50k.pth
TRANS=$HOME/zeroppo-grp/grp_trans3p_v1.pth
TCREPO=$HOME/zeroppo-grp
URL=${RIICHI_URL:-wss://game.riichi.dev/ws/ranked}
LOG=$REPO/online3p/_live
COOPDIR=/tmp/riichi_coop
mkdir -p "$LOG" "$COOPDIR"
rm -f "$COOPDIR/STOP" "$COOPDIR"/*.json   # 清除上次停机标记 + 陈旧指纹

if pgrep -af "online3p[.]client" | grep -q "ws/"; then
  echo "已有 bot 在运行，请先 bash online3p/live_stop.sh（或 --force 停）"; exit 1
fi
[ -f "$CK" ] || { echo "缺权重 $CK"; exit 1; }

# 诊断：RIICHI_RAW=1 时每 bot 把原始 recv/send 帧（含解码后的 observation）落盘
# $LOG/$BOT.frames.jsonl，用于核对平台真实线格式（如红5=5pr 还是 5p）。默认关。
RAW=${RIICHI_RAW:-0}
# 剥削旋钮：LEVEL=/AGGR= 覆盖 aux 水平/激进度条件（三家同值＝对手 profile）；不设=默认
STYLE=()
[ -n "${LEVEL:-}" ] && STYLE+=(--level "$LEVEL")
[ -n "${AGGR:-}" ] && STYLE+=(--aggr "$AGGR")
for BOT in Nosam Mason; do
  RAWENV=()
  if [ "$RAW" = "1" ]; then
    : > "$LOG/$BOT.frames.jsonl"   # 清空上次抓取
    RAWENV=(RIICHI_RAW_LOG="$LOG/$BOT.frames.jsonl")
  fi
  setsid nohup env PYTHONPATH="$PP" "${RAWENV[@]}" "$PY" -m online3p.client \
    --url "$URL" --bot-name "$BOT" \
    --qgrp-ckpt "$CK" --trans-ckpt "$TRANS" --transcore-repo "$TCREPO" \
    --device cuda "${STYLE[@]}" > "$LOG/$BOT.log" 2>&1 < /dev/null &
  echo "$BOT 已启动 → $LOG/$BOT.log${RAWENV:+ (raw→$LOG/$BOT.frames.jsonl)}"
done
echo ""
echo "两 bot 已上 $URL（coop 默认开、自动重连、同起）。"
echo "看状态： tail -f $LOG/Nosam.log $LOG/Mason.log"
echo "停机（打完当前对局再停、同停）： bash online3p/live_stop.sh"

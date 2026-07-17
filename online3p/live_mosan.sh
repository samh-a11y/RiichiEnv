#!/usr/bin/env bash
# 本机（4070 WSL）启动 Mosan 单 bot——Mortal3 原生 mortal3p-msebest（--backend mortal3）。
# 新 bot 默认连 **validate** 端点走验证流程；过验证后用 RIICHI_URL 切 ranked。
# 用法：bash online3p/live_mosan.sh                              # 连 validate（默认）
#      RIICHI_URL=wss://game.riichi.dev/ws/ranked bash online3p/live_mosan.sh   # 过验证后上 ranked
# 停机：touch /tmp/riichi_coop/STOP_MOSAN   （打完当前局退；独立于 Nosam/Mason 的 STOP）
#      或 pkill -f 'bot-name Mosan'
set -u
cd "$(dirname "$0")/.." || exit 1
REPO=$(pwd)
PY=$HOME/miniconda3/envs/mortal/bin/python
# mortal3 后端只需 Mortal3/mortal（model/engine/libriichi3p.so）+ riichienv；无需 qgrp/trans
PP=$HOME/Mortal3/mortal:$REPO
CK=$HOME/Mortal3/train/sl3p-online-mse/ckpt/mortal-80000.pth   # mortal3p-msebest（md5 d02d8c6f）
URL=${RIICHI_URL:-wss://game.riichi.dev/ws/validate}
LOG=$REPO/online3p/_live
STOP=/tmp/riichi_coop/STOP_MOSAN
mkdir -p "$LOG" /tmp/riichi_coop
rm -f "$STOP"

if pgrep -af "online3p[.]client" | grep -q "bot-name Mosan"; then
  echo "Mosan 已在运行，请先 touch $STOP 优雅停，或 pkill -f 'bot-name Mosan'"; exit 1
fi
[ -f "$CK" ] || { echo "缺权重 $CK"; exit 1; }

setsid nohup env PYTHONPATH="$PP" "$PY" -m online3p.client \
  --url "$URL" --bot-name Mosan --backend mortal3 --mortal-ckpt "$CK" \
  --device cuda --stop-file "$STOP" "$@" > "$LOG/Mosan.log" 2>&1 < /dev/null &
echo "Mosan 已启动（$URL） → $LOG/Mosan.log"
echo "看状态： tail -f $LOG/Mosan.log"
echo "停机：   touch $STOP   （打完当前局退）"

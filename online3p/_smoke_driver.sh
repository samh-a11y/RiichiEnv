#!/usr/bin/env bash
# online3p 端到端冒烟驱动（gpu16b 上 detached 跑）：mock 平台 + Nosam/Mason 真实客户端
# + dummy 第三家，打 --real 决定的桌型。用法：bash _smoke_driver.sh <real> <hanchan> <seed>
set -u
cd /root/riichienv
# mock（裁判）用仓库 .venv（有 riichienv）；客户端用 aigc venv（有 torch/libriichi3p）
MOCK_PY=/root/riichienv/.venv/bin/python
MOCK_PP=/root/riichienv
CLIENT_PY=/root/aigc_apps/venv/bin/python3
CLIENT_PP=/root/Mortal3/mortal:/root/qgrp:/root/riichienv
CK=/root/qgrp3p_run/qgrp3p_v3_ftb50k.pth
REAL=${1:-2}; HAN=${2:-1}; SEED=${3:-100}; PORT=${4:-8901}
LOG=/root/riichienv/online3p/_smoke
mkdir -p "$LOG"; rm -f "$LOG"/*.log "$LOG/DONE"
echo "driver: real=$REAL hanchan=$HAN seed=$SEED port=$PORT $(date +%T)" > "$LOG/driver.log"

PYTHONPATH=$MOCK_PP $MOCK_PY -m online3p.mock_server --host 127.0.0.1 --port "$PORT" --real "$REAL" --hanchan "$HAN" --seed "$SEED" > "$LOG/mock.log" 2>&1 &
MOCK=$!
sleep 3
PYTHONPATH=$CLIENT_PP $CLIENT_PY -m online3p.client --url "ws://127.0.0.1:$PORT" --bot-name Nosam --qgrp-ckpt "$CK" --device cuda --no-reconnect --exit-on-end-game > "$LOG/nosam.log" 2>&1 &
N=$!
if [ "$REAL" -ge 2 ]; then
  PYTHONPATH=$CLIENT_PP $CLIENT_PY -m online3p.client --url "ws://127.0.0.1:$PORT" --bot-name Mason --qgrp-ckpt "$CK" --device cuda --no-reconnect --exit-on-end-game > "$LOG/mason.log" 2>&1 &
  M=$!
else
  M=""
fi

for i in $(seq 1 240); do kill -0 $MOCK 2>/dev/null || break; sleep 2; done
kill $MOCK $N $M 2>/dev/null
wait 2>/dev/null
echo "driver done $(date +%T)" >> "$LOG/driver.log"
touch "$LOG/DONE"

#!/usr/bin/env bash
# 上线 ranked 的**唯一入口**：两道门 → 签通行证 → live_start。
#
# 2026-07-28 事故后立的规矩：改完代码只做 py_compile 就上 ranked，结果每帧抛
# AttributeError、bot 全程无法出牌、平台代打摸切。语法检查抓不到属性名错误，必须跑
# 运行时门。两道门都在离线跑，不碰平台：
#   门1 回放门 —— 用固定的真实 RAW 样本双边回放整条链路：
#        handle_frame → _feed → _note_event → _try_coop_timing（含侧信道 IO 与
#        detect）→ bot.react 真实推理 → _on_request_action → _sanitize。
#        双边跑还顺带覆盖 coop **命中**路径（单边只能覆盖未命中）。
#   门2 判据门 —— coop timing 判据在真实 log 上不得有假阳（把不同桌判成同桌
#        会让 bot 对无关真人做协作压制）。
# 全过才 stamp 通行证，然后才起 ranked。PreToolUse hook 会校验这张通行证。
#
# ⚠ 2026-07-29 去掉了原门3（/ws/validate 拿 passed:true）：它要求先停机（同 JWT 双连
# 会把在跑的 bot 挤掉 → 又是摸切），每次上线都得停机过门，成本过高。代价是门禁不再覆盖
# 「平台协议/服务器行为变化」——真要验平台，手动跑：
#   PYTHONPATH=... python -m online3p.client --url wss://game.riichi.dev/ws/validate \
#       --bot-name Nosam --no-reconnect --no-coop      # 需 bot 当前没在 ranked 上跑
#
# 用法：
#   bash online3p/go_live.sh                          # 两道门 + 上线（默认 hybrid α=0.18）
#   bash online3p/go_live.sh --alpha 0.12             # 透传给 client（同 live_start.sh）
#   GATES_ONLY=1 bash online3p/go_live.sh             # 只过门+签证，不上线
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
REPO=$(pwd)
PY=$HOME/miniconda3/envs/mortal/bin/python
PP=$HOME/Mortal3/mortal:$HOME/qgrp:$REPO
SAMPLES=$REPO/online3p/_samples
BACKEND=${BACKEND:-hybrid}
ALPHA=${ALPHA:-0.18}
GATES=()

fail() { echo ""; echo "❌ $1"; echo "   ⇒ 未签发通行证，**不要上 ranked**"; exit 1; }

echo "═══ 门1/2 回放门（离线，双边真实帧）"
[ -f "$SAMPLES/A.frames.jsonl" ] && [ -f "$SAMPLES/B.frames.jsonl" ] \
  || fail "缺样本 $SAMPLES/{A,B}.frames.jsonl（用 RIICHI_RAW=1 采集一局后放进去）"
rm -rf /tmp/riichi_coop_replay
for side in A B; do
  name=$([ "$side" = A ] && echo GateA || echo GateB)
  PYTHONPATH=$PP "$PY" online3p/replay_smoke.py \
      --frames "$SAMPLES/$side.frames.jsonl" --name "$name" \
      --teammates GateA,GateB --backend "$BACKEND" --alpha "$ALPHA" \
      --device cuda --limit 200 2>&1 | tail -4
  [ "${PIPESTATUS[0]}" -eq 0 ] || fail "回放门 $side 侧未过"
done
GATES+=(--gate replay)

echo ""
echo "═══ 门2/2 判据门（coop timing 在真实 log 上不得假阳）"
PYTHONPATH=$PP "$PY" online3p/verify_coop_timing.py \
    --a "$SAMPLES/A.frames.jsonl" --b "$SAMPLES/B.frames.jsonl" 2>&1 | tail -4
[ "${PIPESTATUS[0]}" -eq 0 ] || fail "判据门未过（有假阳）"
GATES+=(--gate coop)

echo ""
echo "═══ 签发通行证"
"$PY" online3p/gate.py stamp "${GATES[@]}" || fail "签发失败"

if [ "${GATES_ONLY:-0}" = "1" ]; then
  echo ""
  echo "GATES_ONLY=1：只过门，未上线。上线：bash online3p/live_start.sh --backend $BACKEND --alpha $ALPHA"
  exit 0
fi

echo ""
echo "═══ 上线 ranked"
RIICHI_RAW=${RIICHI_RAW:-1} bash online3p/live_start.sh \
    --backend "$BACKEND" --alpha "$ALPHA" "$@"

#!/usr/bin/env bash
# Claude Code PreToolUse hook：拦住「没过门就上 ranked」。
#
# 由 2026-07-28 摸切事故催生：助手改完 client.py 只做了 py_compile 就 live_start 上
# ranked，属性名错误导致 bot 每帧抛异常、全程无法出牌、平台代打摸切。靠自觉不可靠，
# 改成机制拦截。
#
# 逻辑：只关心「起 ranked 在线对战」的命令；命中后校验 online3p/gate.py 的通行证
# （绑定上线链路代码指纹 + 2h 时效 + 必须过 replay/coop 两门）。无效 ⇒ exit 2，
# stderr 会作为阻止原因反馈给模型。validate/dry-run、停机、离线 arena 一律不拦。
#
# 注册（全局 ~/.claude/settings.json，改完需重启 session 才生效）：
#   "PreToolUse": [{ "matcher": "Bash",
#                    "hooks": [{"type":"command",
#                               "command":"bash /home/administrator/riichienv/online3p/hooks/live_gate.sh"}] }]
set -uo pipefail

CMD=$(jq -r '.tool_input.command // ""' 2>/dev/null || echo "")
[ -z "$CMD" ] && exit 0

# 只拦真正会把 bot 送上排位的命令
is_live=0
case "$CMD" in
  *live_start.sh*) is_live=1 ;;
  *online3p.client*ws/ranked*) is_live=1 ;;
  *go_live.sh*) is_live=0 ;;      # 正门：它自己会过门+签证
esac
# go_live.sh 出现在命令里就一律放行（即使同时含 live_start.sh 字样）
case "$CMD" in *go_live.sh*) exit 0 ;; esac
[ "$is_live" -eq 1 ] || exit 0

GATE=/home/administrator/riichienv/online3p/gate.py
PY=$HOME/miniconda3/envs/mortal/bin/python
[ -x "$PY" ] || PY=python3

if OUT=$("$PY" "$GATE" check 2>&1); then
  exit 0            # 通行证有效：刚过完门，放行
fi

{
  echo "🚫 已拦下上 ranked 的命令：上线门禁未通过。"
  echo "$OUT"
  echo ""
  echo "正门是（三道门 + 签证 + 上线，一条命令）："
  echo "    cd ~/riichienv && bash online3p/go_live.sh --backend hybrid --alpha 0.18"
  echo "只过门不上线：GATES_ONLY=1 bash online3p/go_live.sh"
  echo ""
  echo "理由（2026-07-28 事故）：只做 py_compile 就上 ranked，属性名错误让 bot 每帧"
  echo "抛异常、全程无法出牌、平台代打摸切，真实排位分受损。门 = 离线双边回放 +"
  echo "coop 判据无假阳（均离线，不碰平台）。"
} >&2
exit 2

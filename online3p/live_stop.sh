#!/usr/bin/env bash
# 优雅停机：两 bot **打完当前对局**后一起退出（不中断进行中对局）。
# 用法：bash online3p/live_stop.sh           # 优雅停（推荐）
#      bash online3p/live_stop.sh --force    # 立即强杀（不等当前对局）
set -u
cd "$(dirname "$0")/.." || exit 1
REPO=$(pwd)
LOG=$REPO/online3p/_live
COOPDIR=/tmp/riichi_coop

if [ "${1:-}" = "--force" ]; then
  pkill -9 -f "online3p[.]client"
  echo "已强杀两 bot（未等当前对局）。"
  exit 0
fi

touch "$COOPDIR/STOP"
echo "已发停机标记 → 两 bot 将各自打完当前对局后退出（空闲时约 5s 内退）。"
echo "等待退出…"
for i in $(seq 1 120); do
  pgrep -f "online3p[.]client" | grep -q . || { echo "两 bot 均已退出。"; rm -f "$COOPDIR/STOP"; exit 0; }
  sleep 5
done
echo "超时仍有进程未退（可能在长对局中）。可继续等，或 --force 强停。"
echo "当前： $(pgrep -af 'online3p[.]client' | grep -c ws/) 个在跑"

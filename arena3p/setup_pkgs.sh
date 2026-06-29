#!/usr/bin/env bash
# 幂等建立 arena3p/engines/_pkgs/community 这个我方 symlink package。
#   - 不改 Mortal3（只读其文件）。
#   - community model.py 用相对 import (from .libriichi.mjai/.consts)，故需 package 化。
#   - 单个 libriichi.so 同时提供 libriichi.mjai 与 libriichi.consts 两个 pyo3 子模块。
#   - _pkgs/ 整个目录已被 .gitignore（symlink/.so/.pth 不入库），故每次 checkout 后跑一次。
set -euo pipefail

ARENA3P_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RIICHIENV_ROOT="$(cd "$ARENA3P_DIR/.." && pwd)"
MORTAL3="$(cd "$RIICHIENV_ROOT/../Mortal3" && pwd)"

COMM_SRC="$MORTAL3/community_3p/v0.1.0"
SO="$COMM_SRC/libriichi-3.12-x86_64-unknown-linux-gnu.so"   # conda mortal = py3.12
PKGS="$ARENA3P_DIR/engines/_pkgs"
PKG="$PKGS/community"

for f in "$COMM_SRC/model.py" "$SO" "$COMM_SRC/mortal.pth"; do
  [[ -e "$f" ]] || { echo "[setup_pkgs] 缺文件: $f" >&2; exit 1; }
done

mkdir -p "$PKG"
: > "$PKGS/__init__.py"
: > "$PKG/__init__.py"
ln -sfn "$COMM_SRC/model.py" "$PKG/model.py"
ln -sfn "$SO"                "$PKG/libriichi.so"
ln -sfn "$COMM_SRC/mortal.pth" "$PKG/mortal.pth"

echo "[setup_pkgs] community symlink package 就绪：$PKG"
ls -l "$PKG"

#!/usr/bin/env bash
# 从 gpuo fetch v8（同事 BC 模型）接入所需资产到 arena3p/engines/_pkgs/v8/（gitignore，勿入库）。
# 幂等：已存在则跳过 .so/代码，权重按 md5 校验。conda mortal py3.12 可直接 import（.so abi3 兼容）。
#   bash arena3p/fetch_v8.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DST="$HERE/engines/_pkgs/v8"
REMOTE=gpuo
mkdir -p "$DST"

echo "[1/4] libriichi_sanma.so"
[ -f "$DST/libriichi_sanma.so" ] || scp -q "$REMOTE:/root/sanma/engine/libriichi_sanma.so" "$DST/"

echo "[2/4] model/ (SanmaNet) + features/ (consts)"
scp -qr "$REMOTE:/root/sanma/model" "$DST/"
scp -qr "$REMOTE:/root/sanma/features" "$DST/"
rm -rf "$DST/model/__pycache__" "$DST/features/__pycache__"

echo "[3/4] runs/v8_bc/model.pth (101MB)"
if [ ! -f "$DST/model.pth" ] || \
   [ "$(md5sum "$DST/model.pth" | cut -d' ' -f1)" != "$(ssh "$REMOTE" md5sum /root/sanma/runs/v8_bc/model.pth | cut -d' ' -f1)" ]; then
  scp -q "$REMOTE:/root/sanma/runs/v8_bc/model.pth" "$DST/model.pth"
fi

echo "[4/4] import 自检"
~/miniconda3/envs/mortal/bin/python -c "import sys; sys.path.insert(0,'$DST'); import libriichi_sanma, model.net, features.consts as c; print('OK libriichi_sanma', libriichi_sanma.__version__, 'N_ACTIONS', c.N_ACTIONS)"
echo "done -> $DST"

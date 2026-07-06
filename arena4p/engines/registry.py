"""四麻模型 → 子进程启动规格（qgrp change-002 对战需求）。

与 arena3p 的差异：
  - 无方言层（四麻无 kita，官方 MJAI 即原生格式，恒等透传）；
  - spec 用 argv(seat) 工厂——qgrp bot 自带 array 协议入口（qgrp/bot/run_stdio.py），
    不必都走 mjai_runner。
路径默认 HOME 布局（gpu-16: /root/...；本地: /home/<user>/...），env 可覆盖。
"""
from __future__ import annotations

import os
import pathlib

RIICHIENV_ROOT = pathlib.Path(__file__).resolve().parents[2]
HOME = pathlib.Path.home()
MORTAL = pathlib.Path(os.environ.get("ARENA_MORTAL_ROOT", HOME / "Mortal")).resolve()
QGRP = pathlib.Path(os.environ.get("ARENA_QGRP_ROOT", HOME / "qgrp")).resolve()
ZEROPPO = pathlib.Path(os.environ.get("ARENA_ZEROPPO_ROOT", HOME / "zeroppo")).resolve()
ZEROPPO_GRP = pathlib.Path(
    os.environ.get("ARENA_ZEROPPO_GRP_ROOT", HOME / "zeroppo-grp")).resolve()

# torch + .so 匹配的解释器（gpu-16: /root/aigc_apps/venv/bin/python3）
ENGINE_PY = os.environ.get("ARENA_ENGINE_PY") or str(
    HOME / "aigc_apps" / "venv" / "bin" / "python3")


def _env(extra: dict | None = None, pythonpath: list | None = None) -> dict:
    env = dict(os.environ)
    device = os.environ.get("ARENA_DEVICE", "cpu")
    env["ARENA_DEVICE"] = device
    if device != "cuda":
        env["CUDA_VISIBLE_DEVICES"] = ""
    for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
              "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        env[k] = "1"
    pp = [str(p) for p in (pythonpath or [])] + [env.get("PYTHONPATH", "")]
    env["PYTHONPATH"] = os.pathsep.join(pp).rstrip(os.pathsep)
    if extra:
        env.update(extra)
    return env


REGISTRY: dict[str, dict] = {
    # 上游四麻 Mortal（默认 config.toml 的 state_file，即 mortal-1090k 系）
    "mortal": {
        "argv": lambda seat: [ENGINE_PY, "-m", "arena4p.engines.mjai_runner",
                              "--model", "mortal", "--seat", str(seat)],
        "env": _env(
            extra={"MORTAL_CFG": os.environ.get(
                "MORTAL_CFG", str(MORTAL / "configs" / "config.toml"))},
            # Mortal 自己的 libriichi.so（标准 46 动作）+ runner 包
            pythonpath=[MORTAL / "target" / "release", RIICHIENV_ROOT],
        ),
        "cwd": str(MORTAL),
    },
    # QGRP 打牌器（qgrp 仓 bot/，自带 ready+数组协议）
    "qgrp": {
        "argv": lambda seat: [
            ENGINE_PY, "-m", "bot.run_stdio", "--player-id", str(seat),
            "--qgrp-ckpt", os.environ.get(
                "ARENA_QGRP_CKPT", str(HOME / "qgrp_run" / "qgrp_full.pth")),
            "--trans-ckpt", os.environ.get(
                "ARENA_QGRP_TRANS", str(ZEROPPO_GRP / "grp_trans_v2.pth")),
            "--transcore-repo", str(ZEROPPO_GRP),
            "--device", os.environ.get("ARENA_DEVICE", "cpu"),
            *(os.environ.get("ARENA_QGRP_EXTRA", "").split() or []),
        ],
        # zeroppo fork 的 libriichi.so（joint 83 动作）+ qgrp 仓根（bot 包）
        "env": _env(pythonpath=[ZEROPPO / "target" / "release", QGRP]),
        "cwd": str(QGRP),
    },
}


def get_spec(model_name: str) -> dict:
    if model_name not in REGISTRY:
        raise KeyError(f"未知模型 {model_name!r}；已知：{list(REGISTRY)}")
    return REGISTRY[model_name]

"""模型 → 子进程启动规格。

每个 runner 跑在「自己 .so 匹配的 torch python」里（community/joint 都用 conda ``mortal`` py3.12）。
父进程（run_arena）跑在 RiichiEnv ``.venv``。两侧只经 stdin/stdout 传 MJAI JSON。
"""
from __future__ import annotations

import os
import pathlib

# arena3p/engines/registry.py -> riichienv/
RIICHIENV_ROOT = pathlib.Path(__file__).resolve().parents[2]
MORTAL3 = (RIICHIENV_ROOT.parent / "Mortal3").resolve()
HOME = pathlib.Path.home()

# 带 torch + 各模型 .so 的解释器（py3.12：community 3.12 .so / joint libriichi3p / v8 abi3 都可导入）。
# 默认本机 conda mortal；可经 ARENA_ENGINE_PY 覆盖（如 gpu-16 用 ~/aigc_apps/venv/bin/python）。
CONDA_MORTAL_PY = os.environ.get("ARENA_ENGINE_PY") or str(
    HOME / "miniconda3" / "envs" / "mortal" / "bin" / "python")


def _env(extra: dict | None = None) -> dict:
    env = dict(os.environ)
    # 设备：ARENA_DEVICE=cuda 走 GPU（模型极小，单卡可并存多实例）；否则 CPU（屏蔽 GPU，确定性）
    device = os.environ.get("ARENA_DEVICE", "cpu")
    env["ARENA_DEVICE"] = device
    if device != "cuda":
        env["CUDA_VISIBLE_DEVICES"] = ""
    # 每个 runner 限 1 线程：单样本推理不吃多线程，多对局并行时避免 torch 线程过订阅（否则颠簸卡死）
    for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
              "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        env[k] = "1"
    # runner 用 -m arena3p.engines.mjai_runner 需从 cwd 找到 arena3p 包；显式 PYTHONPATH 兜底
    env["PYTHONPATH"] = os.pathsep.join(
        [str(RIICHIENV_ROOT), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    if extra:
        env.update(extra)
    return env


REGISTRY: dict[str, dict] = {
    "community": {
        "python": str(CONDA_MORTAL_PY),
        "runner_args": ["--model", "community"],
        "env": _env(),
        "cwd": str(RIICHIENV_ROOT),
        "dialect": "community",  # 4 人格式 + 第 4 座掩码：按座数组 3→4 padding
    },
    "joint": {
        "python": str(CONDA_MORTAL_PY),
        "runner_args": ["--model", "joint"],
        # 防 joint 的 model/engine 间接 import config 时找不到 config.toml
        "env": _env({
            "MORTAL_CFG": str(MORTAL3 / "mortal" / "versions" / "sl3p-joint-v2" / "config.toml"),
        }),
        "cwd": str(RIICHIENV_ROOT),
        "dialect": "standard",  # 原生 3 座，仅 kita↔nukidora
    },
    "v8": {
        # 同事 gpuo BC 模型；.so/net/features/权重 fetch 到 _pkgs/v8（py3.10 编但 abi3，conda mortal py3.12 可用）
        "python": str(CONDA_MORTAL_PY),
        "runner_args": ["--model", "v8"],
        "env": _env(),
        "cwd": str(RIICHIENV_ROOT),
        "dialect": "standard",  # 实测训练 mjai：原生 3 座（scores/tehais 3 元）+ nukidora，与 joint 同
    },
    # ---- change-002（第二测试任务：2×joint-mse vs 1×v8guard，轮转 30k）----
    "joint-mse": {
        # joint 引擎同 joint-v2（实测 3p-mse-v1.1 与 joint-v2 同构）；仅换权重路径。
        "python": str(CONDA_MORTAL_PY),
        "runner_args": ["--model", "joint"],
        "env": _env({
            "ARENA_JOINT_WEIGHT": str(MORTAL3 / "train" / "sl3p-joint-result" / "3p-mse-v1.1.pth"),
            "MORTAL_CFG": str(MORTAL3 / "mortal" / "versions" / "sl3p-joint-v2" / "config.toml"),
        }),
        "cwd": str(RIICHIENV_ROOT),
        "dialect": "standard",  # 原生 3 座，仅 kita↔nukidora
    },
    "v8guard": {
        # 同事 sanma_v8_guard 完整包（v8 BC backbone + danger head + mitoshi 防守 guard，guard 开）。
        # 资产在 Mortal3/train/sanma_v8_guard（44-action build：model/net.py 带 .features()/SanmaDangerHead）。
        "python": str(CONDA_MORTAL_PY),
        "runner_args": ["--model", "v8guard"],
        "env": _env({
            "ARENA_V8GUARD_DIR": str(MORTAL3 / "train" / "sanma_v8_guard"),
            # danger head：默认 v8_danger（=同事 sanma_joint_api 钉死默认）；另有 v8_danger_suit4(更新)可选
            "ARENA_V8_DANGER": str(MORTAL3 / "train" / "sanma_v8_guard"
                                   / "runs" / "v8_danger" / "danger_head.pth"),
        }),
        "cwd": str(RIICHIENV_ROOT),
        "dialect": "standard",  # 同 v8：原生 3 座 + nukidora
    },
}


def get_spec(model_name: str) -> dict:
    if model_name not in REGISTRY:
        raise KeyError(f"未知模型 {model_name!r}；已知：{list(REGISTRY)}")
    return REGISTRY[model_name]

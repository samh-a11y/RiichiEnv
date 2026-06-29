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

# 带 torch + 各模型 .so 的解释器（community 3.12 .so / joint libriichi3p.so 都在此 py3.12 可导入）
CONDA_MORTAL_PY = HOME / "miniconda3" / "envs" / "mortal" / "bin" / "python"


def _env(extra: dict | None = None) -> dict:
    env = dict(os.environ)
    # 强制 CPU：确定性 greedy + 避免 3 个子进程争 GPU（apples-to-apples）
    env["CUDA_VISIBLE_DEVICES"] = ""
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
}


def get_spec(model_name: str) -> dict:
    if model_name not in REGISTRY:
        raise KeyError(f"未知模型 {model_name!r}；已知：{list(REGISTRY)}")
    return REGISTRY[model_name]

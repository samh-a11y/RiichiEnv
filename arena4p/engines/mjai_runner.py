#!/usr/bin/env python3
"""四麻 MJAI 子进程 runner（跑在带 torch + 对应 .so 的解释器里）。

协议同 arena3p/engines/mjai_runner.py：
  握手 : 建好 bot 后输出一行 {"type":"ready"}。
  stdin : 每行 = 一个 JSON 事件数组（该座 new_events() 全量）。
  stdout: 每行 = 一条动作 JSON（去 meta）或 {"type":"none"}。

目前只有 --model mortal（上游 ~/Mortal 标准 v4 权重；qgrp bot 自带协议入口，
见 qgrp/bot/run_stdio.py，不经本 runner）。
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

HOME = pathlib.Path.home()
MORTAL = pathlib.Path(os.environ.get("ARENA_MORTAL_ROOT", HOME / "Mortal")).resolve()


def build_mortal_bot(seat: int):
    """复刻 ~/Mortal/mortal/mortal.py 的标准分支加载（46 动作 .so 匹配 ckpt）。

    权重 = ARENA_MORTAL_WEIGHT 或 config['control']['state_file']（MORTAL_CFG 指
    的 config.toml）。joint(83) ckpt 请直接用 mortal.py 的 Tier-A 适配器路径，
    本 runner 不复刻。
    """
    sys.path.insert(0, str(MORTAL / "mortal"))
    import torch
    from model import Brain, DQN
    from engine import MortalEngine
    from libriichi.mjai import Bot
    from libriichi.consts import ACTION_SPACE
    from config import config

    use_cuda = os.environ.get("ARENA_DEVICE") == "cuda" and torch.cuda.is_available()
    dev = torch.device("cuda" if use_cuda else "cpu")
    weight = os.environ.get("ARENA_MORTAL_WEIGHT") or config["control"]["state_file"]
    state = torch.load(str(weight), weights_only=True, map_location="cpu")
    cfg = state["config"]
    version = cfg["control"].get("version", 1)
    rn = cfg.get("resnet", {})
    brain_kwargs = dict(
        version=version,
        num_blocks=rn["num_blocks"],
        conv_channels=rn["conv_channels"],
        split_conv=rn.get("split_conv", False),
        conv_out=rn.get("conv_out", 128),
        conv_extend_overview=rn.get("conv_extend_overview", False),
        keep_sp_turns=tuple(rn.get("keep_sp_turns", (0, 4))),
    )
    if version == 4:
        ckpt_action = state["current_dqn"]["net.weight"].shape[0] - 1
    else:
        ckpt_action = ACTION_SPACE
    if ckpt_action != ACTION_SPACE:
        raise SystemExit(
            f"ckpt 动作空间 {ckpt_action} 与 .so ACTION_SPACE {ACTION_SPACE} 不符；"
            f"标准 v4 权重（如 mortal-1090k）才能走本 runner")

    mortal = Brain(**brain_kwargs).eval().to(dev)
    dqn = DQN(version=version).eval().to(dev)
    mortal.load_state_dict(state["mortal"])
    dqn.load_state_dict(state["current_dqn"])
    engine = MortalEngine(
        mortal, dqn, version=version, is_oracle=False, device=dev,
        enable_amp=False, enable_quick_eval=True,
        enable_rule_based_agari_guard=True, name="mortal",
    )
    return Bot(engine, seat)


BUILDERS = {"mortal": build_mortal_bot}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, choices=sorted(BUILDERS))
    ap.add_argument("--seat", type=int, required=True)
    args = ap.parse_args()

    bot = BUILDERS[args.model](args.seat)
    print('{"type":"ready"}', flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        events = json.loads(line)
        last = None
        for ev in events:
            if r := bot.react(json.dumps(ev)):
                last = r
        out = json.loads(last) if last is not None else {"type": "none"}
        out.pop("meta", None)
        print(json.dumps(out), flush=True)


if __name__ == "__main__":
    main()

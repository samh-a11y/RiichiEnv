#!/usr/bin/env python3
"""统一 MJAI 子进程引擎 runner（跑在各模型匹配的 torch+.so python 里，如 conda mortal py3.12）。

协议（我方自定，规避各原生 bot 协议不一）：
  握手 : 建好 bot 后先输出一行 {"type":"ready"}，父进程据此确认就绪。
  stdin : 之后每行 = 一个 JSON 数组 = 该座 new_events() 的全部事件。
  stdout: 每行 = 一条动作 JSON（已去 meta）或 {"type":"none"}。

方言（kita↔nukidora）由父进程侧 dialect.py 处理，本 runner 纯透传。
出错时 traceback 直接写 stderr（父进程会转发），便于诊断。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

# arena3p/engines/mjai_runner.py -> riichienv/
RIICHIENV_ROOT = pathlib.Path(__file__).resolve().parents[2]
MORTAL3 = (RIICHIENV_ROOT.parent / "Mortal3").resolve()


def build_community_bot(seat: int):
    """community：经 arena3p/engines/_pkgs/community 这个我方 symlink package 解析其相对 import。"""
    sys.path.insert(0, str(RIICHIENV_ROOT))
    from arena3p.engines._pkgs.community import model as comm_model
    return comm_model.load_model(seat)  # -> 原生 libriichi.mjai.Bot


def build_joint_bot(seat: int):
    """joint-v2：sys.path 插入 Mortal3/mortal，复刻 mortal.py:31-57 的加载（权重写死绝对路径）。"""
    sys.path.insert(0, str(MORTAL3 / "mortal"))
    import torch
    from model import Brain, DQN
    from engine import MortalEngine
    from libriichi3p.mjai import Bot

    weight = MORTAL3 / "train" / "sl3p-joint-v2" / "archive" / "mortal.final.pth"
    state = torch.load(str(weight), weights_only=True, map_location="cpu")
    cfg = state["config"]
    version = cfg["control"].get("version", 1)
    num_blocks = cfg["resnet"]["num_blocks"]
    conv_channels = cfg["resnet"]["conv_channels"]

    mortal = Brain(version=version, num_blocks=num_blocks, conv_channels=conv_channels).eval()
    dqn = DQN(version=version).eval()
    mortal.load_state_dict(state["mortal"])
    dqn.load_state_dict(state["current_dqn"])

    engine = MortalEngine(
        mortal,
        dqn,
        version=version,
        is_oracle=False,
        device=torch.device("cpu"),
        enable_amp=False,
        enable_quick_eval=True,
        enable_rule_based_agari_guard=True,
        name="mortal",
    )
    return Bot(engine, seat)  # -> 原生 libriichi3p.mjai.Bot


BUILDERS = {"community": build_community_bot, "joint": build_joint_bot}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, choices=list(BUILDERS))
    ap.add_argument("--seat", type=int, required=True)
    args = ap.parse_args()

    bot = BUILDERS[args.model](args.seat)

    # 就绪握手
    sys.stdout.write(json.dumps({"type": "ready"}) + "\n")
    sys.stdout.flush()

    while True:
        line = sys.stdin.readline()
        if not line:  # EOF：父进程关闭 stdin
            break
        line = line.strip()
        if not line:
            continue
        events = json.loads(line)
        # 逐事件喂原生 react，取最后一条非 None 反应（一个 new_events 批最多末事件触发动作）
        last = None
        for ev in events:
            reaction = bot.react(json.dumps(ev, separators=(",", ":")))
            if reaction:
                last = reaction
        if last is None:
            out = {"type": "none"}
        else:
            out = json.loads(last)
            out.pop("meta", None)  # 去掉模型自带的 meta（与 community 原 bot.py 一致）
        sys.stdout.write(json.dumps(out, separators=(",", ":")) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()

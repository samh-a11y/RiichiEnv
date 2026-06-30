#!/usr/bin/env python3
"""review 阶段 2（重放比对）：用模型各自工程的【独立/原版推理代码】重放 gen_tapes 录的 tape，
比对每个决策点的 mjai 动作，算一致率（DoD：100%）。分模型分进程跑（joint 与 v8guard 都有
同名 `model` 包，同进程冲突），各自独立 import：
  - joint-mse：独立加载 libriichi3p + Mortal3/mortal 的 Brain/DQN/MortalEngine（quick_eval=T /
    agari_guard=T，与 arena build_joint_bot、与原生 mortal.py review_mode=0 逐参数同）+ libriichi3p.mjai.Bot。
  - v8guard：直接 import 同事 **原版** sanma_joint_api.SanmaV8GuardEngine（GUARD ON，sanma 标定默认
    参数）+ libriichi_sanma.mjai.Bot —— 与 arena build_v8guard_bot（我方手抄）逐决策点对照，抓任何偏差。

truth 侧走与 arena 子进程 runner **完全相同**的调用路径（同 .so 的 *.mjai.Bot 逐事件 react，
取最后非 None），故一致 == 接入链路（dialect / select / IPC / 手抄 guard）零偏差。

跑在 conda mortal（py3.12，有 torch + libriichi3p + libriichi_sanma + fastapi）：
  ~/miniconda3/envs/mortal/bin/python arena3p/review/replay_truth.py --model v8guard  --tape <t.jsonl>
  ~/miniconda3/envs/mortal/bin/python arena3p/review/replay_truth.py --model joint-mse --tape <t.jsonl>
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

MORTAL3 = pathlib.Path(os.environ.get("ARENA_MORTAL3", "/home/administrator/Mortal3"))


def build_truth_joint(seat, weight):
    """独立原生加载（= 原生 mortal.py review_mode=0 同配置）。"""
    sys.path.insert(0, str(MORTAL3 / "mortal"))
    import torch
    import libriichi3p  # noqa: F401
    from model import Brain, DQN
    from engine import MortalEngine
    from libriichi3p.mjai import Bot
    torch.set_num_threads(1)
    state = torch.load(weight, weights_only=True, map_location="cpu")
    cfg = state["config"]
    ver = cfg["control"].get("version", 1)
    nb = cfg["resnet"]["num_blocks"]
    cc = cfg["resnet"]["conv_channels"]
    brain = Brain(version=ver, num_blocks=nb, conv_channels=cc).eval()
    dqn = DQN(version=ver).eval()
    brain.load_state_dict(state["mortal"])
    dqn.load_state_dict(state["current_dqn"])
    eng = MortalEngine(brain, dqn, version=ver, is_oracle=False, device=torch.device("cpu"),
                       enable_amp=False, enable_quick_eval=True,
                       enable_rule_based_agari_guard=True, name="mortal")
    return Bot(eng, seat), eng


def build_truth_v8guard(seat):
    """同事原版：直接 import sanma_joint_api 的 SanmaV8GuardEngine（GUARD ON，sanma 标定默认参数）。"""
    G = MORTAL3 / "train" / "sanma_v8_guard"
    os.environ["SANMA_GUARD"] = "1"
    os.environ.setdefault("SANMA_V8", str(G / "runs" / "v8_bc" / "model.pth"))
    os.environ.setdefault("SANMA_DANGER", str(G / "runs" / "v8_danger" / "danger_head.pth"))
    os.environ.setdefault("SANMA_LOG_Q", "0")
    # 本地布局 .so 在 sanma_v8_guard/engine（api 自带 path 逻辑是远端 /root/sanma 布局，须先补本地）
    for p in (str(G / "engine"), str(G), str(G / "local_model")):
        sys.path.insert(0, p)
    import torch
    torch.set_num_threads(1)
    import sanma_joint_api as api  # 顶部：配 path + import libriichi_sanma + SanmaNet/SanmaDangerHead + fastapi
    eng = api.SanmaV8GuardEngine(model_path=api.V8_PATH, danger_path=api.DANGER_PATH, name="v8_guard")
    print(f"  v8guard truth: v8={api.V8_PATH} danger={api.DANGER_PATH} "
          f"floor={eng.danger_floor} gap={eng.danger_gap} margin={eng.ukeire_margin}", flush=True)
    return api.Bot(eng, seat), eng


def norm(a):
    """规范化 mjai 动作用于比对：去模型自带 meta；其余字段原样。"""
    a = dict(a)
    a.pop("meta", None)
    return a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, choices=["joint-mse", "joint", "v8guard", "v8"])
    ap.add_argument("--tape", required=True)
    ap.add_argument("--weight", help="joint 权重（默认 sl3p-joint-result/3p-mse-v1.1.pth）")
    ap.add_argument("--show", type=int, default=20, help="最多打印多少条不一致")
    args = ap.parse_args()

    lines = [json.loads(l) for l in open(args.tape) if l.strip()]
    meta = lines[0].get("_meta", {}) if lines and "_meta" in lines[0] else {}
    recs = [l for l in lines if "_meta" not in l]
    seat = meta.get("seat", 0)
    print(f"tape={args.tape} model={args.model} seat={seat} acts={len(recs)}", flush=True)

    if args.model in ("joint-mse", "joint"):
        weight = args.weight or str(MORTAL3 / "train" / "sl3p-joint-result" / "3p-mse-v1.1.pth")
        print(f"  joint truth 权重: {weight}", flush=True)
        bot, eng = build_truth_joint(seat, weight)
    else:
        bot, eng = build_truth_v8guard(seat)

    total = match = sel_fail = 0
    mism = []
    for idx, rec in enumerate(recs):
        last = None
        for ev in rec["events"]:
            r = bot.react(json.dumps(ev, separators=(",", ":")))
            if r:
                last = r
        truth = norm(json.loads(last) if last else {"type": "none"})
        arena = norm(rec["resp"])
        total += 1
        if truth == arena:
            match += 1
        else:
            mism.append((idx, arena, truth, rec["events"][-1] if rec["events"] else None))
        if rec.get("select_ok") is False:
            sel_fail += 1

    rate = match / total * 100 if total else 0.0
    print(f"\n一致: {match}/{total} = {rate:.4f}%   arena-side select 失败: {sel_fail}", flush=True)
    if mism:
        print(f"不一致 {len(mism)} 条（最多示 {args.show}）:", flush=True)
        for idx, a, t, ev in mism[:args.show]:
            print(f"  #{idx} 触发事件={ev}", flush=True)
            print(f"     arena={a}", flush=True)
            print(f"     truth={t}", flush=True)
    diag = [f"{a}={getattr(eng, a)}" for a in
            ("dahai_decisions", "guard_triggers", "aka_protected", "q_protected")
            if hasattr(eng, a)]
    if diag:
        print("  guard 诊断（truth 侧）: " + " ".join(diag), flush=True)
    passed = (match == total and sel_fail == 0)
    print(f"\n[{args.model}] {'PASS（100% 一致）' if passed else 'FAIL'}", flush=True)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

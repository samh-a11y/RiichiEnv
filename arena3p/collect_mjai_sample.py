#!/usr/bin/env python3
"""change-001 步骤 0/1：采集 RiichiEnv 3p-red-half 的 MJAI 事件流样例 + 方言探针。

用「优先稀有动作」策略驱动若干局三麻（强制触发拔北/立直/各类杠以覆盖事件 schema），落产物：
  - samples/godview_<tag>.jsonl   上帝视角全量日志（env.mjai_log，对手手牌可见）——供逐事件 schema diff。
  - samples/player<pid>_events_<tag>.jsonl  各座 obs.new_events() 累积流（对手手牌为 "?"）——真正喂各模型 bot 的输入。

并打印：god-view 事件类型统计 + 每种 MJAI 事件首例（供与 Mortal3 MJAI_SCHEMA_3P.md 逐字段 diff）。

跑法：uv run python arena3p/collect_mjai_sample.py [--kyoku N] [--seed S]
"""
import argparse
import json
import pathlib
from collections import Counter, OrderedDict

from riichienv import RiichiEnv, GameRule

OUT = pathlib.Path(__file__).parent / "samples"

# 稀有动作优先级（越靠前越优先选），目的是最大化事件 schema 覆盖
PRIORITY = ["KITA", "ANKAN", "KAKAN", "DAIMINKAN", "RIICHI", "PON"]


def rare_first(obs):
    """优先选稀有动作以覆盖事件类型；否则首个合法动作。"""
    acts = obs.legal_actions()
    by_type = {}
    for a in acts:
        t = str(a.action_type).split(".")[-1]
        by_type.setdefault(t, a)
    for t in PRIORITY:
        if t in by_type:
            return by_type[t]
    return acts[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="hanchan")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    env = RiichiEnv(game_mode="3p-red-half", rule=GameRule.default_tenhou())
    obs_dict = env.reset()
    per_player = {pid: [] for pid in range(env.num_players)}

    steps = 0
    while not env.done():
        for pid, obs in obs_dict.items():
            per_player.setdefault(pid, [])
            for ev in obs.new_events():
                per_player[pid].append(ev)
        actions = {pid: rare_first(obs) for pid, obs in obs_dict.items()}
        obs_dict = env.step(actions)
        steps += 1
        if steps > 5000:
            print("[warn] step 上限保护触发，提前停止")
            break
    for pid, obs in obs_dict.items():
        for ev in obs.new_events():
            per_player[pid].append(ev)

    god = env.mjai_log() if callable(env.mjai_log) else env.mjai_log

    god_path = OUT / f"godview_{args.tag}.jsonl"
    with god_path.open("w") as f:
        for ev in god:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    for pid, evs in per_player.items():
        p = OUT / f"player{pid}_events_{args.tag}.jsonl"
        with p.open("w") as f:
            for ev in evs:
                line = ev if isinstance(ev, str) else json.dumps(ev, ensure_ascii=False)
                f.write(line + "\n")

    print(f"steps={steps}  done={env.done()}")
    print(f"god-view events: {len(god)} -> {god_path}")
    for pid, evs in per_player.items():
        print(f"player{pid} new_events: {len(evs)}")
    print("scores:", env.scores(), " ranks:", env.ranks())

    c = Counter(ev.get("type") for ev in god)
    print("\ngod-view event types:", dict(c))

    # 每种事件首例（逐字段 diff 用）
    first = OrderedDict()
    for ev in god:
        t = ev.get("type")
        if t not in first:
            first[t] = ev
    print("\n=== god-view 每种事件首例 ===")
    for t, ev in first.items():
        print(json.dumps(ev, ensure_ascii=False))


if __name__ == "__main__":
    main()

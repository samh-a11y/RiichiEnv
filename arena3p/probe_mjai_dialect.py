#!/usr/bin/env python3
"""change-001 步骤 1：MJAI 方言探针。

验证两个方向的桥接：
  A. env 产出方向：god-view / new_events 里拔北用 "kita" 还是 "nukidora"，座位/kyoku/牌集边界。
  B. 动作收回方向：select_action_from_mjai 能否吃模型回的 {"type":"nukidora"}（Mortal 方言）
     与 {"type":"kita"}（RiichiEnv 方言），分别返回合法 Action 还是 None。

跑法：uv run python arena3p/probe_mjai_dialect.py
"""
import json
from riichienv import RiichiEnv, GameRule

PRIORITY = ["KITA", "ANKAN", "KAKAN", "DAIMINKAN", "RIICHI", "PON"]


def rare_first(obs):
    by = {}
    for a in obs.legal_actions():
        by.setdefault(str(a.action_type).split(".")[-1], a)
    for t in PRIORITY:
        if t in by:
            return by[t]
    return obs.legal_actions()[0]


def main():
    env = RiichiEnv(game_mode="3p-red-half", rule=GameRule.default_tenhou())
    obs = env.reset()

    # ---- B. 收回方向：第一次遇到 KITA 合法时做往返测试 ----
    kita_tested = False
    bakaze_seen, kyoku_seen, actor_seen, pai_seen = set(), set(), set(), set()
    steps = 0
    while not env.done() and steps < 5000:
        for pid, o in obs.items():
            for ev in o.new_events():
                d = json.loads(ev)
                t = d.get("type")
                if "bakaze" in d:
                    bakaze_seen.add(d["bakaze"])
                if t == "start_kyoku":
                    kyoku_seen.add(d["kyoku"])
                if "actor" in d:
                    actor_seen.add(d["actor"])
                for k in ("pai", "dora_marker"):
                    if k in d:
                        pai_seen.add(d[k])

            if not kita_tested:
                kita_act = None
                for a in o.legal_actions():
                    if str(a.action_type).split(".")[-1] == "KITA":
                        kita_act = a
                        break
                if kita_act is not None:
                    kita_tested = True
                    raw = kita_act.to_mjai()  # RiichiEnv 原生形态（JSON 字符串）
                    base = json.loads(raw) if isinstance(raw, str) else raw
                    print("=== B. 收回方向往返测试（拔北合法局面） ===")
                    print("kita_act.to_mjai():", json.dumps(base, ensure_ascii=False))
                    nukidora_dict = {"type": "nukidora", "actor": base["actor"], "pai": base.get("pai", "N")}
                    kita_dict = {"type": "kita", "actor": base["actor"], "pai": base.get("pai", "N")}
                    for name, d in [("nukidora(Mortal方言)", nukidora_dict), ("kita(RiichiEnv方言)", kita_dict)]:
                        try:
                            r = o.select_action_from_mjai(d)
                            print(f"  select_action_from_mjai({name}) -> {r!r}")
                        except Exception as e:
                            print(f"  select_action_from_mjai({name}) -> EXC {type(e).__name__}: {e}")

        actions = {pid: rare_first(o) for pid, o in obs.items()}
        obs = env.step(actions)
        steps += 1

    print("\n=== A. 产出方向边界 ===")
    print("bakaze 出现值:", sorted(bakaze_seen))
    print("kyoku  出现值:", sorted(kyoku_seen))
    print("actor  出现值:", sorted(actor_seen))
    man = sorted(p for p in pai_seen if p.endswith("m"))
    print("万子牌出现值（应无 2m-8m）:", man)
    print("kita_tested:", kita_tested)


if __name__ == "__main__":
    main()

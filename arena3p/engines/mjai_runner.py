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
    import os
    sys.path.insert(0, str(MORTAL3 / "mortal"))
    import torch
    from model import Brain, DQN
    from engine import MortalEngine
    from libriichi3p.mjai import Bot

    use_cuda = os.environ.get("ARENA_DEVICE") == "cuda" and torch.cuda.is_available()
    dev = torch.device("cuda" if use_cuda else "cpu")

    # 权重可经 ARENA_JOINT_WEIGHT 覆盖（默认 joint-v2；本任务=2 测用 sl3p-joint-result/3p-mse-v1.1.pth）。
    # 实测 3p-mse-v1.1 与 joint-v2 同构（version=4 / conv192 / blk40 / 同 config+mortal+current_dqn keys），
    # 故直接换权重路径即可（用户言「相关 mjai 接口已完备」）。
    weight = os.environ.get("ARENA_JOINT_WEIGHT") or str(
        MORTAL3 / "train" / "sl3p-joint-v2" / "archive" / "mortal.final.pth")
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
        device=dev,
        enable_amp=False,
        enable_quick_eval=True,
        enable_rule_based_agari_guard=True,
        name="mortal",
    )
    return Bot(engine, seat)  # -> 原生 libriichi3p.mjai.Bot


def build_v8_bot(seat: int):
    """v8（同事 gpuo BC 384x24 / obs575 / action44）：fetch 到 _pkgs/v8 的 .so+net+features+权重。

    guard **关闭**（不挂 danger head）。最小 engine 复刻同事 eval/agent_v2.SanmaV2Engine 的
    react_batch（鸭子类型，被 libriichi_sanma.mjai.Bot 调用），仅把 obs 改 575 / mask 改 44 /
    version=3 / SanmaNet 用 cfg.in_channels=575 装载。action 44 的 id→mjai 由 .so 内部映射。
    """
    import os
    import numpy as np
    import torch

    pkg = pathlib.Path(__file__).resolve().parent / "_pkgs" / "v8"
    sys.path.insert(0, str(pkg))  # libriichi_sanma.so + model/（SanmaNet）+ features/（consts）
    from model.net import SanmaNet
    from libriichi_sanma.mjai import Bot

    use_cuda = os.environ.get("ARENA_DEVICE") == "cuda" and torch.cuda.is_available()
    dev = torch.device("cuda" if use_cuda else "cpu")

    class SanmaV8Engine:
        engine_type = "mortal"          # 以下 4 个鸭子类型属性 Rust MortalBatchAgent 构造时读
        is_oracle = False
        enable_quick_eval = False
        enable_rule_based_agari_guard = False

        def __init__(self, model_path):
            self.name = "v8_bc"
            self.version = 3            # rich 575ch obs（必须 3）
            self.device = dev
            ck = torch.load(model_path, map_location="cpu", weights_only=False)
            cfg = ck["cfg"]             # {channels:384, blocks:24, in_channels:575, oracle:False}
            self.model = SanmaNet(channels=cfg["channels"], blocks=cfg["blocks"],
                                  in_channels=cfg["in_channels"])
            self.model.load_state_dict(ck["model"])
            self.model.to(dev).eval()

        def react_batch(self, states, masks, invisible_states):
            obs = torch.as_tensor(np.stack(states, 0), dtype=torch.float32, device=dev)  # (B,575,34)
            m = torch.as_tensor(np.stack(masks, 0), dtype=torch.bool, device=dev)         # (B,44)
            with torch.inference_mode():
                logits = self.model(obs)
            masked = logits.masked_fill(~m, float("-inf"))
            actions = masked.argmax(-1)
            q = torch.nan_to_num(masked, neginf=-1e9)  # 跨 py/rust 边界须有限值
            return actions.tolist(), q.tolist(), [x for x in masks], [True] * len(states)

    engine = SanmaV8Engine(str(pkg / "model.pth"))
    return Bot(engine, seat)  # -> 原生 libriichi_sanma.mjai.Bot


def build_v8guard_bot(seat: int):
    """v8 + guard（同事 sanma_v8_guard 完整版）：BC backbone + danger head + mitoshi 防守 guard。

    **精确复刻** 同事 sanma_joint_api.py `SanmaV8GuardEngine` 的 *defense-guard* 路径
    （sanma 标定参数 floor=0.10 / gap=0.05 / margin=2 + 赤dora 保护 0.25 + Q 保护 1.0）：
    在自家弃牌点用 danger 头 + 真实牌效枚数重排——不退向听 ∩ 枚数小让(≤margin) ∩ danger 显著
    更低(≥gap) 才换更安全张；赤5/强役(Q差≥1)不换。reach_suppress / tenpai_rescue **关**（与同事
    默认一致），故无需 /decide 层的 pending_own_discards / pending_genbutsu_all。

    资产经 env：ARENA_V8GUARD_DIR（含 model/net.py 44-action、features/、engine/.so、local_model/
    guard helpers）、ARENA_V8_DANGER（danger head 权重）。obs/version 同 v8（575ch / version=3）。
    """
    import os
    import numpy as np
    import torch

    gdir = pathlib.Path(os.environ["ARENA_V8GUARD_DIR"]).resolve()
    sys.path.insert(0, str(gdir))                  # model/(SanmaNet 44act) + features/(consts N_ACTIONS=44)
    sys.path.insert(0, str(gdir / "engine"))       # libriichi_sanma.so
    sys.path.insert(0, str(gdir / "local_model"))  # sanma_ukeire / mitoshi_sanma_guard
    from model.net import SanmaNet, SanmaDangerHead
    from libriichi_sanma.mjai import Bot
    from sanma_ukeire import ukeire_by_tile
    from mitoshi_sanma_guard import sanma_guard

    use_cuda = os.environ.get("ARENA_DEVICE") == "cuda" and torch.cuda.is_available()
    dev = torch.device("cuda" if use_cuda else "cpu")
    model_path = str(gdir / "runs" / "v8_bc" / "model.pth")
    danger_path = os.environ.get("ARENA_V8_DANGER",
                                 str(gdir / "runs" / "v8_danger" / "danger_head.pth"))

    # ---- sanma 标定 guard 参数（= sanma_joint_api SanmaV8GuardEngine 默认）。env 名与同事一致、
    # 默认值一致 → 正式跑（不设 env）两边等价；review 等价性压测可临时设宽松 env 强制走 guard 换牌路径。----
    FLOOR = float(os.environ.get("SANMA_GUARD_FLOOR", "0.10"))      # danger_floor
    GAP = float(os.environ.get("SANMA_GUARD_GAP", "0.05"))         # danger_gap
    MARGIN = int(os.environ.get("SANMA_GUARD_MARGIN", "2"))        # ukeire_margin
    AKA_GAP = float(os.environ.get("SANMA_GUARD_AKA_GAP", "0.25"))  # 赤dora 保护 gap
    Q_GAP = float(os.environ.get("SANMA_GUARD_Q_GAP", "1.0"))      # Q 保护 gap
    SEEN_PLANE = 463                       # obs 通道：tiles_seen / 4（同事实测唯一）
    TILES_34 = [f"{n}{s}" for s in "mps" for n in range(1, 10)] + ["E", "S", "W", "N", "P", "F", "C"]
    ID34 = {t: i for i, t in enumerate(TILES_34)}
    AKA_SLOT_T34 = {34: ID34["5m"], 35: ID34["5p"], 36: ID34["5s"]}  # 44-action 赤5 slot → deaka t34
    AKA_SLOTS = frozenset({34, 35, 36})

    def slot_to_t34(slot):
        return AKA_SLOT_T34[slot] if slot in AKA_SLOT_T34 else slot

    def aka_protect_skip(from_slot, to_slot, dng_from, dng_to):
        # 别为微小 danger 差把非红牌改判成会丢赤dora的红5；danger 大降(≥AKA_GAP)仍换（安全优先）
        if AKA_GAP > 0 and to_slot in AKA_SLOTS and from_slot not in AKA_SLOTS:
            return (dng_from - dng_to) < AKA_GAP
        return False

    class SanmaV8GuardEngine:
        engine_type = "mortal"          # 鸭子类型属性（Rust MortalBatchAgent 构造时读）
        is_oracle = False
        enable_quick_eval = False
        enable_rule_based_agari_guard = False

        def __init__(self):
            self.name = "v8_guard"
            self.version = 3            # rich 575ch obs（必须 3）
            self.device = dev
            ck = torch.load(model_path, map_location="cpu", weights_only=False)
            cfg = ck["cfg"]             # {channels:384, blocks:24, in_channels:575, oracle:False}
            self.model = SanmaNet(channels=cfg["channels"], blocks=cfg["blocks"],
                                  in_channels=cfg["in_channels"])
            self.model.load_state_dict(ck["model"])
            self.model.to(dev).eval()
            dh = torch.load(danger_path, map_location="cpu", weights_only=False)
            assert dh.get("concat_oracle") is False, \
                "danger head trained with oracle concat; obs mismatch"
            self.danger_head = SanmaDangerHead(channels=cfg["channels"], hidden=256)
            self.danger_head.load_state_dict(dh["head"])
            self.danger_head.to(dev).eval()

        def react_batch(self, states, masks, invisible_states):
            obs_np = np.stack(states, 0).astype(np.float32)        # (B,575,34)
            obs = torch.as_tensor(obs_np, device=dev)
            m = torch.as_tensor(np.stack(masks, 0), dtype=torch.bool, device=dev)  # (B,44)
            with torch.inference_mode():
                phi = self.model.features(obs)                     # (B,C,34) 冻结主干
                logits = self.model.head(phi)                      # (B,44)
                danger = torch.sigmoid(self.danger_head(phi))      # (B,34) 每张放铳风险
            masked = logits.masked_fill(~m, float("-inf"))
            actions = masked.argmax(-1)
            actions_list = actions.tolist()
            mask_np = m.cpu().numpy()                              # (B,44) bool
            danger_np = danger.cpu().numpy()                       # (B,34)

            for b, act in enumerate(actions_list):
                if act > 36:                                       # 非弃牌 → 不 guard
                    continue
                row_mask = mask_np[b]
                legal_slots = [s for s in range(37) if row_mask[s]]
                if len(legal_slots) < 2:
                    continue
                cur_t34 = slot_to_t34(act)
                # ★ 加速（动作严格等价）：sanma_guard 在 danger[cur]<FLOOR 时直接放行(不看 ukeire)，
                # 故提前跳过昂贵的 ukeire 枚举——实战大部分弃牌 danger<floor。float() 对齐原版 tolist
                # 口径；FLOOR=0 的压测下 danger>=0 必不跳过 → 完整 guard 路径仍被 review 覆盖。
                if float(danger_np[b][cur_t34]) < FLOOR:
                    continue
                # tile34 → emit slot（plain slot <34 优先 over aka >=34）
                t34_to_slot, legal_t34 = {}, []
                for s in legal_slots:
                    t = slot_to_t34(s)
                    if t not in t34_to_slot or s < t34_to_slot[t]:
                        t34_to_slot[t] = s
                    if t not in legal_t34:
                        legal_t34.append(t)
                # hand34（ch0..3）+ 手外可见（tiles_seen - hand34）。同事实测 hand34==PlayerState.tehai、
                # obs[463]*4==tiles_seen。
                row_obs = obs_np[b]                                # (575,34)
                hand34 = row_obs[0:4].sum(axis=0).round().astype(int).tolist()
                tiles_seen = (row_obs[SEEN_PLANE] * 4.0).round().astype(int)
                seen_out = [max(0, int(tiles_seen[t]) - hand34[t]) for t in range(34)]
                try:
                    uk = ukeire_by_tile(hand34, seen_out, legal_t34)
                except Exception:  # noqa: BLE001 -- 决策不能因 guard 计算崩
                    continue
                action_dict = {"type": "dahai", "pai": TILES_34[cur_t34], "tsumogiri": False}
                new_dict, info = sanma_guard(
                    action_dict, danger_np[b].tolist(), uk, legal_t34,
                    last_draw=None, reached=False,
                    ukeire_margin=MARGIN, danger_gap=GAP, danger_floor=FLOOR,
                )
                if info is not None:
                    to_t34 = ID34[new_dict["pai"]]
                    new_slot = t34_to_slot.get(to_t34)
                    if new_slot is not None and new_slot != act:
                        if aka_protect_skip(act, new_slot, info["dng_from"], info["dng_to"]):
                            continue
                        if Q_GAP > 0 and (masked[b, act].item()
                                          - masked[b, new_slot].item()) >= Q_GAP:
                            continue                               # 模型对原牌 Q 显著高（强役/打点）→ 不换
                        actions_list[b] = new_slot
            q = torch.nan_to_num(masked, neginf=-1e9)              # 跨 py/rust 边界须有限值
            return actions_list, q.tolist(), [x for x in masks], [True] * len(states)

    engine = SanmaV8GuardEngine()
    return Bot(engine, seat)  # -> 原生 libriichi_sanma.mjai.Bot


BUILDERS = {"community": build_community_bot, "joint": build_joint_bot,
            "v8": build_v8_bot, "v8guard": build_v8guard_bot}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, choices=list(BUILDERS))
    ap.add_argument("--seat", type=int, required=True)
    args = ap.parse_args()

    # 限 1 线程（配合 registry 的 OMP/MKL=1）：单样本推理不吃多线程，多对局并行避免过订阅
    try:
        import torch
        torch.set_num_threads(1)
    except Exception:
        pass

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

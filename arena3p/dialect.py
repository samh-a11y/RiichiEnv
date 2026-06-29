"""MJAI 三麻方言改写（按模型分；change-001 步骤1+2 实测）。

两类差异（详见 .claude/RESOURCES.md §C + Mortal3 cross_validate_community_so.py 的 17 步验证）：

1) 拔北命名：RiichiEnv 产出/接受 ``kita``；Mortal 系模型产出/期望 ``nukidora``。
   两个模型都需 kita→nukidora（喂入）/ nukidora→kita（收回）。

2) 座位数组形状：
   - joint（我们 libriichi3p，原生 3 座）：scores/tehais/deltas 均 3 元，与 RiichiEnv 一致 → 不改。
   - community（社区 .so，4 人格式 + 第 4 座掩码）：按座数组须补到 4 元。第 4 座为掩码幻影：
     scores 补 35000、tehais 补 13×"?"、deltas 补 0。actor/target 仍 0~2（社区 4 座引擎容忍 3 座轮转）。

收回方向（模型→env）的动作都是标准 3 座（actor∈0~2），除 nukidora→kita 外无需改写。
"""
from __future__ import annotations

_MASK13 = ["?"] * 13


def to_env(act: dict) -> dict:
    """模型回的动作 → 交给 ``select_action_from_mjai`` 前：``nukidora`` → ``kita``。"""
    if act.get("type") == "nukidora":
        act = dict(act)
        act["type"] = "kita"
    return act


def _kita_to_nukidora(ev: dict) -> dict:
    if ev.get("type") == "kita":
        ev = dict(ev)
        ev["type"] = "nukidora"
    return ev


def to_model_standard(ev: dict) -> dict:
    """原生 3 座模型（joint）：仅 kita→nukidora。"""
    return _kita_to_nukidora(ev)


def to_model_community(ev: dict) -> dict:
    """community（4 人格式 + 第 4 座掩码）：kita→nukidora + 按座数组 3→4 padding。"""
    ev = _kita_to_nukidora(ev)
    t = ev.get("type")
    if t == "start_kyoku":
        ev = dict(ev)
        if len(ev.get("scores", ())) == 3:
            ev["scores"] = list(ev["scores"]) + [35000]
        if len(ev.get("tehais", ())) == 3:
            ev["tehais"] = list(ev["tehais"]) + [list(_MASK13)]
    elif t in ("hora", "ryukyoku"):
        if len(ev.get("deltas", ())) == 3:
            ev = dict(ev)
            ev["deltas"] = list(ev["deltas"]) + [0]
    return ev


# registry 里每个模型选一个 env→model 事件改写器
DIALECTS = {
    "standard": to_model_standard,
    "community": to_model_community,
}

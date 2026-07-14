#!/usr/bin/env python3
"""合法性兜底匹配核验（change-003）：确认 OnlineMjaiClient._match / _sanitize 与服务器
select_action（riichienv-core observation/mjai_select.rs）的接受逻辑一致，尤其是 **ankan**。

真机 bug（Nosam ranked 日志）：服务器合法集里的 ankan 由 Rust `to_mjai` 生成，因合法动作
构造时 `tile=Some(lowest)`，会带上一个**冗余的 `pai` 字段**（`{"type":"ankan","pai":"E",
"consumed":["E","E","E","E"]}`）；而标准 mjai / qgrp bot 产出的 ankan **不带 `pai`**。旧
`_match` 对 ankan 比 `pai` → `"E" != None` → **每次暗杠都被误判非法 → 回退成打牌**（少一番/
宝牌指示牌不翻，实打实的对局损失）。服务器收到无 pai 的 ankan 时按 `consumed` 匹配、忽略 pai
（mjai_select.rs 的 pai 二次校验只对 chi/pon/daiminkan/kakan），故无需给出站 ankan 补 pai——
修法：`_match` 对 ankan/kita 只比 `consumed`，与服务器对齐。

纯逻辑测试，只依赖 stdlib（client.py 顶层不引 torch，模型懒加载）。跑法：
    cd /root/riichienv && PYTHONPATH=/root/riichienv \\
    python3 -m online3p.test_action_match
"""
from __future__ import annotations

import sys

from .client import OnlineMjaiClient

_match = OnlineMjaiClient._match


def main() -> None:
    # _sanitize 只用到 self.log；不跑 __init__ 造空壳即可
    c = OnlineMjaiClient.__new__(OnlineMjaiClient)
    c.log = lambda *a, **k: None

    failures: list[str] = []

    def check(name: str, cond: bool) -> None:
        print(("PASS" if cond else "FAIL"), name)
        if not cond:
            failures.append(name)

    # 服务器合法集 ankan（to_mjai：tile=Some → 带冗余 pai）vs bot ankan（无 pai）
    for pai, cons in (("E", ["E"] * 4), ("2s", ["2s"] * 4)):
        bot = {"type": "ankan", "actor": 0, "consumed": cons}
        srv = {"type": "ankan", "actor": 0, "pai": pai, "consumed": cons}
        check(f"match ankan {pai}（服务器带 pai / bot 不带）", _match(bot, srv))

    # 端到端：真机 legal 集（14×dahai + 1×ankan）应保留 ankan，不回退成 dahai
    pas = [{"type": "dahai", "actor": 0, "pai": p} for p in
           ["1m", "9m", "1p", "2p", "3p", "4p", "5p", "6p", "7p", "8p", "9p", "1s", "3s", "4s"]]
    pas.append({"type": "ankan", "actor": 0, "pai": "E", "consumed": ["E"] * 4})
    out = c._sanitize({"type": "ankan", "actor": 0, "consumed": ["E"] * 4}, pas)
    check("sanitize 保留 ankan（不回退 dahai）", out.get("type") == "ankan")

    # 不误伤：不同牌的暗杠不能互相匹配（consumed 不同）
    check("ankan 3s 不匹配服务器 ankan E",
          not _match({"type": "ankan", "actor": 0, "consumed": ["3s"] * 4},
                     {"type": "ankan", "actor": 0, "pai": "E", "consumed": ["E"] * 4}))

    # 无回归：kita 两侧都带 pai=N 仍匹配
    check("match kita（pai=N 两侧都有）",
          _match({"type": "kita", "actor": 0, "pai": "N"},
                 {"type": "kita", "actor": 0, "pai": "N"}))

    # 无回归：pon 仍按 pai 二次校验（同 consumed 不同 pai=aka → 不匹配，保持严格）
    check("pon 不同 pai 不匹配（保持严格）",
          not _match({"type": "pon", "actor": 0, "pai": "5p", "consumed": ["5p", "5p"]},
                     {"type": "pon", "actor": 0, "pai": "5pr", "consumed": ["5p", "5p"]}))
    check("pon 同 pai 匹配",
          _match({"type": "pon", "actor": 0, "pai": "5p", "consumed": ["5p", "5p"]},
                 {"type": "pon", "actor": 0, "pai": "5p", "consumed": ["5p", "5p"]}))

    # 无回归：dahai 仍按 pai 匹配
    check("dahai 匹配",
          _match({"type": "dahai", "actor": 0, "pai": "1m"},
                 {"type": "dahai", "actor": 0, "pai": "1m"}))
    check("dahai pai 不同不匹配",
          not _match({"type": "dahai", "actor": 0, "pai": "1m"},
                     {"type": "dahai", "actor": 0, "pai": "2m"}))

    # 红5核心修复：possible_actions 把红5 dahai 折叠成普通5（validate 实测），bot 输出 5pr/
    # 5sr。归一化后应命中（否则回退错牌＝"模型不认识红5"）。服务器实测照收 5pr/5sr。
    check("dahai 红5筒 5pr 命中折叠后的 5p",
          _match({"type": "dahai", "actor": 0, "pai": "5pr"},
                 {"type": "dahai", "actor": 0, "pai": "5p"}))
    check("dahai 红5索 5sr 命中折叠后的 5s",
          _match({"type": "dahai", "actor": 0, "pai": "5sr"},
                 {"type": "dahai", "actor": 0, "pai": "5s"}))
    # 端到端：bot 想摸切红5筒，合法集里红/非红 5p 都显示为 "5p"（真机 frame [4] 实况）→
    # 不回退、原样发 bot 的 5pr（服务器区分红/非红）
    pas_aka = [{"type": "dahai", "actor": 0, "pai": p} for p in
               ["1m", "1p", "2p", "3p", "4p", "5p", "5p", "6p", "6p", "4s", "7s", "9s"]]
    out_aka = c._sanitize({"type": "dahai", "actor": 0, "pai": "5pr",
                           "tsumogiri": True}, pas_aka)
    check("sanitize 保留 bot 的 5pr（不回退成第一张 1m）",
          out_aka.get("pai") == "5pr")
    # 不误伤：红5归一化不该让 5pr 匹配到 6p
    check("dahai 5pr 不匹配 6p",
          not _match({"type": "dahai", "actor": 0, "pai": "5pr"},
                     {"type": "dahai", "actor": 0, "pai": "6p"}))
    # melds 保持严格（未观察到平台折叠副露 aka）：pon pai 5p vs 5pr 仍不匹配——见上方
    # "pon 不同 pai 不匹配"，此处不重复。

    print("\n=>", "ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}")
    sys.exit(0 if not failures else 1)


if __name__ == "__main__":
    main()

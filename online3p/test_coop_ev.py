#!/usr/bin/env python3
"""协作 leaf_pt 数值核验（change-003）：确认 bot3p/ev.py 的 set_coop 严格等于
w_self·自家 − w_third·第三家，且权重可调、协作关闭时回到纯自家。

只用到 trans_core_3p + LeafTensors（start_kyoku 不过 qgrp net），但走完整
EvCalc3P 构造以贴近真实。跑法（gpu16b）：
    cd /root/riichienv
    PYTHONPATH=/root/Mortal3/mortal:/root/qgrp:/root/riichienv \\
    /root/aigc_apps/venv/bin/python3 -m online3p.test_coop_ev --device cpu
"""
from __future__ import annotations

import argparse


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qgrp-ckpt", default="/root/qgrp3p_run/qgrp3p_v3_ftb50k.pth")
    ap.add_argument("--trans-ckpt", default="/root/zeroppo-grp/grp_trans3p_v1.pth")
    ap.add_argument("--transcore-repo", default="/root/zeroppo-grp")
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()

    from bot3p.config import BotConfig3P
    from bot3p.ev import EvCalc3P

    def mk(**kw):
        return EvCalc3P(BotConfig3P(
            qgrp_ckpt=args.qgrp_ckpt, trans_ckpt=args.trans_ckpt,
            transcore_repo=args.transcore_repo, device=args.device, **kw))

    # ── 组1：默认权重 0.5/0.5，bonus/素点全关 ────────────────────
    ev = mk()
    entry = {"gk": 0, "honba": 0, "kyotaku": 0,
             "scores": [35000, 35000, 35000], "oya": 0}
    ev.clear_coop(); ev.start_kyoku(entry, 0); self0 = ev.leaf_pt.clone()
    ev.clear_coop(); ev.start_kyoku(entry, 2); third2 = ev.leaf_pt.clone()
    ev.set_coop(2, 0.5, 0.5); ev.start_kyoku(entry, 0); coop = ev.leaf_pt.clone()
    exp = 0.5 * self0 - 0.5 * third2
    err = float((coop - exp).abs().max())
    diff = float((coop - self0).abs().max())
    print(f"[组1] coop vs (0.5·self−0.5·third)  max|err|={err:.3e}")
    print(f"[组1] coop vs self（应显著≠0）        max|diff|={diff:.3e}")
    assert err < 1e-3, "协作 leaf_pt 不等于 0.5·self−0.5·third！"
    assert diff > 1e-3, "协作 leaf_pt 与自家无差异（可疑）"

    # ── 组2：非默认权重 0.7/0.3 + 素点权重开 + 非零 honba/kyotaku ──
    ev2 = mk(pt_per_1000=1.0)
    entry2 = {"gk": 1, "honba": 2, "kyotaku": 1,
              "scores": [40000, 30000, 35000], "oya": 1}
    ev2.clear_coop(); ev2.start_kyoku(entry2, 0); s2 = ev2.leaf_pt.clone()
    ev2.clear_coop(); ev2.start_kyoku(entry2, 2); t2 = ev2.leaf_pt.clone()
    ev2.set_coop(2, 0.7, 0.3); ev2.start_kyoku(entry2, 0); c2 = ev2.leaf_pt.clone()
    exp2 = 0.7 * s2 - 0.3 * t2
    err2 = float((c2 - exp2).abs().max())
    print(f"[组2] 权重0.7/0.3+素点 max|err|={err2:.3e}")
    assert err2 < 1e-3, "带权/素点下协作 leaf_pt 不匹配！"

    # ── 组3：clear_coop 后逐位回到纯自家 ─────────────────────────
    ev2.clear_coop(); ev2.start_kyoku(entry2, 0); s2b = ev2.leaf_pt.clone()
    err3 = float((s2b - s2).abs().max())
    print(f"[组3] clear_coop 回纯自家 max|err|={err3:.3e}")
    assert err3 < 1e-6, "clear_coop 未恢复纯自家！"

    print("PASS —— 协作 leaf_pt 数值全部核验通过")


if __name__ == "__main__":
    main()

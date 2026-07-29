#!/usr/bin/env python3
"""上线门禁通行证：把「过了哪些门」和**当前代码指纹**绑在一起。

2026-07-28 事故：改完 client.py 只做 `py_compile` 就上 ranked，结果每收一帧就
`AttributeError`（字段改名漏改一处引用）→ 断线重连 120+ 次 → bot 全程无法出牌 →
平台代打摸切，真实排位分受损。语法检查抓不到这类错误，必须跑运行时门。

于是：上线前跑 `go_live.sh`（回放门 + coop 判据门，均离线）→ 它 `stamp` 出通行证 →
Claude Code 的 PreToolUse hook 在拦到 ranked 上线命令时 `check`。**代码一改，指纹就变，
通行证立即失效**，必须重新过门。

⚠ 2026-07-29 起去掉了原门3（`/ws/validate` 拿 passed:true）：它要求先停机（同 JWT 双连
会把在跑的 bot 挤掉 → 又是摸切），每次上线都得停机过门，操作成本过高。代价是门禁不再
覆盖「平台协议/服务器行为发生变化」这类问题——只有离线两门 + 代码指纹。

指纹 = riichienv/online3p/*.py + workspace/hybrid/*.py 的内容哈希（上线链路的全部代码）。

用法：
  python online3p/gate.py stamp --gate replay --gate coop
  python online3p/gate.py check            # exit 0=有效，1=无效（打印原因）
  python online3p/gate.py fingerprint      # 只打印当前指纹
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import time

REPO = pathlib.Path(__file__).resolve().parents[1]          # riichienv/
HYBRID = pathlib.Path("/home/administrator/workspace/hybrid")
STAMP = pathlib.Path("/tmp/riichi_coop/.gate.json")
MAX_AGE_SEC = 7200.0        # 通行证时效：2 小时
REQUIRED = ("replay", "coop")


def code_files() -> list[pathlib.Path]:
    files = sorted((REPO / "online3p").glob("*.py"))
    if HYBRID.is_dir():
        files += sorted(HYBRID.glob("*.py"))
    return files


def fingerprint() -> str:
    h = hashlib.sha256()
    for f in code_files():
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def do_stamp(gates: list[str]) -> int:
    STAMP.parent.mkdir(parents=True, exist_ok=True)
    payload = {"fp": fingerprint(), "ts": time.time(),
               "gates": sorted(set(gates)),
               "files": len(code_files())}
    STAMP.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"通行证已签发：fp={payload['fp']} 门={payload['gates']} "
          f"（{payload['files']} 个源文件）→ {STAMP}")
    return 0


def do_check(max_age: float) -> int:
    if not STAMP.exists():
        print(f"❌ 没有通行证（{STAMP} 不存在）：上线前请跑 "
              f"`bash online3p/go_live.sh`")
        return 1
    try:
        p = json.loads(STAMP.read_text(encoding="utf-8"))
    except Exception as e:                     # noqa: BLE001
        print(f"❌ 通行证不可读（{e!r}）：重新跑 `bash online3p/go_live.sh`")
        return 1
    now, fp = time.time(), fingerprint()
    if p.get("fp") != fp:
        print(f"❌ 代码已变（通行证 fp={p.get('fp')} ≠ 当前 {fp}）："
              f"改过上线链路的代码就必须重新过门 `bash online3p/go_live.sh`")
        return 1
    age = now - float(p.get("ts", 0))
    if age > max_age:
        print(f"❌ 通行证过期（{age/60:.0f} 分钟前签发，上限 {max_age/60:.0f} 分钟）："
              f"重新跑 `bash online3p/go_live.sh`")
        return 1
    missing = [g for g in REQUIRED if g not in (p.get("gates") or [])]
    if missing:
        print(f"❌ 缺门 {missing}（已过 {p.get('gates')}）："
              f"跑 `bash online3p/go_live.sh` 补齐")
        return 1
    print(f"✅ 通行证有效：fp={fp} 门={p.get('gates')} "
          f"（{age/60:.1f} 分钟前签发）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("stamp")
    s.add_argument("--gate", action="append", default=[])
    c = sub.add_parser("check")
    c.add_argument("--max-age-sec", type=float, default=MAX_AGE_SEC)
    sub.add_parser("fingerprint")
    a = ap.parse_args()
    if a.cmd == "stamp":
        return do_stamp(a.gate)
    if a.cmd == "check":
        return do_check(a.max_age_sec)
    print(fingerprint())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

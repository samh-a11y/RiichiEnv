"""父进程侧（.venv，有 riichienv）：把一个 MJAI 子进程 runner 封装成 MjaiEngine。

act(obs) 流程：
  obs.new_events() → [kita→nukidora] → 发一行 JSON 数组给 runner
  → 读 runner 回的一条动作 → [nukidora→kita] → obs.select_action_from_mjai(dict)
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading

from .. import dialect
from . import registry
from .base import MjaiEngine


def _type_name(action_type) -> str:
    """Action3P.action_type（枚举）→ 名字，如 'PASS' / 'PON' / 'KITA'。"""
    return str(action_type).split(".")[-1]


class SubprocessMjaiEngine(MjaiEngine):
    def __init__(self, model_name: str, seat: int, record: bool = False):
        self.model_name = model_name
        self.seat = seat
        self.record = record       # review：录 (视角事件流, mjai动作) tape 供 ground truth 重放比对
        self.tape: list[dict] = []
        spec = registry.get_spec(model_name)
        # 按模型选 env→model 事件改写器（community 需 3→4 座 padding；joint 仅 kita→nukidora）
        self._to_model = dialect.DIALECTS[spec["dialect"]]
        # qgrp change-004：带 "argv" 工厂的 spec（先例 arena4p）自带协议入口，
        # 直接用工厂命令行；既有 python+runner_args spec 走原 mjai_runner 路径不变
        argv = spec.get("argv")
        cmd = argv(seat) if argv is not None else [
            spec["python"], "-m", "arena3p.engines.mjai_runner",
            *spec["runner_args"], "--seat", str(seat),
        ]
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=spec["env"],
            cwd=spec["cwd"],
        )
        # 转发子进程 stderr（带前缀）便于看 Traceback；daemon 线程随主进程退出
        self._stderr_thread = threading.Thread(target=self._pump_stderr, daemon=True)
        self._stderr_thread.start()
        self._await_ready()

    # ------------------------------------------------------------------
    def _pump_stderr(self):
        prefix = f"[{self.model_name}:{self.seat}] "
        try:
            for line in self.proc.stderr:
                sys.stderr.write(prefix + line)
                sys.stderr.flush()
        except Exception:
            pass

    def _await_ready(self):
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError(
                f"engine {self.model_name}:{self.seat} 启动即退出（见上方 stderr）"
            )
        msg = json.loads(line)
        if msg.get("type") != "ready":
            raise RuntimeError(
                f"engine {self.model_name}:{self.seat} 首行非 ready：{line!r}"
            )

    # ------------------------------------------------------------------
    def act(self, obs):
        events = [self._to_model(json.loads(e)) for e in obs.new_events()]
        self.proc.stdin.write(json.dumps(events, separators=(",", ":")) + "\n")
        self.proc.stdin.flush()

        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError(
                f"engine {self.model_name}:{self.seat} 读动作时 EOF（崩溃？见 stderr）"
            )
        resp = json.loads(line)

        select_ok = None   # None=resp 为 none（无需 select）；True/False=select 成 / 败
        if resp.get("type") == "none":
            result = self._resolve_none(obs)
        else:
            act = obs.select_action_from_mjai(dialect.to_env(resp))
            if act is None:
                sys.stderr.write(
                    f"[{self.model_name}:{self.seat}] WARN select_action_from_mjai 未匹配："
                    f"{json.dumps(resp, ensure_ascii=False)}；legals="
                    f"{[_type_name(a.action_type) for a in obs.legal_actions()]}\n"
                )
                result = self._resolve_none(obs)
                select_ok = False
            else:
                result = act
                select_ok = True

        if self.record:
            # events = dialect 改写后（与喂 truth Bot 同口径）；resp = runner 原始 mjai（已去 meta）
            self.tape.append({"events": events, "resp": resp, "select_ok": select_ok})
        return result

    def _resolve_none(self, obs):
        """bot 弃和/不鸣：优先映射成 PASS，绝不误退化成 legal[0]（可能是 pon）。"""
        a = obs.select_action_from_mjai({"type": "none"})
        if a is not None:
            return a
        for la in obs.legal_actions():
            if _type_name(la.action_type) == "PASS":
                return la
        legals = obs.legal_actions()
        return legals[0] if legals else None

    # ------------------------------------------------------------------
    def close(self):
        try:
            if self.proc.stdin and not self.proc.stdin.closed:
                self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass

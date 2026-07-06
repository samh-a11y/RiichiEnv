"""父进程侧（.venv，有 riichienv）：MJAI 子进程 runner → MjaiEngine（四麻版）。

与 arena3p 的差异：无方言改写（四麻即官方 MJAI），事件恒等透传。
协议：子进程首行 {"type":"ready"}；每行入一个 JSON 事件数组，出一条动作或 none。
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading

from . import registry
from .base import MjaiEngine


def _type_name(action_type) -> str:
    return str(action_type).split(".")[-1]


class SubprocessMjaiEngine(MjaiEngine):
    def __init__(self, model_name: str, seat: int):
        self.model_name = model_name
        self.seat = seat
        spec = registry.get_spec(model_name)
        self.proc = subprocess.Popen(
            spec["argv"](seat),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=spec["env"],
            cwd=spec["cwd"],
        )
        self._stderr_thread = threading.Thread(target=self._pump_stderr, daemon=True)
        self._stderr_thread.start()
        self._await_ready()

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
                f"engine {self.model_name}:{self.seat} 启动即退出（见上方 stderr）")
        msg = json.loads(line)
        if msg.get("type") != "ready":
            raise RuntimeError(
                f"engine {self.model_name}:{self.seat} 首行非 ready：{line!r}")

    def act(self, obs):
        events = [json.loads(e) for e in obs.new_events()]
        self.proc.stdin.write(json.dumps(events, separators=(",", ":")) + "\n")
        self.proc.stdin.flush()

        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError(
                f"engine {self.model_name}:{self.seat} 读动作时 EOF（崩溃？见 stderr）")
        resp = json.loads(line)

        if resp.get("type") == "none":
            return self._resolve_none(obs)
        act = obs.select_action_from_mjai(resp)
        if act is None:
            sys.stderr.write(
                f"[{self.model_name}:{self.seat}] WARN select_action_from_mjai "
                f"未匹配：{json.dumps(resp, ensure_ascii=False)}；legals="
                f"{[_type_name(a.action_type) for a in obs.legal_actions()]}\n")
            return self._resolve_none(obs)
        return act

    def _resolve_none(self, obs):
        """bot 弃和/不鸣：优先映射成 PASS，绝不误退化成 legal[0]。"""
        a = obs.select_action_from_mjai({"type": "none"})
        if a is not None:
            return a
        for la in obs.legal_actions():
            if _type_name(la.action_type) == "PASS":
                return la
        legals = obs.legal_actions()
        return legals[0] if legals else None

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

"""四麻 MJAI 引擎抽象（与 arena3p/engines/base.py 同构）。"""
from __future__ import annotations

from abc import ABC, abstractmethod


class MjaiEngine(ABC):
    @abstractmethod
    def act(self, obs):
        """喂 obs.new_events() 给模型，返回选定的合法 Action（或 None）。"""

    def close(self):
        pass

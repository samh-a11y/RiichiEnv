"""MjaiEngine 抽象基类：每个被测模型在父进程侧的统一句柄。"""
from __future__ import annotations

from abc import ABC, abstractmethod


class MjaiEngine(ABC):
    @abstractmethod
    def act(self, obs):
        """喂 ``obs.new_events()`` 给模型，返回选定的合法 Action（或 None=无合法匹配）。"""
        raise NotImplementedError

    def close(self):
        """释放底层资源（如子进程）。默认无操作。"""

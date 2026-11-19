"""随机延迟：所有等待都从区间内随机取值，避免固定节奏被风控识别。"""
from __future__ import annotations

import random
import time


class RateLimiter:
    """带记录的随机延迟器。

    ``delay((lo, hi))`` 睡一个 [lo, hi] 的随机秒数并返回该值；
    ``recorded`` 保存历史延迟（测试/调试用）。
    """

    def __init__(self, seed: int | None = None):
        self._rng = random.Random(seed)
        self.recorded: list = []

    def jitter(self, lo: float, hi: float) -> float:
        """返回 [lo, hi] 的随机数，不睡眠。"""
        return self._rng.uniform(lo, hi)

    def delay(self, delay_range: tuple) -> float:
        """睡眠一个 [lo, hi] 的随机秒数并返回。"""
        lo, hi = delay_range
        seconds = self._rng.uniform(lo, hi)
        self.recorded.append(seconds)
        time.sleep(seconds)
        return seconds

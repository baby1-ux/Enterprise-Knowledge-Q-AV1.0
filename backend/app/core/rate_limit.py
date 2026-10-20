"""登录防爆破：按用户名统计登录失败次数，连续失败达到上限后锁定一段时间。

内存实现（单机部署足够）：锁定信息随进程销毁而清除，重启服务后自动解锁。
只有「账号或密码错误」计入失败；验证码错误不消耗失败次数（未经验证的身份不应连坐）。
"""

from __future__ import annotations

import math
import threading
import time

from .logging import get_logger

logger = get_logger("rate_limit")


class LoginThrottle:
    """登录失败计数器：连续失败 max_attempts 次后锁定 lock_seconds 秒。"""

    def __init__(self, max_attempts: int = 5, lock_seconds: int = 600) -> None:
        self.max_attempts = max(1, int(max_attempts))
        self.lock_seconds = max(1, int(lock_seconds))
        # username(key 已小写) -> [失败次数, 锁定截止时间戳(0 表示未锁定)]
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def configure(self, max_attempts: int, lock_minutes: float) -> None:
        """按配置刷新阈值（应用启动时调用）。"""
        self.max_attempts = max(1, int(max_attempts))
        self.lock_seconds = max(1, int(lock_minutes * 60))
        logger.info("登录防爆破已配置：连续失败 %s 次锁定 %s 分钟", self.max_attempts, lock_minutes)

    # ------------------------------------------------------------------
    def check(self, username: str) -> tuple[bool, int]:
        """检查账号是否处于锁定状态，返回 (是否锁定, 剩余锁定分钟数)。"""
        key = self._key(username)
        now = time.time()
        with self._lock:
            self._cleanup_locked(now)
            item = self._failures.get(key)
            if item is None:
                return False, 0
            locked_until = item[1]
            if locked_until > now:
                return True, max(1, math.ceil((locked_until - now) / 60))
            return False, 0

    def record_failure(self, username: str) -> tuple[bool, int]:
        """记录一次登录失败；达到上限时锁定账号，返回 (是否已锁定, 剩余分钟数)。"""
        key = self._key(username)
        now = time.time()
        with self._lock:
            self._cleanup_locked(now)
            item = self._failures.setdefault(key, [0.0, 0.0])
            item[0] += 1
            if item[0] >= self.max_attempts:
                item[0] = 0.0
                item[1] = now + self.lock_seconds
                logger.warning(
                    "登录失败次数过多，账号已锁定 %s 分钟：username=%s", int(self.lock_seconds / 60), key
                )
                return True, max(1, math.ceil(self.lock_seconds / 60))
            return False, 0

    def record_success(self, username: str) -> None:
        """登录成功，清除失败记录。"""
        key = self._key(username)
        with self._lock:
            self._failures.pop(key, None)

    def clear(self) -> None:
        """清空全部记录（测试用）。"""
        with self._lock:
            self._failures.clear()

    # ------------------------------------------------------------------
    @staticmethod
    def _key(username: str) -> str:
        return (username or "").strip().lower()

    def _cleanup_locked(self, now: float) -> None:
        """清理已过锁定期的记录，避免内存无限增长（需持有锁调用）。

        注意：未锁定的记录锁定截止时间为 0，不能被当作“已过期”清掉，
        否则失败计数会在每次 check 时被清零，永远达不到锁定阈值。
        """
        expired = [key for key, item in self._failures.items() if item[1] > 0 and item[1] <= now]
        for key in expired:
            self._failures.pop(key, None)


# 全局单例，应用启动时按配置初始化
login_throttle = LoginThrottle()

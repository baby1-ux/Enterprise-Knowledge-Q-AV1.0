"""图形验证码：PIL 生成图片，内存 TTL 存储，一次性校验。"""

from __future__ import annotations

import base64
import io
import random
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, Tuple

from PIL import Image, ImageDraw, ImageFont

from .logging import get_logger

logger = get_logger("captcha")

# 去掉易混淆字符 0/O/1/I
_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """加载字体，找不到时退回 PIL 默认字体。"""
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:  # pragma: no cover - 字体损坏时继续尝试下一个
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1 不支持 size 参数
        return ImageFont.load_default()


def generate_captcha_code(length: int = 4) -> str:
    """生成指定长度的随机验证码文本。"""
    return "".join(random.choice(_CODE_ALPHABET) for _ in range(max(1, length)))


def render_captcha_image(code: str, width: int = 130, height: int = 44) -> str:
    """渲染验证码图片，返回 data URI（base64 PNG）。"""
    image = Image.new("RGB", (width, height), (245, 247, 252))
    draw = ImageDraw.Draw(image)

    # 背景干扰点
    for _ in range(120):
        draw.point(
            (random.randint(0, width), random.randint(0, height)),
            fill=(random.randint(150, 210), random.randint(150, 210), random.randint(200, 245)),
        )

    # 背景干扰线
    for _ in range(4):
        draw.line(
            (
                random.randint(0, width),
                random.randint(0, height),
                random.randint(0, width),
                random.randint(0, height),
            ),
            fill=(random.randint(150, 200), random.randint(150, 200), random.randint(200, 240)),
            width=1,
        )

    font = _load_font(int(height * 0.62))
    char_width = width / (len(code) + 1)
    for index, char in enumerate(code):
        color = (random.randint(40, 110), random.randint(40, 110), random.randint(140, 220))
        x = int(char_width * (index + 0.6))
        y = int(height * 0.18 + random.randint(-3, 3))
        draw.text((x, y), char, font=font, fill=color)

    # 干扰弧线
    for _ in range(2):
        draw.arc(
            (
                random.randint(-10, width // 2),
                random.randint(-10, height // 2),
                random.randint(width // 2, width + 10),
                random.randint(height // 2, height + 10),
            ),
            start=random.randint(0, 180),
            end=random.randint(180, 360),
            fill=(random.randint(150, 200), random.randint(150, 200), random.randint(220, 250)),
            width=2,
        )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


class CaptchaStore:
    """内存验证码存储（进程内，单机部署场景足够）。"""

    def __init__(self, expire_seconds: int = 300, length: int = 4, width: int = 130, height: int = 44) -> None:
        self.expire_seconds = expire_seconds
        self.length = length
        self.width = width
        self.height = height
        self._items: Dict[str, Tuple[str, float]] = {}
        self._lock = threading.Lock()

    def configure(self, expire_seconds: int, length: int, width: int, height: int) -> None:
        """按配置刷新参数（应用启动时调用）。"""
        self.expire_seconds = expire_seconds
        self.length = length
        self.width = width
        self.height = height

    def create(self) -> Tuple[str, str, str]:
        """创建验证码，返回 (captcha_id, code, image_data_uri)。"""
        code = generate_captcha_code(self.length)
        image = render_captcha_image(code, self.width, self.height)
        captcha_id = uuid.uuid4().hex
        with self._lock:
            self._cleanup_locked()
            self._items[captcha_id] = (code.upper(), time.time() + self.expire_seconds)
        logger.debug("生成验证码 captcha_id=%s", captcha_id)
        return captcha_id, code, image

    def verify(self, captcha_id: str, code: str) -> bool:
        """校验验证码（校验后立即失效）。"""
        if not captcha_id or not code:
            return False
        with self._lock:
            self._cleanup_locked()
            item = self._items.pop(captcha_id, None)
        if item is None:
            logger.info("验证码不存在或已被使用 captcha_id=%s", captcha_id)
            return False
        expected, expire_at = item
        if time.time() > expire_at:
            logger.info("验证码已过期 captcha_id=%s", captcha_id)
            return False
        ok = code.strip().upper() == expected
        if not ok:
            logger.info("验证码错误 captcha_id=%s", captcha_id)
        return ok

    def _cleanup_locked(self) -> None:
        now = time.time()
        expired = [key for key, (_, expire_at) in self._items.items() if expire_at < now]
        for key in expired:
            self._items.pop(key, None)

    def clear(self) -> None:
        """清空全部验证码（测试用）。"""
        with self._lock:
            self._items.clear()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._items)


# 全局单例，应用启动时按配置初始化
captcha_store = CaptchaStore()

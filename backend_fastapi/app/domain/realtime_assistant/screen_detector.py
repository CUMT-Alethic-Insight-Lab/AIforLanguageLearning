"""屏幕变化检测模块（实时助教 Token 节省策略 L2/L3）。

基于文档中的 ScreenChangeDetector 设计，实现：
- 分辨率下采样（保留鼠标轨迹）
- 感知哈希快速去重
- 像素级差异检测
- 冷却时间控制

当前为 CPU 实现，无需 GPU。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# 可选依赖：当 Pillow/imagehash 不可用时降级到基础哈希
try:
    IMAGEHASH_AVAILABLE = True
except Exception:
    IMAGEHASH_AVAILABLE = False


@dataclass
class ScreenChangeResult:
    changed: bool
    confidence: float = 0.0
    change_type: str = "none"  # initial | content | ui_noise | cooldown
    hash_diff: int | None = None
    resized_frame: bytes | None = None  # 下采样后的 JPEG bytes


class ScreenChangeDetector:
    """屏幕变化检测器 — 三级筛选（哈希→像素→OCR）。

    当前实现 L1/L2：哈希 + 像素差异。
    L3 OCR 文本对比由调用方在触发后执行。
    """

    RESOLUTIONS = {
        "1080p": (1920, 1080),
        "720p": (1280, 720),
        "480p": (854, 480),
    }

    def __init__(
        self,
        hash_threshold: int = 10,
        pixel_threshold: float = 0.05,
        target_resolution: str = "720p",
        cooldown_seconds: float = 3.0,
    ) -> None:
        self.hash_threshold = hash_threshold
        self.pixel_threshold = pixel_threshold
        self.target_resolution = self.RESOLUTIONS.get(target_resolution, (1280, 720))
        self.cooldown_seconds = cooldown_seconds
        self.last_trigger_time: float = 0.0
        self.last_hash: Any = None
        self.last_capture: bytes | None = None

    def detect_change(
        self, current_frame: bytes, *, format_hint: str = "jpeg"
    ) -> ScreenChangeResult:
        """检测屏幕是否发生显著变化。

        Args:
            current_frame: 当前帧图像数据（JPEG/PNG bytes）
            format_hint: 图像格式提示

        Returns:
            ScreenChangeResult
        """
        current_time = time.time()

        # 冷却检查
        if current_time - self.last_trigger_time < self.cooldown_seconds:
            return ScreenChangeResult(changed=False, change_type="cooldown")

        # 下采样（如果 Pillow 可用）
        resized = self._resize(current_frame, format_hint)
        if resized is None:
            # 无法处理图像时，首次视为变化，后续忽略
            if self.last_hash is None:
                return ScreenChangeResult(changed=True, change_type="initial", confidence=1.0)
            return ScreenChangeResult(changed=False, change_type="ui_noise")

        # 首次捕获
        if self.last_hash is None:
            self.last_trigger_time = current_time
            self.last_hash = self._compute_hash(resized)
            self.last_capture = resized
            return ScreenChangeResult(
                changed=True, change_type="initial", confidence=1.0, resized_frame=resized
            )

        # 1. 快速哈希检测
        current_hash = self._compute_hash(resized)
        hash_diff = self._hash_distance(self.last_hash, current_hash)

        if hash_diff < self.hash_threshold:
            # 快速返回：无明显变化
            return ScreenChangeResult(
                changed=False, change_type="ui_noise", hash_diff=hash_diff, resized_frame=resized
            )

        # 2. 像素级差异（若 Pillow 可用则做简单灰度差异）
        diff_ratio = self._pixel_diff_ratio(self.last_capture, resized)

        if diff_ratio > self.pixel_threshold:
            self.last_trigger_time = current_time
            self.last_hash = current_hash
            self.last_capture = resized
            return ScreenChangeResult(
                changed=True,
                change_type="content",
                confidence=diff_ratio,
                hash_diff=hash_diff,
                resized_frame=resized,
            )

        return ScreenChangeResult(
            changed=False, change_type="ui_noise", hash_diff=hash_diff, resized_frame=resized
        )

    # ── 内部工具 ──

    def _resize(self, image_bytes: bytes, format_hint: str) -> bytes | None:
        """将图像下采样到目标分辨率，返回 JPEG bytes。"""
        if not IMAGEHASH_AVAILABLE:
            return image_bytes
        try:
            from io import BytesIO

            from PIL import Image

            img = Image.open(BytesIO(image_bytes))
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img = img.resize(self.target_resolution, Image.Resampling.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=85)
            return buf.getvalue()
        except Exception as exc:
            logger.debug("Resize failed: %s", exc)
            return None

    def _compute_hash(self, image_bytes: bytes) -> Any:
        """计算感知哈希。"""
        if not IMAGEHASH_AVAILABLE:
            # 降级：使用 bytes 长度 + 首尾 64 bytes 做简单指纹
            return hash((len(image_bytes), image_bytes[:64], image_bytes[-64:]))
        try:
            from io import BytesIO

            from imagehash import phash
            from PIL import Image

            img = Image.open(BytesIO(image_bytes))
            if img.mode != "RGB":
                img = img.convert("RGB")
            return phash(img)
        except Exception as exc:
            logger.debug("Hash compute failed: %s", exc)
            return hash(image_bytes)

    @staticmethod
    def _hash_distance(a: Any, b: Any) -> int:
        """计算哈希差异。"""
        if isinstance(a, int) and isinstance(b, int):
            return abs(a - b)
        if IMAGEHASH_AVAILABLE and hasattr(a, "__sub__"):
            try:
                return int(a - b)
            except Exception:
                pass
        return 999  # 未知类型视为极大差异

    def _pixel_diff_ratio(self, img1_bytes: bytes | None, img2_bytes: bytes) -> float:
        """计算像素差异比例（简化版）。"""
        if not IMAGEHASH_AVAILABLE or img1_bytes is None:
            return 0.5  # 无法计算时保守返回
        try:
            from io import BytesIO

            import numpy as np
            from PIL import Image

            i1 = Image.open(BytesIO(img1_bytes)).convert("L")
            i2 = Image.open(BytesIO(img2_bytes)).convert("L")
            if i1.size != i2.size:
                return 1.0

            a1 = np.asarray(i1, dtype=np.int16)
            a2 = np.asarray(i2, dtype=np.int16)
            total = a1.size
            if total == 0:
                return 0.0
            return float((np.abs(a1 - a2) > 30).sum() / total)
        except Exception as exc:
            logger.debug("Pixel diff failed: %s", exc)
            return 0.5

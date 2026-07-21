from __future__ import annotations

import base64
import re
import tempfile
from pathlib import Path
from threading import RLock

_OCR_LOCK = RLock()
_OCR_ENGINE = None
_OCR_LANG = None


# OCR 适配器（优先 PaddleOCR）
# 说明：
# - 为了避免服务启动时强依赖 OCR 包，这里采用“懒加载”
# - 若 PaddleOCR 不可用，调用方会收到空字符串并自行走业务降级


def _normalize_image_b64(image_b64: str) -> bytes:
    raw = str(image_b64 or "").strip()
    if not raw:
        return b""

    # 兼容 data URL: data:image/png;base64,xxxx
    raw = re.sub(r"^data:image/[^;]+;base64,", "", raw, flags=re.IGNORECASE)
    try:
        return base64.b64decode(raw, validate=False)
    except Exception:
        return b""


def _map_lang(language: str) -> str:
    low = str(language or "").strip().lower()
    if low in ("en", "english", "en-us", "en-gb"):
        return "en"
    if low in ("ja", "jp", "japanese", "ja-jp"):
        return "japan"
    if low in ("zh", "zh-cn", "zh-hans", "chinese"):
        return "ch"
    return "en"


def _get_ocr_engine(lang: str):
    global _OCR_ENGINE, _OCR_LANG
    with _OCR_LOCK:
        if _OCR_ENGINE is not None and _OCR_LANG == lang:
            return _OCR_ENGINE

        from paddleocr import PaddleOCR  # type: ignore

        _OCR_ENGINE = PaddleOCR(use_textline_orientation=True, lang=lang, device="cpu")
        _OCR_LANG = lang
        return _OCR_ENGINE


def ocr_image_base64(image_b64: str, *, language: str = "english") -> str:
    payload = _normalize_image_b64(image_b64)
    if not payload:
        return ""

    lang = _map_lang(language)

    # PaddleOCR 接口对“文件路径输入”更稳定，这里写临时文件。
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(payload)

    try:
        # 主路径：PaddleOCR
        try:
            engine = _get_ocr_engine(lang)
            result = engine.predict(str(tmp_path))

            texts: list[str] = []
            # PaddleOCR 返回结构在不同版本会略有差异，这里做宽松解析：
            # - list[dict]（旧）
            # - list[OCRResult-like]（v3 常见：有 get() 但不是 dict）
            # - list[list[...]]（历史形态）
            for item in result or []:
                item_get = getattr(item, "get", None)

                if callable(item_get):
                    rec_texts = item_get("rec_texts")
                    if isinstance(rec_texts, list):
                        for t in rec_texts:
                            if isinstance(t, str) and t.strip():
                                texts.append(t.strip())
                elif isinstance(item, list):
                    for row in item:
                        if isinstance(row, (list, tuple)) and len(row) >= 2:
                            r2 = row[1]
                            if isinstance(r2, (list, tuple)) and len(r2) >= 1:
                                t = r2[0]
                                if isinstance(t, str) and t.strip():
                                    texts.append(t.strip())

            merged = "\n".join(texts).strip()
            if merged:
                return merged
        except Exception:
            # Paddle 失败时继续走兜底。
            pass

        # 兜底 1：尝试 rapidocr_onnxruntime（若已安装）。
        try:
            from rapidocr_onnxruntime import RapidOCR  # type: ignore

            engine2 = RapidOCR()
            out, _ = engine2(str(tmp_path))
            t2: list[str] = []
            for row in out or []:
                if isinstance(row, (list, tuple)) and len(row) >= 2:
                    text_item = row[1]
                    if isinstance(text_item, str) and text_item.strip():
                        t2.append(text_item.strip())
            merged2 = "\n".join(t2).strip()
            if merged2:
                return merged2
        except Exception:
            pass

        # 兜底 2：调用已有 wrapper（与旧后端一致），尽量复用现网可用链路。
        try:
            engine3 = _get_ocr_engine(lang)
            ocr_fn = getattr(engine3, "ocr", None)
            if callable(ocr_fn):
                rows = ocr_fn(str(tmp_path))
                t3: list[str] = []
                if isinstance(rows, list):
                    for page in rows:
                        if not isinstance(page, list):
                            continue
                        for item in page:
                            if not isinstance(item, (list, tuple)) or len(item) < 2:
                                continue
                            block = item[1]
                            if not isinstance(block, (list, tuple)) or len(block) < 1:
                                continue
                            text = str(block[0] or "").strip()
                            if text:
                                t3.append(text)
                merged3 = "\n".join(t3).strip()
                if merged3:
                    return merged3
        except Exception:
            pass

        return ""
    except Exception:
        return ""
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

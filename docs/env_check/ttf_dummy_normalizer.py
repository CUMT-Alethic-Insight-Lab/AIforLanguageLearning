# Simple TTF-like normalizer shim for CosyVoice text frontend swapping
# Two interfaces supported:
# - Classes ZhNormalizer/EnNormalizer with .normalize(text)
# - Or functions normalize_zh/normalize_en; or a unified normalize

import re

class ZhNormalizer:
    def normalize(self, text: str) -> str:
        # Minimal cleanup: strip, unify punctuation, remove brackets
        t = text.strip()
        t = t.replace("-", "，").replace(".", "。")
        t = re.sub(r"[\[\](){}<>]", "", t)
        t = re.sub(r"\s+", " ", t)
        return t

class EnNormalizer:
    def normalize(self, text: str) -> str:
        # Minimal cleanup: strip, collapse spaces, ensure sentence end
        t = text.strip()
        t = re.sub(r"\s+", " ", t)
        if t and t[-1].isalpha():
            t += "."
        return t

# Functional API alternatives

def normalize_zh(text: str) -> str:
    return ZhNormalizer().normalize(text)

def normalize_en(text: str) -> str:
    return EnNormalizer().normalize(text)

"""Token工具模块 - 提供Token计数和上下文压缩功能

支持多种Tokenizer:
- tiktoken (OpenAI模型)
- 本地模型的近似计数
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import threading
from typing import Any

# 尝试导入tiktoken，如果不存在则使用近似计数
try:
    import tiktoken
    from tiktoken import registry as tiktoken_registry

    TIKTOKEN_AVAILABLE = True
except ImportError:
    tiktoken = None
    tiktoken_registry = None
    TIKTOKEN_AVAILABLE = False


_ENCODING_RESOURCES: dict[str, tuple[tuple[str, str], ...]] = {
    "gpt2": (
        (
            "https://openaipublic.blob.core.windows.net/gpt-2/encodings/main/vocab.bpe",
            "1ce1664773c50f3e0cc8842619a93edc4624525b728b188a9e0be33b7726adc5",
        ),
        (
            "https://openaipublic.blob.core.windows.net/gpt-2/encodings/main/encoder.json",
            "196139668be63f3b5d6574427317ae82f612a97c5d1cdaf36ed2256dbf636783",
        ),
    ),
    "r50k_base": (
        (
            "https://openaipublic.blob.core.windows.net/encodings/r50k_base.tiktoken",
            "306cd27f03c1a714eca7108e03d66b7dc042abe8c258b44c199a7ed9838dd930",
        ),
    ),
    "p50k_base": (
        (
            "https://openaipublic.blob.core.windows.net/encodings/p50k_base.tiktoken",
            "94b5ca7dff4d00767bc256fdd1b27e5b17361d7b8a5f968547f9f23eb70d2069",
        ),
    ),
    "p50k_edit": (
        (
            "https://openaipublic.blob.core.windows.net/encodings/p50k_base.tiktoken",
            "94b5ca7dff4d00767bc256fdd1b27e5b17361d7b8a5f968547f9f23eb70d2069",
        ),
    ),
    "cl100k_base": (
        (
            "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken",
            "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7",
        ),
    ),
    "o200k_base": (
        (
            "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken",
            "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d",
        ),
    ),
    "o200k_harmony": (
        (
            "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken",
            "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d",
        ),
    ),
}

_TOKENIZER_LOCK = threading.RLock()
_TOKENIZER_CACHE: dict[str, Any | None] = {}
_LOCAL_ENCODING_CACHE: dict[str, bool] = {}


def _tiktoken_cache_dir() -> str:
    if "TIKTOKEN_CACHE_DIR" in os.environ:
        return os.environ["TIKTOKEN_CACHE_DIR"]
    if "DATA_GYM_CACHE_DIR" in os.environ:
        return os.environ["DATA_GYM_CACHE_DIR"]
    return os.path.join(tempfile.gettempdir(), "data-gym-cache")


def _cached_resource_is_valid(cache_dir: str, url: str, expected_hash: str) -> bool:
    cache_key = hashlib.sha1(url.encode()).hexdigest()
    cache_path = os.path.join(cache_dir, cache_key)
    try:
        digest = hashlib.sha256()
        with open(cache_path, "rb") as cached_file:
            for chunk in iter(lambda: cached_file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest() == expected_hash
    except OSError:
        return False


def _has_local_encoding_data(encoding_name: str) -> bool:
    cached = _LOCAL_ENCODING_CACHE.get(encoding_name)
    if cached is not None:
        return cached

    loaded_encodings = getattr(tiktoken_registry, "ENCODINGS", {})
    if encoding_name in loaded_encodings:
        _LOCAL_ENCODING_CACHE[encoding_name] = True
        return True

    resources = _ENCODING_RESOURCES.get(encoding_name)
    cache_dir = _tiktoken_cache_dir()
    available = bool(cache_dir and resources) and all(
        _cached_resource_is_valid(cache_dir, url, expected_hash)
        for url, expected_hash in resources
    )
    _LOCAL_ENCODING_CACHE[encoding_name] = available
    return available


def get_tokenizer(model_name: str = "gpt-3.5-turbo") -> Any:
    """
    获取适合模型的tokenizer
    
    Args:
        model_name: 模型名称
        
    Returns:
        tokenizer实例或None
    """
    if not TIKTOKEN_AVAILABLE:
        return None

    with _TOKENIZER_LOCK:
        if model_name in _TOKENIZER_CACHE:
            return _TOKENIZER_CACHE[model_name]

        try:
            encoding_name = tiktoken.encoding_name_for_model(model_name)
        except KeyError:
            encoding_name = "cl100k_base"
        except Exception:
            _TOKENIZER_CACHE[model_name] = None
            return None

        # tiktoken会在词表缓存缺失或损坏时自动联网下载。仅在确认本地数据完整时构造，
        # 保证默认运行和测试不依赖公网。
        if not _has_local_encoding_data(encoding_name):
            _TOKENIZER_CACHE[model_name] = None
            return None

        try:
            encoding = tiktoken.get_encoding(encoding_name)
        except Exception:
            encoding = None

        # None也缓存：构造失败后本进程不再反复尝试下载或等待网络超时。
        _TOKENIZER_CACHE[model_name] = encoding
        return encoding


def count_tokens(text: str, model_name: str = "gpt-3.5-turbo") -> int:
    """
    计算文本的Token数量
    
    Args:
        text: 输入文本
        model_name: 模型名称，用于选择tokenizer
        
    Returns:
        int: Token数量
    """
    if not text:
        return 0
    
    tokenizer = get_tokenizer(model_name)
    if tokenizer:
        try:
            tokens = tokenizer.encode(text)
            return len(tokens)
        except Exception:
            pass
    
    # 回退到近似计数
    return approximate_token_count(text)


def approximate_token_count(text: str) -> int:
    """
    近似Token计数（当tiktoken不可用时）
    
    经验法则：
    - 英文：1 token ≈ 4个字符或0.75个单词
    - 中文：1 token ≈ 1-2个字符
    
    Args:
        text: 输入文本
        
    Returns:
        int: 估计的Token数量
    """
    if not text:
        return 0
    
    # 统计字符数
    char_count = len(text)
    
    # 统计中文字符
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    
    # 统计英文单词
    english_words = len(re.findall(r'[a-zA-Z]+', text))
    
    # 估算：中文字符按1.5 token/字，英文按0.75 token/词，其他字符按0.25 token/字符
    estimated = int(
        chinese_chars * 1.5 +
        english_words * 0.75 +
        (char_count - chinese_chars) * 0.25
    )
    
    return max(1, estimated)


def count_messages_tokens(messages: list[dict[str, str]], model_name: str = "gpt-3.5-turbo") -> int:
    """
    计算消息列表的总Token数量
    
    OpenAI的token计算规则：
    - 每条消息额外消耗4个token（格式开销）
    - 角色名称消耗token
    - 内容消耗token
    
    Args:
        messages: OpenAI格式的消息列表
        model_name: 模型名称
        
    Returns:
        int: 总Token数量
    """
    if not messages:
        return 0
    
    total = 0
    
    for msg in messages:
        # 每条消息的格式开销
        total += 4
        
        # 角色名称
        role = msg.get("role", "")
        total += count_tokens(role, model_name)
        
        # 内容
        content = msg.get("content", "")
        total += count_tokens(content, model_name)
    
    # 对话格式额外开销
    total += 2
    
    return total


def truncate_by_tokens(
    text: str,
    max_tokens: int,
    model_name: str = "gpt-3.5-turbo",
    from_end: bool = True
) -> str:
    """
    按Token数量截断文本
    
    Args:
        text: 输入文本
        max_tokens: 最大Token数
        model_name: 模型名称
        from_end: 是否从末尾保留（True=保留末尾，False=保留开头）
        
    Returns:
        str: 截断后的文本
    """
    if not text:
        return text
    
    tokenizer = get_tokenizer(model_name)
    if tokenizer:
        try:
            tokens = tokenizer.encode(text)
            if len(tokens) <= max_tokens:
                return text
            
            if from_end:
                truncated = tokens[-max_tokens:]
            else:
                truncated = tokens[:max_tokens]
            
            return tokenizer.decode(truncated)
        except Exception:
            pass
    
    # 回退到字符截断（粗略估计）
    # 假设平均每个token约4个字符
    max_chars = max_tokens * 4
    
    if len(text) <= max_chars:
        return text
    
    if from_end:
        return "..." + text[-max_chars+3:]
    else:
        return text[:max_chars-3] + "..."


def summarize_context(
    messages: list[dict[str, str]],
    max_summary_tokens: int = 200,
    model_name: str = "gpt-3.5-turbo"
) -> str:
    """
    生成对话上下文的摘要
    
    当上下文超过Token限制时，将历史对话压缩为摘要。
    保留system消息，压缩user/assistant对话。
    
    Args:
        messages: 消息列表
        max_summary_tokens: 摘要的最大token数
        model_name: 模型名称
        
    Returns:
        str: 摘要文本
    """
    if not messages:
        return ""
    
    # 分离system消息和普通对话
    system_msgs = [m for m in messages if m.get("role") == "system"]
    conversation = [m for m in messages if m.get("role") != "system"]
    
    if not conversation:
        # 只有system消息，直接返回
        return "\n".join(m.get("content", "") for m in system_msgs)
    
    # 提取关键信息
    topics = []
    key_points = []
    
    for msg in conversation:
        content = msg.get("content", "").strip()
        if not content:
            continue
        
        role = msg.get("role", "")
        
        # 提取用户的主要话题（前50个字符）
        if role == "user":
            topic = content[:50] + "..." if len(content) > 50 else content
            topics.append(f"用户询问: {topic}")
        
        # 提取关键结论（包含"总结"、"结论"等的句子）
        elif role == "assistant":
            # 简单启发式：找包含关键词的句子
            sentences = re.split(r'[。！？.!?]', content)
            for sent in sentences:
                if any(kw in sent for kw in ["总结", "结论", "关键", "重要", "建议", "注意"]):
                    if len(sent) > 10:  # 过滤太短的片段
                        key_points.append(sent.strip())
                        break  # 只取第一个
    
    # 构建摘要
    summary_parts = []
    
    if system_msgs:
        system_content = system_msgs[0].get("content", "")
        if system_content:
            summary_parts.append(f"[场景设定: {system_content[:100]}...]")
    
    if topics:
        summary_parts.append("对话主题:")
        summary_parts.extend(topics[-3:])  # 最近3个主题
    
    if key_points:
        summary_parts.append("关键信息:")
        summary_parts.extend(key_points[-3:])  # 最近3个关键点
    
    summary = "\n".join(summary_parts)
    
    # 确保摘要不超长
    return truncate_by_tokens(summary, max_summary_tokens, model_name, from_end=False)


def compress_messages(
    messages: list[dict[str, str]],
    max_tokens: int = 4000,
    model_name: str = "gpt-3.5-turbo"
) -> list[dict[str, str]]:
    """
    压缩消息列表到指定Token数以内
    
    策略：
    1. 保留所有system消息
    2. 保留最近的几轮完整对话
    3. 更早的对话压缩为摘要
    
    Args:
        messages: 原始消息列表
        max_tokens: 最大Token数
        model_name: 模型名称
        
    Returns:
        list[dict[str, str]]: 压缩后的消息列表
    """
    if not messages:
        return messages
    
    current_tokens = count_messages_tokens(messages, model_name)
    if current_tokens <= max_tokens:
        return messages
    
    # 分离system消息
    system_msgs = [m for m in messages if m.get("role") == "system"]
    conversation = [m for m in messages if m.get("role") != "system"]
    
    system_tokens = count_messages_tokens(system_msgs, model_name)
    available_for_conv = max_tokens - system_tokens - 200  # 预留200给摘要
    
    if available_for_conv < 500:
        # 空间太小，只保留system和最后一轮
        if conversation:
            if len(conversation) >= 2:
                return system_msgs + conversation[-2:]
            return system_msgs + conversation
        return system_msgs
    
    # 从后往前找能完整保留的对话轮数
    preserved = []
    preserved_tokens = 0
    
    for msg in reversed(conversation):
        msg_tokens = count_tokens(msg.get("content", ""), model_name) + 4  # +4格式开销
        if preserved_tokens + msg_tokens <= available_for_conv * 0.6:  # 60%给完整对话
            preserved.insert(0, msg)
            preserved_tokens += msg_tokens
        else:
            break
    
    # 剩余部分生成摘要
    older_msgs = conversation[:-len(preserved)] if preserved else conversation
    if older_msgs:
        summary = summarize_context(older_msgs, int(available_for_conv * 0.4), model_name)
        if summary:
            summary_msg = {
                "role": "system",
                "content": f"[历史对话摘要] {summary}"
            }
            return system_msgs + [summary_msg] + preserved
    
    return system_msgs + preserved


# 导出函数
__all__ = [
    "count_tokens",
    "approximate_token_count",
    "count_messages_tokens",
    "truncate_by_tokens",
    "summarize_context",
    "compress_messages",
    "get_tokenizer",
    "TIKTOKEN_AVAILABLE",
]

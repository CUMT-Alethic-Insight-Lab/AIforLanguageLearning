from __future__ import annotations

import asyncio
import json
import re
from typing import Any, AsyncIterator

import httpx
from openai import AsyncOpenAI

from .prompts import render_prompt
from .runtime_config import get_runtime_config, get_scene_model, update_runtime_config
from .settings import settings

_LLM_MODEL_CACHE: str | None = None
_LLM_MODEL_LOCK = asyncio.Lock()


def _make_openai_client(
    base_url: str, api_key: str, timeout: httpx.Timeout
) -> AsyncOpenAI:
    """构造 OpenAI 兼容客户端（禁用 SDK 内置重试，重试策略由上层统一管理）。"""
    return AsyncOpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=timeout,
        max_retries=0,
    )


def _is_placeholder_model(model_id: str) -> bool:
    low = (model_id or "").strip().lower()
    return (not low) or low in {"local-model", "local-llm", "default"}


def _score_llm_model(model_id: str) -> tuple[int, str] | None:
    mid = (model_id or "").strip()
    if not mid:
        return None

    low = mid.lower()
    # 排除明显非聊天模型。
    if any(k in low for k in ("embedding", "whisper", "cosyvoice", "tts", "asr", "rerank")):
        return None

    m = re.search(r"(\d+)\s*b\b", low)
    size = int(m.group(1)) if m else 999

    # 常见“视觉模型/思考模型”在本项目默认链路里优先级降低。
    if "vl" in low:
        size += 200
    if "thinking" in low:
        size += 300
    if "coder" in low:
        size += 150
    # MoE 大总参数量模型（如 35B-A3B）虽然激活参数小，但加载/切换成本高
    if "a3b" in low or "a2b" in low or "moe" in low:
        size += 50

    return (size, mid)


def _rank_models(model_ids: list[str]) -> list[str]:
    scored: list[tuple[int, str]] = []
    for item in model_ids:
        s = _score_llm_model(item)
        if s is not None:
            scored.append(s)

    if scored:
        scored.sort(key=lambda x: x[0])
        return [x[1] for x in scored]

    # 如果都没命中评分规则，至少保留原始顺序里的非空值。
    out: list[str] = []
    for item in model_ids:
        t = str(item or "").strip()
        if t:
            out.append(t)
    return out


async def list_available_llm_models() -> list[str]:
    """从 OpenAI-compatible `/models` 拉取并过滤可用于对话的模型列表。"""

    timeout = httpx.Timeout(min(float(settings.llm_timeout_seconds), 8.0), connect=2.0)
    try:
        async with _make_openai_client(
            settings.llm_base_url, settings.llm_api_key, timeout
        ) as client:
            page = await client.models.list()
            ids = [
                m.id.strip() for m in page.data if isinstance(m.id, str) and m.id.strip()
            ]
    except Exception:
        cfg = get_runtime_config()
        cached = (((cfg.get("models") or {}).get("available") or []))
        return [str(x).strip() for x in cached if isinstance(x, str) and str(x).strip()]

    ranked = _rank_models(ids)
    # 始终使用排序后的最优模型作为 primary，不保留旧缓存。
    # 原因：本地 LM Studio 可能切换模型，旧缓存会导致错误调用大模型（如 35B）。
    primary = ranked[0] if ranked else ""

    update_runtime_config(
        {
            "models": {
                "available": ranked,
                "primary": primary,
            }
        }
    )
    return ranked


def _try_json_load(t: str) -> Any:
    try:
        return json.loads(t)
    except Exception:
        return None


def _strip_thinking(text: str) -> str:
    """Remove chain-of-thought / reasoning prefixes from LLM output.

    Handles patterns like:
    - "Thinking Process:\n...\n{...}"
    - "<think>...</think>"
    - "Reasoning: ...\nAnswer: ..."
    Returns only the final answer/JSON portion.
    """
    s = (text or "").strip()
    if not s:
        return ""

    # 1. Strip <think>...</think> blocks (common in Qwen/DeepSeek)
    if "<think>" in s.lower():
        s = re.sub(r"<think>.*?</think>", "", s, flags=re.DOTALL | re.IGNORECASE).strip()

    # 1b. Strip "Thinking Process:" blocks (common in reasoning models)
    if s.lower().startswith("thinking process:") or s.lower().startswith("thinking:"):
        # Reasoning models often place the actual JSON inside a ```json block
        # or at the end of the text.  Try code-fence first, then balanced braces.
        last_fence = s.rfind("```")
        if last_fence != -1:
            fence_start = s.rfind("```", 0, last_fence)
            if fence_start != -1:
                inner = s[fence_start + 3 : last_fence].strip()
                inner = re.sub(r"^json\s*", "", inner, flags=re.IGNORECASE).strip()
                if _try_json_load(inner):
                    return inner
        # Fallback: extract last balanced {...} block that parses as JSON.
        start = s.rfind("{")
        end = s.rfind("}")
        if start != -1 and end != -1 and start < end:
            candidate = s[start:end + 1]
            if _try_json_load(candidate):
                return candidate
        # If nothing works, still try the divider-based stripping below
        # so the rest of the function can attempt further extraction.

    # 2. Look for explicit dividers like "Construct JSON:", "Final Answer:", etc.
    dividers = [
        r"\n\s*\d+\s*\.\s*\*\*Construct JSON:\*\*\s*\n",
        r"\n\s*\*\*Construct JSON:\*\*\s*\n",
        r"\n\s*\d+\s*\.\s*Construct JSON:\s*\n",
        r"\n\s*Construct JSON:\s*\n",
        r"\n\s*Final Answer:\s*\n",
        r"\n\s*Answer:\s*\n",
        r"\n\s*Output:\s*\n",
        r"\n\s*Result:\s*\n",
    ]
    for pat in dividers:
        m = re.search(pat, s)
        if m:
            s = s[m.end():].strip()
            break

    # 3. If still contains thinking patterns or no valid JSON yet,
    #    try to extract the last parseable JSON object/array from the text.

    # Strip code fences first.
    cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", s, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned).strip()

    # Try the cleaned text directly.
    if _try_json_load(cleaned):
        return cleaned

    # Try all {...} and [...] blocks from longest to shortest.
    candidates: list[str] = []
    # Find balanced braces.
    for opener, closer in (("{", "}"), ("[", "]")):
        idx = 0
        while True:
            start = cleaned.find(opener, idx)
            if start == -1:
                break
            depth = 0
            for i in range(start, len(cleaned)):
                if cleaned[i] == opener:
                    depth += 1
                elif cleaned[i] == closer:
                    depth -= 1
                    if depth == 0:
                        candidates.append(cleaned[start : i + 1])
                        idx = i + 1
                        break
            else:
                break

    # Sort by length descending (prefer largest valid JSON).
    candidates.sort(key=len, reverse=True)
    for cand in candidates:
        if _try_json_load(cand):
            return cand

    # 4. Universal fallback: extract content from the last code fence regardless of prefix.
    last_fence = s.rfind("```")
    if last_fence != -1:
        fence_start = s.rfind("```", 0, last_fence)
        if fence_start != -1:
            inner = s[fence_start + 3 : last_fence].strip()
            inner = re.sub(r"^json\s*", "", inner, flags=re.IGNORECASE).strip()
            if _try_json_load(inner):
                return inner

    # 5. Final fallback: extract the last balanced {...} block that parses as JSON.
    start = s.rfind("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and start < end:
        candidate = s[start:end + 1]
        if _try_json_load(candidate):
            return candidate

    return s


def _extract_chat_response_text(data: Any) -> str:
    """Extract assistant text from an OpenAI-compatible chat.completions response.

    Some servers/models (notably certain "thinking" variants) may return an empty
    message.content while placing the actual text in message.reasoning_content.
    """

    if not isinstance(data, dict):
        return ""

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""

    c0 = choices[0] if isinstance(choices[0], dict) else {}
    msg = c0.get("message")
    if not isinstance(msg, dict):
        return ""

    content = msg.get("content")
    raw = ""
    if isinstance(content, str) and content.strip():
        raw = content.strip()

    # Some providers return content as structured parts.
    elif isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str) and part.strip():
                parts.append(part.strip())
            elif isinstance(part, dict):
                txt = part.get("text")
                if isinstance(txt, str) and txt.strip():
                    parts.append(txt.strip())
        if parts:
            raw = "\n".join(parts).strip()

    if not raw:
        reasoning = msg.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning.strip():
            raw = reasoning.strip()

    if raw:
        return _strip_thinking(raw)

    return ""


async def _resolve_llm_model(*, scene: str = "chat") -> str:
    """Resolve a usable model id for OpenAI-compatible servers.

    Strategy:
    - If user configured a non-placeholder model, use it.
    - Otherwise, return settings.llm_model (locked to configuration).
    """

    # 1) 场景模型（运行时配置）优先。
    scene_model = get_scene_model(scene)
    if scene_model and (not _is_placeholder_model(scene_model)):
        return scene_model

    # 2) 主模型（运行时配置）次之。
    cfg = get_runtime_config()
    primary = str(((cfg.get("models") or {}).get("primary") or "")).strip()
    if primary and (not _is_placeholder_model(primary)):
        return primary

    # 3) settings 默认模型（写死优先）。
    configured = str(getattr(settings, "llm_model", "qwen/qwen3.5-9b") or "").strip()
    if configured and (not _is_placeholder_model(configured)):
        return configured

    # Last resort: lock to qwen/qwen3.5-9b
    return "qwen/qwen3.5-9b"


def _extract_vocab_from_text(text: str) -> dict[str, Any]:
    s = (text or "").strip()
    if not s:
        return {"meaning": "", "example": "", "example_translation": "", "definitions": []}

    # Strip thinking / reasoning chains and code fences before parsing.
    s = _strip_thinking(s)

    def _maybe_fix_keys(raw: str) -> str:
        t = (raw or "").strip()
        if not t:
            return t
        # Fix patterns like: {" "meaning": ...} or {"  "example": ...}
        t = re.sub(
            r'"\s*"(meaning|example|example_translation|exampleTranslation)"',
            r'"\1"',
            t,
        )
        return t

    def _try_parse_obj(raw: str) -> Any:
        t = (raw or "").strip()
        if not t:
            return None

        # Strip code fences if present (handles ```json, ```javascript, etc.).
        t = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```\s*$", "", t).strip()

        # First attempt: direct JSON.
        try:
            return json.loads(t)
        except Exception:
            pass

        # If it looks like escaped JSON (e.g. {\"definitions\":...}), unescape quotes/backslashes.
        if "\\\"" in t and (t.startswith("{\\\"") or t.startswith("[\\\"")):
            candidate = t.replace("\\\"", '"').replace("\\\\", "\\")
            candidate = _maybe_fix_keys(candidate)
            try:
                return json.loads(candidate)
            except Exception:
                pass

        # Extract the largest {...} block and retry.
        if "{" in t and "}" in t:
            start = t.find("{")
            end = t.rfind("}")
            if 0 <= start < end:
                candidate = t[start : end + 1]
                candidate = _maybe_fix_keys(candidate)
                try:
                    return json.loads(candidate)
                except Exception:
                    pass

                # Retry after unescaping common patterns.
                if "\\\"" in candidate:
                    candidate2 = candidate.replace("\\\"", '"').replace("\\\\", "\\")
                    candidate2 = _maybe_fix_keys(candidate2)
                    try:
                        return json.loads(candidate2)
                    except Exception:
                        pass

        return None

    # Try JSON first.
    obj = _try_parse_obj(s)
    if isinstance(obj, str):
        # Double-decode if model returned a JSON string.
        obj2 = _try_parse_obj(obj)
        if obj2 is not None:
            obj = obj2

    if isinstance(obj, dict):
        defs = obj.get("definitions")
        if isinstance(defs, list):
            parsed_defs: list[dict[str, str]] = []
            for item in defs:
                if not isinstance(item, dict):
                    continue
                meaning = str(item.get("meaning") or item.get("definition") or "").strip()
                example = str(item.get("example") or item.get("example_en") or "").strip()
                example_translation = str(
                    item.get("example_translation")
                    or item.get("exampleTranslation")
                    or item.get("example_zh")
                    or ""
                ).strip()
                if meaning or example or example_translation:
                    parsed_defs.append(
                        {
                            "meaning": meaning,
                            "example": example,
                            "example_translation": example_translation,
                        }
                    )
            return {
                "meaning": str(obj.get("meaning") or obj.get("definition") or "").strip(),
                "example": "",
                "example_translation": "",
                "definitions": parsed_defs,
            }

        return {
            "meaning": str(obj.get("meaning") or obj.get("definition") or "").strip(),
            "example": str(obj.get("example") or obj.get("example_en") or "").strip(),
            "example_translation": str(
                obj.get("example_translation")
                or obj.get("exampleTranslation")
                or obj.get("example_zh")
                or ""
            ).strip(),
            "definitions": [],
        }

    # NOTE: JSON-in-text extraction is handled by _try_parse_obj above.

    def _clean_line(line: str) -> str:
        t = (line or "").strip()
        t = re.sub(r"^\s*(?:\d+\.|[-•]+)\s*", "", t)
        return t.strip()

    lines = [_clean_line(x) for x in s.splitlines() if _clean_line(x)]
    if len(lines) == 1:
        one = lines[0]
        # Split combined one-liners.
        one = re.sub(r"(例句翻译|例句|释义)\s*[:：]", r"\n\1：", one)
        lines = [_clean_line(x) for x in one.splitlines() if _clean_line(x)]

    meaning = ""
    example = ""
    example_translation = ""
    for line in lines:
        m = re.match(r"^释义\s*[:：]\s*(.+)$", line)
        if m:
            meaning = m.group(1).strip()
            continue

        m = re.match(r"^(?:例句翻译|翻译)\s*[:：]\s*(.+)$", line)
        if m:
            example_translation = m.group(1).strip()
            continue

        m = re.match(r"^例句\s*[:：]\s*(.+)$", line)
        if m:
            example = m.group(1).strip()
            continue

    if not (meaning or example or example_translation):
        meaning = s

    return {"meaning": meaning, "example": example, "example_translation": example_translation, "definitions": []}


async def generate_vocab_fields(term: str) -> dict[str, Any]:
    """Generate structured vocab fields via LM Studio (OpenAI compatible).

    Returns keys:
    - meaning (zh)
    - example (en)
    - example_translation (zh)

    Must be resilient: LLM may be unavailable or output non-JSON.
    """

    t = (term or "").strip()
    if not t:
        return {"meaning": "", "example": "", "example_translation": "", "definitions": []}

    def _should_expand(term_text: str) -> bool:
        low = (term_text or "").strip().lower()
        if not low:
            return False
        # Phrases usually have one primary meaning.
        if " " in low:
            return False
        # Heuristic: very short/common function words and classic polysemy verbs.
        common = {
            "to",
            "in",
            "on",
            "at",
            "for",
            "as",
            "by",
            "up",
            "down",
            "over",
            "set",
            "run",
            "get",
            "make",
            "take",
            "go",
            "come",
            "put",
            "turn",
            "right",
            "left",
            "like",
            "can",
            "will",
            "may",
        }
        return len(low) <= 3 or low in common

    prompt = (
        "你是一个外语学习助手。请为给定英文词/短语生成结构化结果。\n"
        f"term: {t}\n"
        "要求：\n"
        "- 如果确实有多个常用义项/用法，请返回多个义项（不必强行凑数）。\n"
        "- 每条义项都要有：meaning(中文释义)、example(英文例句)、example_translation(中文翻译)。\n"
        "- meaning 要简洁但完整（可以包含 1-2 个短语解释/用法提示）。\n"
        "- 只输出一个 JSON 对象，不要输出任何多余文本/Markdown/代码块。\n"
        'JSON schema: {"definitions":[{"meaning":"...","example":"...","example_translation":"..."}, ...]}'
    )

    expand_prompt = (
        "你是一个外语学习助手。请为给定英文词生成更全面的多义项解释。\n"
        f"term: {t}\n"
        "要求：\n"
        "- 给出尽可能多的常见义项/用法（优先常用、真实；不要生造冷门）。\n"
        "- 对于像 to/in/on/at 这类介词/功能词：给出多个最常用的用法，并各配一个英文例句与中文翻译。\n"
        "- 每条义项都要有：meaning(中文释义)、example(英文例句)、example_translation(中文翻译)。\n"
        "- 只输出一个 JSON 对象，不要输出任何多余文本/Markdown/代码块。\n"
        'JSON schema: {"definitions":[{"meaning":"...","example":"...","example_translation":"..."}, ...]}'
    )

    # Keep connect failures fast and cap total time so the API stays responsive.
    # Vocab generation is still allowed a bit longer to let local models respond.
    effective = min(float(settings.llm_timeout_seconds), 25.0)
    timeout = httpx.Timeout(effective, connect=min(2.0, effective))

    try:
        async with _make_openai_client(
            settings.llm_base_url, settings.llm_api_key, timeout
        ) as client:
            model = await _resolve_llm_model(scene="vocab")

            async def _translate_example_to_zh(example_en: str) -> str:
                ex = (example_en or "").strip()
                if not ex:
                    return ""
                translate_prompt = (
                    "把下面这句英文例句翻译成中文。只输出中文翻译本身，不要输出任何多余内容。\n"
                    f"英文：{ex}"
                )
                r = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": translate_prompt},
                    ],
                    temperature=0.0,
                    max_tokens=160,
                )
                txt = _extract_chat_response_text(r.model_dump())
                return (txt or "").strip().strip('"')

            async def _request_vocab_json(user_prompt: str) -> str:
                r = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant. Respond with valid JSON only. Do not output any thinking process, reasoning, or explanation. Output ONLY the JSON object, nothing else."},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.2,
                    max_tokens=700,
                )
                return _extract_chat_response_text(r.model_dump())

            text = ""
            parsed: dict[str, Any] = {}
            for _attempt in range(5):
                text = await _request_vocab_json(prompt)
                if text:
                    parsed = _extract_vocab_from_text(text)
                    defs = parsed.get("definitions")
                    if isinstance(defs, list) and defs:
                        break
                await asyncio.sleep(0.5)
            else:
                defs = []

            if isinstance(defs, list) and defs:
                normalized_defs: list[dict[str, str]] = []
                for d in defs:
                    if not isinstance(d, dict):
                        continue
                    meaning = str(d.get("meaning") or "").strip()
                    example = str(d.get("example") or "").strip()
                    example_translation = str(d.get("example_translation") or "").strip()

                    if example and not example_translation:
                        try:
                            example_translation = await _translate_example_to_zh(example)
                        except Exception:
                            example_translation = ""

                    if example and not example_translation:
                        example_translation = "暂无"

                    if meaning or example or example_translation:
                        normalized_defs.append(
                            {
                                "meaning": meaning,
                                "example": example,
                                "example_translation": example_translation,
                            }
                        )

                # If result looks incomplete for common/polysemous terms, retry once with an explicit expand prompt.
                if len(normalized_defs) < 2 and _should_expand(t):
                    try:
                        t2 = await _request_vocab_json(expand_prompt)
                        if t2:
                            p2 = _extract_vocab_from_text(t2)
                            d2 = p2.get("definitions")
                            if isinstance(d2, list) and d2:
                                for d in d2:
                                    if not isinstance(d, dict):
                                        continue
                                    m2 = str(d.get("meaning") or "").strip()
                                    e2 = str(d.get("example") or "").strip()
                                    z2 = str(d.get("example_translation") or "").strip()
                                    if e2 and not z2:
                                        try:
                                            z2 = await _translate_example_to_zh(e2)
                                        except Exception:
                                            z2 = ""
                                    if e2 and not z2:
                                        z2 = "暂无"
                                    if m2 or e2 or z2:
                                        normalized_defs.append(
                                            {
                                                "meaning": m2,
                                                "example": e2,
                                                "example_translation": z2,
                                            }
                                        )
                    except Exception:
                        pass

                # De-duplicate by meaning text.
                deduped: list[dict[str, str]] = []
                seen: set[str] = set()
                for d in normalized_defs:
                    key = (d.get("meaning") or "").strip()
                    if not key:
                        continue
                    if key in seen:
                        continue
                    seen.add(key)
                    deduped.append(d)

                if deduped:
                    # Keep legacy top-level keys for backward compatibility.
                    first = deduped[0]
                    return {
                        "meaning": first.get("meaning") or "",
                        "example": first.get("example") or "",
                        "example_translation": first.get("example_translation") or "",
                        "definitions": deduped,
                    }

            # Legacy single-definition shape or fallback.
            meaning = str(parsed.get("meaning") or "").strip()
            example = str(parsed.get("example") or "").strip()
            example_translation = str(parsed.get("example_translation") or "").strip()

            if example and (not example_translation or example_translation == "暂无"):
                try:
                    example_translation = await _translate_example_to_zh(example)
                except Exception:
                    example_translation = example_translation or ""

            if example and not example_translation:
                example_translation = "暂无"

            return {
                "meaning": meaning,
                "example": example,
                "example_translation": example_translation,
                "definitions": [],
            }
    except Exception:
        return {
            "meaning": "暂无（服务暂时不可用，请稍后再试）",
            "example": "暂无",
            "example_translation": "暂无",
            "definitions": [],
        }

    return {"meaning": "暂无（LLM 输出为空）", "example": "暂无", "example_translation": "暂无", "definitions": []}


async def generate_definition(term: str) -> str:
    """尽力从 LM Studio（OpenAI 兼容）生成一个简短释义。

    约束：
    - 不能依赖 LLM 一定可用（本地服务可能未启动）
    - 超时要短，失败要快速降级
    """

    prompt = (
        "你是一个外语学习助手。请用简洁中文解释这个英文词/短语，并给一个例句。\n"
        f"词：{term}\n"
        "输出格式：\n释义：...\n例句：..."
    )

    effective = min(float(settings.llm_timeout_seconds), 15.0)
    timeout = httpx.Timeout(effective, connect=min(2.0, effective))

    try:
        async with _make_openai_client(
            settings.llm_base_url, settings.llm_api_key, timeout
        ) as client:
            model = await _resolve_llm_model(scene="vocab")
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
            )
            data = resp.model_dump()
            # OpenAI 兼容：choices[0].message.content
            text = _extract_chat_response_text(data)
            if text:
                return text
    except Exception:
        # 降级：不抛出，保持服务可用
        return "释义：暂无（服务暂时不可用，请稍后再试）\n例句：暂无"

    return "释义：暂无\n例句：暂无"


def _build_chat_messages(
    *,
    system_prompt: str,
    user_text: str,
    history: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]

    if history:
        for item in history:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": user_text})
    return messages


async def chat_complete(
    *,
    system_prompt: str,
    user_text: str,
    history: list[dict[str, str]] | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.7,
) -> str:
    """Generate a single-turn chat completion using an explicit system prompt.

    Used by voice dialogue. Must be resilient: failures should degrade quickly.
    """

    sp = (system_prompt or "").strip() or "You are a helpful assistant."
    ut = (user_text or "").strip()
    if not ut:
        return "（未检测到语音内容）"

    effective = min(float(settings.llm_timeout_seconds), 15.0)
    timeout = httpx.Timeout(effective, connect=min(2.0, effective))
    resolved_base_url = str(base_url or "").strip() or settings.llm_base_url
    resolved_api_key = str(api_key or "").strip() or settings.llm_api_key

    try:
        async with _make_openai_client(resolved_base_url, resolved_api_key, timeout) as client:
            resolved_model = str(model or "").strip()
            if not resolved_model:
                resolved_model = await _resolve_llm_model(scene="chat")
            resp = await client.chat.completions.create(
                model=resolved_model,
                messages=_build_chat_messages(system_prompt=sp, user_text=ut, history=history),
                temperature=temperature,
            )
            data = resp.model_dump()
            text = _extract_chat_response_text(data)
            if text:
                return text
    except Exception:
        return "（网络不太稳定，请稍后再试）"

    return "（LLM 输出为空）"


async def chat_complete_race(
    *,
    system_prompt: str,
    user_text: str,
    history: list[dict[str, str]] | None = None,
    temperature: float = 0.7,
) -> str:
    """同时调用云端（Kimi）和本地模型，谁先成功返回用谁。

    适用于实时助教等对能力上限要求高、且延迟敏感的场景。
    若 Kimi 未配置，直接回退到本地。
    """
    sp = (system_prompt or "").strip() or "You are a helpful assistant."
    ut = (user_text or "").strip()
    if not ut:
        return "（未检测到输入内容）"

    messages = _build_chat_messages(system_prompt=sp, user_text=ut, history=history)

    try:
        from .model_router import get_model_router

        router = get_model_router()
        return await router.call_cloud_local_race(messages, temperature=temperature)
    except Exception:
        return "（网络不太稳定，请稍后再试）"


async def chat_complete_cloud_first(
    *,
    system_prompt: str,
    user_text: str,
    history: list[dict[str, str]] | None = None,
    temperature: float = 0.7,
    timeout_seconds: float = 10.0,
) -> str:
    """云端（Kimi）优先，超过 timeout_seconds 无响应则 fallback 到本地模型。

    适用于学情分析、周报等对质量要求高、但延迟不敏感的后台场景。
    """
    sp = (system_prompt or "").strip() or "You are a helpful assistant."
    ut = (user_text or "").strip()
    if not ut:
        return "（未检测到输入内容）"

    messages = _build_chat_messages(system_prompt=sp, user_text=ut, history=history)

    try:
        from .model_router import get_model_router

        router = get_model_router()
        return await router.call_cloud_first_timeout(
            messages,
            temperature=temperature,
            timeout=timeout_seconds,
        )
    except Exception:
        # 全部失败时回退到纯本地调用
        return await chat_complete(
            system_prompt=system_prompt,
            user_text=user_text,
            history=history,
            temperature=temperature,
        )


async def chat_complete_multimodal(
    *,
    system_prompt: str,
    user_text: str,
    image_base64: str | None = None,
    history: list[dict[str, Any]] | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout_seconds: float | None = None,
    temperature: float = 0.7,
    max_tokens: int = 700,
) -> str:
    """多模态对话补全（支持文本+单张图片）。

    采用 OpenAI vision 兼容格式：
    ```
    content: [
        {"type": "text", "text": "..."},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
    ]
    ```

    失败时返回降级文本，不抛异常。
    """
    sp = (system_prompt or "").strip() or "You are a helpful assistant."
    ut = (user_text or "").strip()
    if not ut:
        return "（未检测到输入内容）"

    effective = min(float(timeout_seconds or settings.llm_timeout_seconds), 20.0)
    timeout = httpx.Timeout(effective, connect=min(2.0, effective))
    resolved_base_url = str(base_url or "").strip() or settings.llm_base_url
    resolved_api_key = str(api_key or "").strip() or settings.llm_api_key

    # 构建 user message content
    user_content: list[dict[str, Any]] = [{"type": "text", "text": ut}]
    if image_base64:
        # 确保前缀正确
        if not image_base64.startswith("data:"):
            image_base64 = f"data:image/jpeg;base64,{image_base64}"
        user_content.append({
            "type": "image_url",
            "image_url": {"url": image_base64, "detail": "low"},
        })

    messages: list[dict[str, Any]] = [{"role": "system", "content": sp}]
    if history:
        for item in history:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            content = item.get("content")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_content})

    try:
        async with _make_openai_client(resolved_base_url, resolved_api_key, timeout) as client:
            resolved_model = str(model or "").strip()
            if not resolved_model:
                resolved_model = await _resolve_llm_model(scene="chat")
            resp = await client.chat.completions.create(
                model=resolved_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            data = resp.model_dump()
            text = _extract_chat_response_text(data)
            if text:
                return text
    except Exception:
        return "（网络不太稳定，请稍后再试）"

    return "（LLM 输出为空）"


def _extract_delta_text(obj: Any) -> str:
    """Extract delta text from OpenAI-compatible chat.completions streaming JSON."""

    if not isinstance(obj, dict):
        return ""

    choices = obj.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""

    c0 = choices[0] if isinstance(choices[0], dict) else {}

    # OpenAI ChatCompletions stream uses choices[].delta.content
    delta = c0.get("delta")
    if isinstance(delta, dict):
        content = delta.get("content")
        if isinstance(content, str):
            return content

    # Some servers may stream 'message.content'
    msg = c0.get("message")
    if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, str):
            return content

    return ""


async def stream_definition(term: str) -> AsyncIterator[str]:
    """Stream a definition from LM Studio, yielding incremental text deltas.

    Notes:
    - Uses OpenAI-compatible '/chat/completions' with stream=true.
    - On failure, yields nothing (caller should fall back).
    """

    prompt = (
        "你是一个外语学习助手。请用简洁中文解释这个英文词/短语，并给一个例句。\n"
        f"词：{term}\n"
        "输出格式：\n释义：...\n例句：..."
    )

    timeout = httpx.Timeout(settings.llm_timeout_seconds)

    try:
        async with _make_openai_client(
            settings.llm_base_url, settings.llm_api_key, timeout
        ) as client:
            model = await _resolve_llm_model(scene="vocab")
            stream = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                stream=True,
            )

            async for chunk in stream:
                delta = _extract_delta_text(chunk.model_dump())
                if delta:
                    yield delta
    except Exception:
        return


async def stream_chat(
    *,
    system_prompt: str,
    user_text: str,
    history: list[dict[str, str]] | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.7,
) -> AsyncIterator[str]:
    """Stream a single-turn chat completion with an explicit system prompt.

    Yields incremental deltas; on failure yields nothing (caller should fall back).
    """

    sp = (system_prompt or "").strip() or "You are a helpful assistant."
    ut = (user_text or "").strip()
    if not ut:
        return

    timeout = httpx.Timeout(settings.llm_timeout_seconds)
    resolved_base_url = str(base_url or "").strip() or settings.llm_base_url
    resolved_api_key = str(api_key or "").strip() or settings.llm_api_key

    try:
        async with _make_openai_client(resolved_base_url, resolved_api_key, timeout) as client:
            resolved_model = str(model or "").strip()
            if not resolved_model:
                resolved_model = await _resolve_llm_model(scene="chat")
            stream = await client.chat.completions.create(
                model=resolved_model,
                messages=_build_chat_messages(system_prompt=sp, user_text=ut, history=history),
                temperature=temperature,
                stream=True,
            )

            async for chunk in stream:
                delta = _extract_delta_text(chunk.model_dump())
                if delta:
                    yield delta
    except asyncio.CancelledError:
        raise
    except Exception:
        return


def _extract_json_object(text: str) -> str:
    s = (text or "").strip()
    if not s:
        return ""
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return ""
    return s[start : end + 1]


def _fallback_essay_result(*, ocr_text: str, language: str) -> dict[str, Any]:
    total = 60
    return {
        "score": total,
        "scores": {
            "vocabulary": total,
            "grammar": total,
            "fluency": total,
            "logic": total,
            "content": total,
            "structure": total,
            "total": total,
        },
        "feedback": "（降级）未连接到 LLM，返回最小可用批改结果。",
        "evaluation": "",
        "errors": [],
        "suggestions": ["检查拼写与标点", "尽量使用更具体的词汇"],
        "questions": [],
        "rewritten": ocr_text.strip()[:2000],
        "language": language,
    }


def _normalize_essay_result(obj: Any, *, ocr_text: str, language: str) -> dict[str, Any]:
    if not isinstance(obj, dict):
        return _fallback_essay_result(ocr_text=ocr_text, language=language)

    try:
        score_raw = obj.get("score", 60)
        if score_raw is None:
            score_raw = 60
        score = int(score_raw)
    except Exception:
        score = 60
    score = max(0, min(100, score))

    feedback = obj.get("feedback")
    if not isinstance(feedback, str):
        feedback = ""

    evaluation = obj.get("evaluation")
    if not isinstance(evaluation, str):
        evaluation = ""

    errors = obj.get("errors")
    if not isinstance(errors, list):
        errors = []

    suggestions = obj.get("suggestions")
    if not isinstance(suggestions, list):
        suggestions = []
    suggestions = [s for s in suggestions if isinstance(s, str) and s.strip()]

    questions = obj.get("questions")
    if not isinstance(questions, list):
        questions = []
    questions = [q for q in questions if isinstance(q, str) and q.strip()]

    rewritten = obj.get("rewritten")
    if not isinstance(rewritten, str):
        rewritten = ocr_text.strip()

    scores_obj = obj.get("scores")
    if isinstance(scores_obj, dict):
        def _int_score(key: str) -> int:
            try:
                v = int(scores_obj.get(key, score))
            except Exception:
                v = score
            return max(0, min(100, v))

        scores = {
            "vocabulary": _int_score("vocabulary"),
            "grammar": _int_score("grammar"),
            "fluency": _int_score("fluency"),
            "logic": _int_score("logic"),
            "content": _int_score("content"),
            "structure": _int_score("structure"),
            "total": _int_score("total"),
        }
        score = scores.get("total", score)
    else:
        scores = {
            "vocabulary": score,
            "grammar": score,
            "fluency": score,
            "logic": score,
            "content": score,
            "structure": score,
            "total": score,
        }

    return {
        "score": score,
        "scores": scores,
        "feedback": feedback,
        "evaluation": evaluation,
        "errors": errors,
        "suggestions": suggestions,
        "questions": questions,
        "rewritten": rewritten,
        "language": language,
    }


async def grade_essay(*, ocr_text: str, language: str) -> dict[str, Any]:
    """作文批改：尽力调用 LLM；失败则返回可用的降级 JSON。

    路由策略：云端优先，10s 内无响应则自动 fallback 到本地模型。
    temperature = 0.5（评分稳定性优先）。
    """

    prompt = render_prompt("essay_grade.j2", language=language, ocr_text=ocr_text)

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": prompt},
    ]

    try:
        from .model_router import get_model_router

        router = get_model_router()
        content = await router.call_cloud_first_timeout(
            messages,
            temperature=0.5,
            timeout=10.0,
        )
    except Exception:
        return _fallback_essay_result(ocr_text=ocr_text, language=language)

    if not content:
        return _fallback_essay_result(ocr_text=ocr_text, language=language)

    raw = content.strip()
    obj: Any | None = None
    try:
        obj = json.loads(raw)
    except Exception:
        json_text = _extract_json_object(raw)
        if json_text:
            try:
                obj = json.loads(json_text)
            except Exception:
                obj = None

    # Double-decode if model returned a JSON string.
    if isinstance(obj, str):
        try:
            obj2 = json.loads(obj)
            obj = obj2
        except Exception:
            pass

    if obj is not None:
        return _normalize_essay_result(obj, ocr_text=ocr_text, language=language)

    return _fallback_essay_result(ocr_text=ocr_text, language=language)

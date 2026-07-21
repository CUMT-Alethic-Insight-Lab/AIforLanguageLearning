"""模块E: 模型路由与上下文管理

核心职责:
1. 多模型统一路由 (Kimi API + 本地Qwen)
2. 场景化模型选择 (chat/vocab/essay/scenario_expansion)
3. 故障自动切换
4. 对话上下文管理 (滑动窗口、Token压缩)
5. Prompt模板管理
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator

import httpx

logger = logging.getLogger(__name__)

from .context_store import get_context_store
from .prompts import render_prompt
from .retry_utils import RETRY_CONFIG_LLM_API
from .runtime_config import get_runtime_config
from .settings import settings
from .token_utils import (
    compress_messages,
    count_tokens,
)


class SceneType(str, Enum):
    """场景类型枚举"""
    CHAT = "chat"                    # 对话执行 → 本地Qwen
    VOCAB = "vocab"                  # 词汇生成 → Kimi API
    ESSAY = "essay"                  # 作文批改 → Kimi API
    SCENARIO_EXPANSION = "scenario_expansion"  # 场景扩写 → Kimi API (thinking)


class ModelProvider(str, Enum):
    """模型提供商枚举"""
    LOCAL = "local"      # 本地模型 (Ollama/vLLM)
    KIMI = "kimi"        # Kimi API


@dataclass
class ModelEndpoint:
    """模型端点配置"""
    provider: ModelProvider
    base_url: str
    api_key: str
    model_id: str
    timeout_connect: float = 5.0
    timeout_read: float = 30.0
    priority: int = 0  # 优先级，数字越小优先级越高


@dataclass  
class RoutingDecision:
    """路由决策结果"""
    scene: SceneType
    primary_endpoint: ModelEndpoint
    fallback_endpoints: list[ModelEndpoint] = field(default_factory=list)
    use_streaming: bool = True
    temperature: float = 0.7


@dataclass
class ConversationMessage:
    """对话消息"""
    role: str  # system/user/assistant
    content: str
    timestamp: float = field(default_factory=time.time)
    token_count: int = 0


@dataclass
class ConversationContext:
    """对话上下文 - 支持分层记忆（短期消息 + 长期记忆点）"""
    conversation_id: str
    session_id: str
    messages: list[ConversationMessage] = field(default_factory=list)
    max_messages: int = 20  # 保留最近20轮
    max_tokens: int = 4000  # 上下文Token上限
    token_threshold: float = 0.8  # 80%触发摘要
    # 分层记忆
    memory_points: list[str] = field(default_factory=list)  # 长期记忆点
    _collapsed_summary: str = ""  # 已折叠的旧对话摘要
    _collapse_threshold: int = 10  # 超过此轮数触发折叠

    def add_message(self, role: str, content: str, token_count: int = 0) -> None:
        """添加消息，维护滑动窗口，并在必要时折叠旧消息"""
        if token_count == 0 and content:
            token_count = count_tokens(content)

        msg = ConversationMessage(
            role=role,
            content=content,
            token_count=token_count
        )
        self.messages.append(msg)

        # 分层折叠：非 system 消息超过阈值时，将中间轮次折叠为 summary
        self._maybe_collapse()

        # 硬上限保护：保留最近N轮
        max_total = self.max_messages * 2
        non_system = [m for m in self.messages if m.role != "system"]
        if len(non_system) > max_total:
            system_msgs = [m for m in self.messages if m.role == "system"]
            # 保留最近的 max_total 条非 system 消息
            keep_non_system = non_system[-max_total:]
            self.messages = system_msgs + keep_non_system

    def _maybe_collapse(self) -> None:
        """当非 system 消息轮数超过阈值时，将旧消息折叠为摘要占位。"""
        non_system = [m for m in self.messages if m.role != "system"]
        if len(non_system) <= self._collapse_threshold:
            return

        # 将最早的几轮（保留最近 threshold 轮）折叠
        to_fold = non_system[: -(self._collapse_threshold)]
        if len(to_fold) < 4:
            return  # 太少不折叠

        # 生成轻量级摘要（用户输入的前 30 字 + 助手回复的前 30 字）
        summary_parts: list[str] = []
        for i in range(0, len(to_fold) - 1, 2):
            user_msg = to_fold[i]
            assistant_msg = to_fold[i + 1] if i + 1 < len(to_fold) else None
            if user_msg.role == "user":
                user_preview = user_msg.content[:30].replace("\n", " ")
                if assistant_msg and assistant_msg.role == "assistant":
                    assistant_preview = assistant_msg.content[:30].replace("\n", " ")
                    summary_parts.append(f"[用户]{user_preview}... → [助手]{assistant_preview}...")
                else:
                    summary_parts.append(f"[用户]{user_preview}...")

        if summary_parts:
            self._collapsed_summary = "此前对话摘要：" + " | ".join(summary_parts)

        # 从 messages 中移除已折叠的消息，替换为单条 summary
        keep = [m for m in self.messages if m.role == "system" or m not in to_fold]
        # 在 system 之后插入 summary
        system_msgs = [m for m in keep if m.role == "system"]
        rest = [m for m in keep if m.role != "system"]
        if self._collapsed_summary:
            summary_msg = ConversationMessage(
                role="system",
                content=f"[对话历史摘要] {self._collapsed_summary}",
                token_count=count_tokens(self._collapsed_summary),
            )
            self.messages = system_msgs + [summary_msg] + rest
        else:
            self.messages = system_msgs + rest

    def add_memory_point(self, point: str) -> None:
        """添加长期记忆点（如用户偏好、关键事实）"""
        p = (point or "").strip()
        if p and p not in self.memory_points:
            self.memory_points.append(p)

    def get_enhanced_system_prompt(self, base_prompt: str = "") -> str:
        """将记忆点合并到 system prompt 中"""
        if not self.memory_points:
            return base_prompt
        memory_section = "\n\n【已记住的信息】\n" + "\n".join(f"- {p}" for p in self.memory_points)
        if base_prompt:
            return base_prompt + memory_section
        return memory_section.lstrip()

    def get_total_tokens(self) -> int:
        """获取总Token数"""
        return sum(m.token_count for m in self.messages)

    def should_compress(self) -> bool:
        """判断是否需要压缩上下文"""
        return self.get_total_tokens() > self.max_tokens * self.token_threshold

    def compress_if_needed(self) -> bool:
        """如果需要，压缩上下文"""
        if not self.should_compress():
            return False

        messages = self.to_openai_messages()
        compressed = compress_messages(messages, self.max_tokens)

        self.messages = []
        for msg in compressed:
            self.add_message(msg["role"], msg["content"])

        return True

    def to_openai_messages(self) -> list[dict[str, str]]:
        """转换为OpenAI格式"""
        return [{"role": m.role, "content": m.content} for m in self.messages]



def _resolve_model_id_sync(endpoint: ModelEndpoint) -> str:
    """同步解析模型 ID，避免占位符导致 LM Studio 选择错误模型。"""
    mid = (endpoint.model_id or "").strip()
    if mid and mid not in {"local-model", "local-llm", "default", ""}:
        return mid
    # Fallback: read from runtime_config primary
    try:
        runtime = get_runtime_config()
        primary = str(((runtime.get("models") or {}).get("primary") or "")).strip()
        if primary and primary not in {"local-model", "local-llm", "default", ""}:
            return primary
    except Exception:
        pass
    return mid or "qwen/qwen3.5-9b"


class _EndpointHealth:
    """端点健康状态（轻量级，无需持久化）"""
    def __init__(self) -> None:
        self.success_count: int = 0
        self.failure_count: int = 0
        self.last_check: float = 0.0
        self.last_latency_ms: float = 0.0
        self.healthy: bool = True

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        if total == 0:
            return 1.0  # 无历史时默认为健康
        return self.success_count / total

    def record(self, success: bool, latency_ms: float = 0.0) -> None:
        if success:
            self.success_count += 1
        else:
            self.failure_count += 1
        self.last_latency_ms = latency_ms
        # 最近 5 次内失败超过 3 次标记为不健康
        total = self.success_count + self.failure_count
        if total > 0:
            self.healthy = self.success_rate >= 0.4  # 容忍阈值


class ModelRouter:
    """模型路由器 - 核心类"""

    # 默认场景到模型提供商的映射（可被运行时配置覆盖）
    _DEFAULT_SCENE_PROVIDER_MAP: dict[SceneType, ModelProvider] = {
        SceneType.CHAT: ModelProvider.LOCAL,
        SceneType.VOCAB: ModelProvider.LOCAL,
        SceneType.ESSAY: ModelProvider.KIMI,
        SceneType.SCENARIO_EXPANSION: ModelProvider.KIMI,
    }

    def _resolve_model_id(self, endpoint: ModelEndpoint) -> str:
        """解析模型 ID，避免占位符导致 LM Studio 选择错误模型。"""
        return _resolve_model_id_sync(endpoint)

    def __init__(self) -> None:
        self._endpoints: dict[ModelProvider, list[ModelEndpoint]] = {}
        self._contexts: dict[str, ConversationContext] = {}
        self._health: dict[str, _EndpointHealth] = {}  # base_url -> health
        self._init_endpoints()
        self._load_scene_provider_map()

    def _health_key(self, endpoint: ModelEndpoint) -> str:
        return f"{endpoint.provider.value}::{endpoint.base_url}::{endpoint.model_id}"

    def _get_health(self, endpoint: ModelEndpoint) -> _EndpointHealth:
        key = self._health_key(endpoint)
        if key not in self._health:
            self._health[key] = _EndpointHealth()
        return self._health[key]

    def _record_health(self, endpoint: ModelEndpoint, success: bool, latency_ms: float = 0.0) -> None:
        self._get_health(endpoint).record(success, latency_ms)

    def _is_healthy(self, endpoint: ModelEndpoint) -> bool:
        return self._get_health(endpoint).healthy

    def _load_scene_provider_map(self) -> None:
        """尝试从运行时配置加载场景映射覆盖。"""
        try:
            runtime = get_runtime_config()
            overrides = runtime.get("scene_provider_map", {})
            self._scene_overrides: dict[str, str] = {
                k: v for k, v in overrides.items()
                if k in {s.value for s in SceneType}
                and v in {p.value for p in ModelProvider}
            }
        except Exception:
            self._scene_overrides = {}

    def _get_scene_provider(self, scene: SceneType) -> ModelProvider:
        """获取场景对应的提供商，支持运行时覆盖。"""
        override = self._scene_overrides.get(scene.value)
        if override:
            return ModelProvider(override)
        return self._DEFAULT_SCENE_PROVIDER_MAP.get(scene, ModelProvider.LOCAL)

    def _apply_scene_model(self, endpoint: ModelEndpoint, scene: SceneType) -> ModelEndpoint:
        """将按场景配置的 model_id 注入到路由结果中。"""
        runtime = get_runtime_config()
        scene_models = (((runtime.get("models") or {}).get("scene") or {}))
        scene_model = str(scene_models.get(scene.value) or "").strip()
        if not scene_model or scene_model in {"local-model", "local-llm", "default"}:
            return endpoint
        if endpoint.provider == ModelProvider.KIMI and not scene_model.startswith(("moonshot", "kimi")):
            return endpoint
        if scene_model == endpoint.model_id:
            return endpoint
        return dataclasses.replace(endpoint, model_id=scene_model)

    def update_scene_provider(self, scene: SceneType | str, provider: ModelProvider | str) -> None:
        """运行时更新场景-提供商映射（仅内存，重启后失效）。"""
        if isinstance(scene, str):
            scene = SceneType(scene)
        if isinstance(provider, str):
            provider = ModelProvider(provider)
        self._scene_overrides[scene.value] = provider.value
        logger.info(f"Updated scene provider mapping: {scene.value} -> {provider.value}")

    def reset_scene_provider(self, scene: SceneType | str | None = None) -> None:
        """重置场景-提供商映射到默认值。"""
        if scene is None:
            self._scene_overrides.clear()
            logger.info("Reset all scene provider mappings to defaults")
            return
        if isinstance(scene, str):
            scene = SceneType(scene)
        self._scene_overrides.pop(scene.value, None)
        logger.info(f"Reset scene provider mapping for {scene.value} to default")
    
    def _init_endpoints(self) -> None:
        """初始化模型端点配置"""
        # 本地模型端点：优先使用运行时配置中的 primary（由 list_available_llm_models 维护）
        # 避免使用 settings.llm_model 占位符导致 LM Studio 选择错误的大模型
        runtime = get_runtime_config()
        primary_model = str(((runtime.get("models") or {}).get("primary") or "")).strip()
        local_model_id = primary_model if primary_model and primary_model not in {"local-model", "local-llm", "default", ""} else getattr(settings, "llm_model", "qwen/qwen3.5-9b")

        local_endpoint = ModelEndpoint(
            provider=ModelProvider.LOCAL,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model_id=local_model_id,
            timeout_connect=5.0,
            timeout_read=60.0,  # 本地模型可能需要更长时间
            priority=1
        )
        self._endpoints[ModelProvider.LOCAL] = [local_endpoint]

        # Kimi API端点 (从环境变量或运行时配置读取)
        kimi_base_url = self._get_kimi_base_url()
        kimi_api_key = self._get_kimi_api_key()
        if kimi_base_url and kimi_api_key:
            kimi_endpoint = ModelEndpoint(
                provider=ModelProvider.KIMI,
                base_url=kimi_base_url,
                api_key=kimi_api_key,
                model_id="moonshot-v1-auto",  # Kimi API 通用模型名称
                timeout_connect=5.0,
                timeout_read=30.0,
                priority=1
            )
            self._endpoints[ModelProvider.KIMI] = [kimi_endpoint]
    
    def _get_kimi_base_url(self) -> str:
        """获取Kimi API基础URL"""
        # 优先从运行时配置读取
        runtime = get_runtime_config()
        kimi_config = runtime.get("kimi", {})
        base_url = kimi_config.get("base_url", "")
        if base_url:
            return base_url
        configured = str(getattr(settings, "kimi_base_url", "") or "").strip()
        if configured:
            return configured
        return "https://api.moonshot.cn/v1"
    
    def _get_kimi_api_key(self) -> str:
        """获取Kimi API密钥"""
        runtime = get_runtime_config()
        kimi_config = runtime.get("kimi", {})
        api_key = kimi_config.get("api_key", "")
        if api_key:
            return api_key
        return str(getattr(settings, "kimi_api_key", "") or "").strip()
    
    def route(self, scene: SceneType | str) -> RoutingDecision:
        """
        根据场景路由到合适的模型，支持运行时覆盖和健康状态感知。
        
        Args:
            scene: 场景类型
            
        Returns:
            RoutingDecision: 路由决策结果
        """
        if isinstance(scene, str):
            scene = SceneType(scene)
        
        # 获取场景对应的提供商（支持运行时覆盖）
        provider = self._get_scene_provider(scene)
        
        # 获取该提供商的端点列表，按健康状态排序
        endpoints = self._endpoints.get(provider, [])
        if endpoints:
            # 健康端点优先，同健康状态下按 priority 排序
            endpoints = sorted(
                endpoints,
                key=lambda e: (0 if self._is_healthy(e) else 1, e.priority)
            )

        if not endpoints:
            # 回退到本地模型
            endpoints = self._endpoints.get(ModelProvider.LOCAL, [])
            endpoints = sorted(
                endpoints,
                key=lambda e: (0 if self._is_healthy(e) else 1, e.priority)
            )
        
        primary = endpoints[0] if endpoints else None
        fallbacks = endpoints[1:] if len(endpoints) > 1 else []
        
        # 追加跨提供商故障回退，保证单一提供商不可用时仍可继续工作。
        if provider == ModelProvider.KIMI:
            cross_provider = ModelProvider.LOCAL
        elif provider == ModelProvider.LOCAL:
            cross_provider = ModelProvider.KIMI
        else:
            cross_provider = None

        if cross_provider is not None:
            cross_eps = self._endpoints.get(cross_provider, [])
            if cross_eps:
                cross_eps = sorted(
                    cross_eps,
                    key=lambda e: (0 if self._is_healthy(e) else 1, e.priority)
                )
                fallbacks.extend(cross_eps)

        if primary is None:
            raise RuntimeError(f"No model endpoints available for scene={scene.value}")

        primary = self._apply_scene_model(primary, scene)
        fallbacks = [self._apply_scene_model(endpoint, scene) for endpoint in fallbacks]
        
        # 场景扩写使用thinking模式，需要不同的temperature
        temperature = 0.7
        if scene == SceneType.SCENARIO_EXPANSION:
            temperature = 0.9  # 更高的创造性
        elif scene == SceneType.ESSAY:
            temperature = 0.5  # 更稳定的评分
        
        return RoutingDecision(
            scene=scene,
            primary_endpoint=primary,
            fallback_endpoints=fallbacks,
            use_streaming=True,
            temperature=temperature
        )
    
    def get_or_create_context(
        self,
        conversation_id: str,
        session_id: str = "",
        system_prompt: str = "",
        load_from_store: bool = True
    ) -> ConversationContext:
        """
        获取或创建对话上下文
        
        Args:
            conversation_id: 对话ID
            session_id: 会话ID
            system_prompt: 系统提示词
            load_from_store: 是否尝试从存储加载
            
        Returns:
            ConversationContext: 对话上下文
        """
        if conversation_id not in self._contexts:
            # 尝试从存储加载
            if load_from_store:
                try:
                    store = get_context_store()
                    loaded = store.load(conversation_id)
                    if loaded:
                        self._contexts[conversation_id] = loaded
                        logger.debug(f"Loaded context {conversation_id} from store")
                        return loaded
                except Exception as e:
                    logger.warning(f"Failed to load context {conversation_id}: {e}")
            
            # 创建新上下文
            context = ConversationContext(
                conversation_id=conversation_id,
                session_id=session_id
            )
            if system_prompt:
                context.add_message("system", system_prompt)
            self._contexts[conversation_id] = context
        
        return self._contexts[conversation_id]
    
    def save_context(self, conversation_id: str) -> bool:
        """
        保存对话上下文到存储
        
        Args:
            conversation_id: 对话ID
            
        Returns:
            bool: 是否保存成功
        """
        context = self._contexts.get(conversation_id)
        if not context:
            return False
        
        try:
            store = get_context_store()
            return store.save(context)
        except Exception as e:
            logger.error(f"Failed to save context {conversation_id}: {e}")
            return False
    
    def clear_context(self, conversation_id: str) -> None:
        """清除对话上下文"""
        if conversation_id in self._contexts:
            del self._contexts[conversation_id]
    
    async def call_with_fallback(
        self,
        decision: RoutingDecision,
        messages: list[dict[str, str]],
        stream: bool = True
    ) -> AsyncIterator[str]:
        """
        调用模型，支持故障切换
        
        Args:
            decision: 路由决策
            messages: 消息列表
            stream: 是否流式输出
            
        Yields:
            str: 生成的文本块
        """
        endpoints = [decision.primary_endpoint] + decision.fallback_endpoints
        
        last_error = None
        for endpoint in endpoints:
            try:
                async for chunk in self._call_endpoint(endpoint, messages, stream, decision.temperature):
                    yield chunk
                return  # 成功，结束
            except Exception as e:
                last_error = e
                continue  # 尝试下一个端点
        
        # 所有端点都失败
        raise RuntimeError(f"All model endpoints failed. Last error: {last_error}")
    
    async def _call_endpoint_with_retry(
        self,
        endpoint: ModelEndpoint,
        messages: list[dict[str, str]],
        stream: bool,
        temperature: float
    ) -> AsyncIterator[str]:
        """调用具体端点（带指数退避重试）"""
        
        async def _make_request() -> AsyncIterator[str]:
            timeout = httpx.Timeout(
                endpoint.timeout_read,
                connect=endpoint.timeout_connect
            )
            
            async with httpx.AsyncClient(base_url=endpoint.base_url, timeout=timeout) as client:
                model_id = self._resolve_model_id(endpoint)
                payload = {
                    "model": model_id,
                    "messages": messages,
                    "stream": stream,
                    "temperature": temperature
                }
                
                if stream:
                    async with client.stream(
                        "POST",
                        "/chat/completions",
                        headers={"Authorization": f"Bearer {endpoint.api_key}"},
                        json=payload
                    ) as resp:
                        resp.raise_for_status()
                        async for line in resp.aiter_lines():
                            if line.startswith("data: "):
                                data = line[6:]
                                if data == "[DONE]":
                                    break
                                try:
                                    chunk = json.loads(data)
                                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                                    content = delta.get("content", "")
                                    if content:
                                        yield content
                                except json.JSONDecodeError:
                                    continue
                else:
                    resp = await client.post(
                        "/chat/completions",
                        headers={"Authorization": f"Bearer {endpoint.api_key}"},
                        json=payload
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    yield content
        
        # 使用指数退避重试
        # 注意：由于这是生成器，我们不能直接包装整个函数
        # 而是在call_with_fallback层面处理重试
        async for chunk in _make_request():
            yield chunk
    
    async def _call_endpoint(
        self,
        endpoint: ModelEndpoint,
        messages: list[dict[str, str]],
        stream: bool,
        temperature: float
    ) -> AsyncIterator[str]:
        """调用具体端点（带重试逻辑和健康状态追踪）"""
        import time as _time
        config = RETRY_CONFIG_LLM_API
        overall_success = False

        for attempt in range(config.max_retries + 1):
            t0 = _time.perf_counter()
            try:
                async for chunk in self._call_endpoint_with_retry(
                    endpoint, messages, stream, temperature
                ):
                    yield chunk
                overall_success = True
                return  # 成功，结束
            except Exception as e:
                latency_ms = (_time.perf_counter() - t0) * 1000
                self._record_health(endpoint, success=False, latency_ms=latency_ms)

                if attempt >= config.max_retries:
                    logger.error(
                        f"Endpoint {endpoint.provider.value} failed after {config.max_retries + 1} attempts. "
                        f"Last error: {e}"
                    )
                    raise

                from .retry_utils import calculate_delay
                delay = calculate_delay(attempt, config)

                logger.warning(
                    f"Endpoint {endpoint.provider.value} failed (attempt {attempt + 1}). "
                    f"Retrying in {delay:.2f}s. Error: {e}"
                )

                await asyncio.sleep(delay)
            finally:
                if overall_success:
                    latency_ms = (_time.perf_counter() - t0) * 1000
                    self._record_health(endpoint, success=True, latency_ms=latency_ms)

    async def call_cloud_local_race(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
    ) -> str:
        """同时调用 KIMI 和 LOCAL，按 TTFT 选择胜者后返回完整文本。

        旧接口保持返回字符串；需要首 token 体验的调用方应使用
        ``call_cloud_local_race_stream``。
        """
        chunks = [
            chunk
            async for chunk in self.call_cloud_local_race_stream(
                messages=messages,
                temperature=temperature,
            )
        ]
        text = "".join(chunks).strip()
        if not text:
            raise RuntimeError("All model endpoints failed")
        return text

    async def call_cloud_local_race_stream(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """同时调用 KIMI 和 LOCAL，谁先产出首个 token 谁胜出并继续流式输出。

        优先调度历史成功率高的端点；不健康端点延迟 200ms 启动，
        避免在端点已明显故障时仍与其竞争。

        若 KIMI 未配置，直接回退到 LOCAL。
        所有任务失败时抛 RuntimeError。
        """
        kimi_eps = self._endpoints.get(ModelProvider.KIMI, [])
        local_eps = self._endpoints.get(ModelProvider.LOCAL, [])

        if not kimi_eps:
            if not local_eps:
                raise RuntimeError("No endpoints available")
            async for chunk in self._call_endpoint(local_eps[0], messages, True, temperature):
                if chunk:
                    yield chunk
            return

        all_eps = [(ep, self._get_health(ep).success_rate) for ep in (kimi_eps + local_eps)]
        # 按成功率降序排列，成功率高的优先创建任务
        all_eps.sort(key=lambda x: x[1], reverse=True)

        async def _race_first_token(endpoint: ModelEndpoint) -> dict[str, Any]:
            stream_iter = self._call_endpoint(endpoint, messages, True, temperature)
            try:
                async for delta in stream_iter:
                    if delta:
                        return {
                            "success": True,
                            "endpoint": endpoint,
                            "stream_iter": stream_iter,
                            "first_delta": delta,
                        }
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            return {"success": False, "endpoint": endpoint}

        task_map: dict[asyncio.Task[dict[str, Any]], ModelEndpoint] = {}
        for ep, rate in all_eps:
            # 不健康端点（成功率 < 0.6）延迟启动，降低竞争优先级
            if rate < 0.6:
                await asyncio.sleep(0.2)
            task = asyncio.create_task(_race_first_token(ep))
            task_map[task] = ep

        pending = set(task_map)
        winner: dict[str, Any] | None = None
        try:
            while pending and winner is None:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    try:
                        result = task.result()
                        if bool(result.get("success")):
                            winner = result
                            break
                    except Exception:
                        continue
            if winner is not None:
                for other in pending:
                    other.cancel()
        finally:
            if winner is None:
                for task in pending:
                    task.cancel()

        if winner is None:
            raise RuntimeError("All model endpoints failed")

        first_delta = str(winner.get("first_delta") or "")
        if first_delta:
            yield first_delta
        stream_iter = winner.get("stream_iter")
        try:
            async for delta in stream_iter:
                if delta:
                    yield delta
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    async def call_cloud_first_timeout(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        timeout: float = 1.0,
    ) -> str:
        """同时发起 KIMI 和 LOCAL，优先等 KIMI timeout 秒，超时则用 LOCAL。

        若 KIMI 未配置，直接回退到 LOCAL。
        """
        kimi_eps = self._endpoints.get(ModelProvider.KIMI, [])
        local_eps = self._endpoints.get(ModelProvider.LOCAL, [])

        if not kimi_eps:
            if not local_eps:
                raise RuntimeError("No endpoints available")
            return await _call_endpoint_text(local_eps[0], messages, temperature)

        cloud_task = asyncio.create_task(_call_endpoint_text(kimi_eps[0], messages, temperature))

        if not local_eps:
            # 仅云端可用时，直接等待云端结果
            try:
                return await cloud_task
            except Exception as e:
                raise RuntimeError(f"Cloud endpoint failed and no local fallback: {e}") from e

        local_task = asyncio.create_task(_call_endpoint_text(local_eps[0], messages, temperature))

        try:
            result = await asyncio.wait_for(cloud_task, timeout=timeout)
            local_task.cancel()
            return result
        except (asyncio.TimeoutError, Exception):
            pass

        try:
            return await local_task
        except Exception:
            pass

        if not cloud_task.done():
            try:
                return await cloud_task
            except Exception:
                pass

        raise RuntimeError("All model endpoints failed")


async def _call_endpoint_text(
    endpoint: ModelEndpoint,
    messages: list[dict[str, str]],
    temperature: float,
) -> str:
    """非流式调用单个端点，返回完整文本。失败时抛异常。"""
    # 读取超时使用端点配置与全局设置中的较小值，避免测试/无响应环境挂死
    read_timeout = min(endpoint.timeout_read, float(settings.llm_timeout_seconds))
    connect_timeout = min(endpoint.timeout_connect, 2.0)
    timeout = httpx.Timeout(read_timeout, connect=connect_timeout)
    async with httpx.AsyncClient(base_url=endpoint.base_url, timeout=timeout) as client:
        model_id = _resolve_model_id_sync(endpoint)
        payload: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "stream": False,
            "temperature": temperature,
        }
        resp = await client.post(
            "/chat/completions",
            headers={"Authorization": f"Bearer {endpoint.api_key}"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content or not content.strip():
            raise ValueError("Empty LLM response")
        return content.strip()


# 全局路由器实例
_router: ModelRouter | None = None


def get_model_router() -> ModelRouter:
    """获取全局模型路由器实例"""
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router


_SYSTEM_PROMPT_TAG_RE = re.compile(
    r"<SYSTEM_PROMPT>\s*(.*?)\s*</SYSTEM_PROMPT>",
    re.IGNORECASE | re.DOTALL,
)


def _normalize_expanded_system_prompt(raw_text: str, append_anchor_rule: bool = False) -> str:
    """将扩写结果标准化为可直接粘贴的 system prompt 正文。"""

    text = str(raw_text or "").strip()
    if not text:
        return ""

    tag_match = _SYSTEM_PROMPT_TAG_RE.search(text)
    if tag_match:
        text = tag_match.group(1).strip()

    # 清理常见代码块包裹。
    if text.startswith("```"):
        text = re.sub(r"^\s*```[\w-]*\s*", "", text, count=1)
        text = re.sub(r"\s*```\s*$", "", text, count=1)

    # 清理模型常见前导话术。
    text = re.sub(
        r"^\s*(以下|下面).{0,48}(System\s*Prompt|系统提示词|可直接).{0,24}[:：]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"^\s*System\s*Prompt\s*[:：]\s*", "", text, flags=re.IGNORECASE)

    # 兜底：删除 AI 主动句中常见的英文肯定/安抚短语（保留用户回应后的使用）。
    # 由于无法精确判断语境，这里采用保守策略：删除括号内或独立出现的常见英文短语。
    for phrase in (
        r"I see what you mean",
        r"Good try",
        r"Don't worry",
        r"Take your time",
        r"Well done",
        r"Nice try",
    ):
        # 匹配括号包裹形式，如 (I see what you mean.) 或 （I see what you mean.）
        text = re.sub(
            rf"[（(]\s*{re.escape(phrase)}[.,!?]*\s*[）)]",
            "",
            text,
            flags=re.IGNORECASE,
        )
        # 匹配独立出现的形式（前后有空格或标点）
        text = re.sub(
            rf"\b{re.escape(phrase)}[.,!?]*\b",
            "",
            text,
            flags=re.IGNORECASE,
        )
    # 清理可能产生的多余空括号或双空格
    text = re.sub(r"[（(]\s*[）)]", "", text)
    text = re.sub(r"  +", " ", text)

    # 折叠连续空行，保留单个空行。
    normalized_lines: list[str] = []
    prev_blank = False
    for line in text.splitlines():
        current = line.rstrip()
        if not current.strip():
            if not prev_blank:
                normalized_lines.append("")
            prev_blank = True
            continue
        normalized_lines.append(current)
        prev_blank = False

    text = "\n".join(normalized_lines).strip()
    text = text.strip('"').strip("'").strip()

    if append_anchor_rule:
        # 强制追加场景锚定规则（工程兜底）：无论扩写结果如何，必须包含此条。
        anchor_suffix = (
            "\n\n【场景锚定强制规则】\n"
            "无论用户输入语法是否正确、语义是否通顺，只要内容明显偏离当前实体场景，"
            "你必须先假设为 ASR 识别错误或用户一时口误，用 1-2 个与场景相关的确认选项把话题拉回正轨，"
            "绝对禁止直接接受偏离场景的内容并顺着话题聊下去。"
        )
        if anchor_suffix.strip() not in text:
            text = text + anchor_suffix

    return text


# ---------------------------------------------------------------------------
# 场景库文化语境匹配（内联精简版，供扩写时注入参考）
# ---------------------------------------------------------------------------
_SCENARIO_LIBRARY_SNIPPETS: dict[str, str] = {
    # 一、出行交通
    "机场": "- 日本机场：敬语层级（尊敬語・謙譲語・丁寧語）极其严格，排队距离和沉默等待的容忍度高。\n- 教学重点：让学生理解'敬语不是客气，是社会距离的管理工具'；练习用「～させていただきます」表达服务方的谦逊。",
    "酒店": "- 美国酒店：门童搬行李期待 $1-2/件小费，但前台不收小费；投诉表达习惯直接。\n- 日本商务酒店：大浴场礼仪（先淋浴再入浴、毛巾不入水、纹身禁忌），退房时间通常 10:00 非常严格。\n- 教学重点：区分 service recovery 的直接表达与日常寒暄的边界；理解'规则前置'的日本服务文化。",
    "租车": "- 美国租车：LDW 与 SLI 保险区分，条款质疑意识。\n- 英国租车：右舵左行，roundabout 让行规则。\n- 教学重点：培养'条款质疑意识'——学会说 'Could you walk me through what this covers?'；理解路权文化。",
    "地铁": "- 英国伦敦地铁：Oyster Card daily cap 机制，指路以线路和终点站为锚点而非东南西北。\n- 教学重点：理解'方向感表达'的英式习惯。",
    # 二、餐饮服务
    "餐厅": "- 美国餐厅：小费 15-20% 是强社会规范；过敏声明需用 'I'm allergic to' 而非 'I don't like'。\n- 法国餐厅：用餐节奏慢是社交仪式，服务员不会频繁打扰；奶酪盘是独立一道。\n- 教学重点：区分 'I don't like'（偏好）和 'I'm allergic to'（医疗）的语用权重；理解'慢即是尊重'的法国餐饮哲学。",
    "西餐": "- 美国餐厅：小费 15-20% 是强社会规范；过敏声明需用 'I'm allergic to' 而非 'I don't like'。\n- 法国餐厅：用餐节奏慢是社交仪式，服务员不会频繁打扰；奶酪盘是独立一道。\n- 教学重点：区分 'I don't like'（偏好）和 'I'm allergic to'（医疗）的语用权重；理解'慢即是尊重'的法国餐饮哲学。",
    "居酒屋": "- 日本居酒屋：お通し是'空间租赁+社交启动器'，不能拒绝；互相倒酒礼仪（空杯表示请续杯）。\n- 教学重点：练习互相倒酒时的谦让表达「お先に失礼します」。",
    "咖啡": "- 澳洲/英国精品咖啡：Flat White 是国民饮品，takeaway vs eat in 可能有 VAT 差异。\n- 教学重点：理解'咖啡文化中的地域身份认同'；学会用咖啡术语表达个人偏好。",
    "酒吧": "- 英国酒吧：轮酒文化（buying rounds）是社交契约，必须去吧台点酒且排队是隐形的。\n- 教学重点：练习吧台点酒时的眼神交流和简洁表达。",
    "外卖": "- 美国外卖：退款流程自动化但过度投诉会被标记为欺诈；'I'd like a refund' 正常，'You guys messed up' 带有指责性。\n- 教学重点：培养 assertive but polite 的投诉表达——描述事实而非指责人格。",
    # 三、生活服务
    "理发": "- 英国理发店：用 'fringe' 而非 'bangs'，trim 通常只修 1-2cm；小费 10% 是礼貌。\n- 日本理发店：沉默服务（no small talk）是尊重而非冷漠；服务流程固定（热毛巾、颈部按摩、耳部清洁）。\n- 教学重点：学会用具体长度和参考图片沟通；理解'沉默是服务的另一种形式'。",
    "干洗": "- 美国干洗店：same-day service 通常是上午送下午取；专业护理消费观念。\n- 教学重点：学会描述污渍类型（coffee stain, ink stain, grease stain）。",
    "银行": "- 美国银行：支票文化（voided check、routing number）仍广泛使用；信用记录与 debit/credit card 使用习惯相关。\n- 教学重点：理解'支票是另一种信任机制'；区分 debit card 和 credit card 的语用场景。",
    "邮局": "- 英国邮政 Royal Mail：1st Class / 2nd Class 是速度和价格而非舱位；邮局通常只卖邮票和寄件服务。\n- 教学重点：理解 'Class' 在英国邮政中的特殊含义；学会用重量和尺寸描述包裹。",
    "药店": "- 美国药店：药剂师有处方审核和用药咨询权，抗生素管控极严。\n- 教学重点：理解'药剂师是医疗团队的一员'；学会用具体症状和持续时间描述病情。",
    # 四、购物消费
    "超市": "- 英国超市：Best Before（品质保证期）vs Use By（安全截止日期）；自助结账礼仪。\n- 教学重点：理解'Best Before 不等于过期'；学会自助结账求助表达。",
    "商场": "- 美国商场：'No Questions Asked' 退货文化是消费者权利，但频繁退货会被标记为 serial returner。\n- 教学重点：理解'退货是消费者权利'与'滥用权利会被反制'的平衡。",
    "退换货": "- 美国商场：'No Questions Asked' 退货文化是消费者权利，但频繁退货会被标记为 serial returner。\n- 教学重点：理解'退货是消费者权利'与'滥用权利会被反制'的平衡。",
    "二手店": "- 英国慈善商店：价格固定不接受砍价；购买二手是中产阶级的环保和品味象征。\n- 教学重点：区分 thrift store 和 vintage shop 的文化定位。",
    "菜市场": "- 法国菜市场：商贩习惯聊食材产地和烹饪方法，是一种社交仪式；禁止用手摸蔬菜水果。\n- 教学重点：理解'市场对话是生活美学的一部分'；学会用 'What's in season?' 开启对话。",
    # 五、医疗健康
    "诊所": "- 英国 NHS：GP 需提前预约，急诊才去 A&E；医生期待患者自己描述症状。\n- 教学重点：理解分级诊疗逻辑；培养用时间线描述症状的能力。",
    "牙科": "- 美国牙科：保险有 annual maximum 和 deductible；患者有权说 'I'd like a second opinion'。\n- 教学重点：理解'知情同意'的美国医疗文化；学会询问保险覆盖范围。",
    "眼科": "- 日本眼镜店：30 分钟立等可取，验光师语气温和。\n- 教学重点：理解'效率与礼貌并重'的日本服务业；学会委婉表达不适「少し見にくいような気がします」。",
    "急诊": "- 美国急诊室：费用昂贵，分诊护士有绝对权力决定等待优先级。\n- 教学重点：理解'医疗资源的稀缺性分配'；学会清晰简洁地描述病情严重程度。",
    # 六、社交娱乐
    "电影": "- 英国电影院：有 15-20 分钟开场广告和预告片，观影时极为安静。\n- 教学重点：理解'公共空间的沉默契约'；学会礼貌表达。",
    "健身": "- 美国健身房：Don't talk to someone mid-set，用完器械归位；'How many sets do you have left?' 是礼貌轮换请求。\n- 教学重点：理解'健身房是共享空间，规则靠自律'；学会用健身术语描述训练目标。",
    "博物馆": "- 法国博物馆：拍照限制严格（闪光灯绝对禁止），英国博物馆免费但建议捐赠。\n- 教学重点：理解'文化机构的规则是保护而非限制'；学会询问 'Is photography allowed here?'",
    "派对": "- 英美 house party：BYOB（自带酒水），small talk 话题避开政治宗教和收入，告别时说 'I should probably make a move'。\n- 教学重点：理解'派对是社交投资'；培养用开放式问题维持对话的能力。",
    # 七、居住事务
    "租房": "- 英国租房：押金必须存入第三方保护机构（DPS/TDS），bills included 通常有合理使用上限。\n- 日本租房：礼金（感谢费，不退）与敷金（押金）区分，垃圾回收日和分类规则严格。\n- 教学重点：理解'租客权利受法律保护'；理解礼金是日本租房文化中的'社交润滑剂'。",
    "家电维修": "- 美国维修服务：service window（如 8am-12pm）不会给出精确时间；维修前需提供书面估价单。\n- 教学重点：理解'时间窗口'的美国服务业惯例；学会描述故障现象而非猜测原因。",
    "物业": "- 美国公寓物业：只处理公共事务，邻居纠纷建议先自行沟通；投诉讲究 document everything。\n- 教学重点：理解'自治优先'的美国社区文化；培养用事实和时间线写正式邮件的能力。",
    # 八、学习教育
    "图书馆": "- 英国大学图书馆：silent study 区域要求绝对安静；self-checkout 和 self-return 是常态。\n- 教学重点：理解'公共空间的使用边界'；学会用图书馆数据库搜索资源的术语。",
    "书店": "- 法国书店：员工乐于讨论书籍内容，新书受 Lang Law 保护不能打折。\n- 教学重点：理解'书店是文化空间而非纯零售点'；学会用文学评论句式开启对话。",
    "语言学校": "- 英国语言学校：placement test 测口语流利度和学习动机；课堂强调 participation。\n- 教学重点：理解'语言能力不等于考试成绩'；培养主动提问和课堂参与的意识。",
    # 九、其他
    "宠物医院": "- 英国兽医：宠物视为家庭成员，沟通方式非常温和委婉；宠物保险普及。\n- 教学重点：理解'动物福利文化'；学会用情感铺垫表达艰难决定。",
    "汽车维修": "- 美国修车店：维修前必须提供书面估价单，未经同意不能额外收费。\n- 教学重点：学会说 'I'll stick to the original estimate for now'，防止过度推销。",
    "美甲": "- 美国美甲店：小费 15-20%，需适应越南移民口音；区分 dip powder 和 gel。\n- 教学重点：适应不同口音的服务场景英语。",
    "瑜伽": "- 美国瑜伽馆：强调 non-competitive 和 listen to your body，迟到通常不能进入教室。\n- 教学重点：理解'身心连接'的西方瑜伽文化。",
    "宗教": "- 英国教堂：参观时恰逢礼拜必须保持绝对安静，某些区域禁止进入；捐赠不是强制门票。\n- 教学重点：理解宗教场所的礼仪边界。",
}


def _match_scenario_library(user_description: str, language: str = "en") -> str:
    """根据用户描述匹配场景库中的文化语境摘要，返回供 Kimi 参考的文本。"""
    desc = (user_description or "").lower()
    matched: list[str] = []
    seen_keys: set[str] = set()

    # 按关键词优先级排序（先匹配长的/具体的）
    for keyword, snippet in sorted(
        _SCENARIO_LIBRARY_SNIPPETS.items(), key=lambda x: len(x[0]), reverse=True
    ):
        if keyword in desc and keyword not in seen_keys:
            matched.append(f"【{keyword}】\n{snippet}")
            seen_keys.add(keyword)

    if not matched:
        return ""

    header = (
        "以下是从场景库中匹配到的文化差异焦点与教学重点，"
        "请在扩写时自然融入角色台词和 💡 学习提示中：\n"
    )
    return header + "\n\n".join(matched)


async def expand_scenario(user_description: str, language: str = "en") -> str:
    """
    场景扩写: 用户描述 → Kimi API扩写 → 结构化场景描述

    Args:
        user_description: 用户的场景描述
        language: 目标语言

    Returns:
        str: 扩写后的场景描述（可作为System Prompt）
    """
    router = get_model_router()
    decision = router.route(SceneType.SCENARIO_EXPANSION)

    scenario_library_context = _match_scenario_library(user_description, language)

    # 使用可编辑模板生成扩写任务，便于手工调优。
    prompt = render_prompt(
        "scenario_expand_system_prompt.j2",
        user_description=user_description,
        language=language,
        scenario_library_context=scenario_library_context,
    )
    
    messages = [
        {
            "role": "system",
            "content": "你是有着对于各种场景广泛且深入理解的AI人机场景对话提示词工程专家。严格遵循输出格式，只返回用于引导对话的system prompt正文。",
        },
        {"role": "user", "content": prompt},
    ]
    
    result = ""
    async for chunk in router.call_with_fallback(decision, messages, stream=False):
        result += chunk

    normalized = _normalize_expanded_system_prompt(result, append_anchor_rule=True)
    return normalized or result.strip()


async def chat_with_context(
    conversation_id: str,
    user_message: str,
    session_id: str = "",
    system_prompt: str = ""
) -> AsyncIterator[str]:
    """
    带上下文的对话: 云端/本地竞速，谁先成功用谁。
    
    Args:
        conversation_id: 对话ID
        user_message: 用户消息
        session_id: 会话ID
        system_prompt: 系统提示词
        
    Yields:
        str: 生成的文本块
    """
    router = get_model_router()
    
    # 获取或创建上下文
    context = router.get_or_create_context(conversation_id, session_id, system_prompt)
    
    # 检查是否需要压缩上下文
    if context.should_compress():
        context.compress_if_needed()
    
    # 添加用户消息
    context.add_message("user", user_message)
    
    # 路由决策
    decision = router.route(SceneType.CHAT)
    
    # chat 场景按架构要求使用云端/本地竞速，避免本地端点不可用时串行阻塞。
    messages = context.to_openai_messages()
    assistant_response = await router.call_cloud_local_race(
        messages,
        temperature=decision.temperature,
    )
    yield assistant_response
    
    # 保存助手回复到上下文
    context.add_message("assistant", assistant_response)
    
    # 持久化上下文
    router.save_context(conversation_id)


async def generate_vocab_with_routing(term: str, language: str = "en") -> dict[str, Any]:
    """
    词汇生成: 默认使用本地模型生成结构化词汇信息。

    当前默认路由遵循 SceneType.VOCAB -> LOCAL，
    可由 runtime_config.scene_provider_map 在运行时覆盖。
    
    Args:
        term: 词汇
        language: 目标语言
        
    Returns:
        dict: 包含meaning、example、example_translation、definitions的结构化数据
    """
    router = get_model_router()
    decision = router.route(SceneType.VOCAB)
    
    prompt = f"""请为单词"{term}"生成详细的词汇解析。

要求输出以下JSON格式:
{{
    "meaning": "中文释义（简洁）",
    "example": "英文例句",
    "example_translation": "例句中文翻译",
    "definitions": [
        {{
            "meaning": "义项1中文解释",
            "example": "义项1例句",
            "example_translation": "义项1例句翻译"
        }}
    ]
}}

注意:
1. 必须输出有效的JSON格式
2. 至少提供2-3个不同义项
3. 例句要体现该义项的典型用法"""

    messages = [
        {"role": "system", "content": "你是一个专业的英语词汇解析专家。只输出JSON格式，不要有任何其他文字。"},
        {"role": "user", "content": prompt}
    ]
    
    result = ""
    async for chunk in router.call_with_fallback(decision, messages, stream=False):
        result += chunk
    
    # 解析JSON结果
    try:
        # 尝试直接解析
        data = json.loads(result.strip())
    except json.JSONDecodeError:
        # 尝试从代码块中提取
        import re
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', result, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
            except json.JSONDecodeError:
                data = {"meaning": result[:200], "example": "", "example_translation": "", "definitions": []}
        else:
            # 尝试提取最大的JSON对象
            json_match = re.search(r'\{[\s\S]*\}', result)
            if json_match:
                try:
                    data = json.loads(json_match.group(0))
                except json.JSONDecodeError:
                    data = {"meaning": result[:200], "example": "", "example_translation": "", "definitions": []}
            else:
                data = {"meaning": result[:200], "example": "", "example_translation": "", "definitions": []}
    
    # 确保返回格式正确
    return {
        "meaning": data.get("meaning", ""),
        "example": data.get("example", ""),
        "example_translation": data.get("example_translation", ""),
        "definitions": data.get("definitions", []),
    }


async def grade_essay_with_routing(
    essay_text: str,
    language: str = "en",
    criteria: list[str] | None = None
) -> dict[str, Any]:
    """
    作文批改: 云端优先，多维度评分超时则回退到本地。
    
    Args:
        essay_text: 作文文本
        language: 语言
        criteria: 评分维度列表，默认使用6个维度
        
    Returns:
        dict: 包含score、dimensions、feedback、corrected的结构化评分结果
    """
    router = get_model_router()
    decision = router.route(SceneType.ESSAY)
    
    if criteria is None:
        criteria = ["词汇", "语法", "逻辑", "流畅度", "内容", "结构"]
    
    prompt = f"""请对以下作文进行专业批改和评分。

作文内容:
```{language}
{essay_text}
```

请从以下维度进行评分（0-100分）:
{', '.join(criteria)}

输出以下JSON格式:
{{
    "total_score": 85,
    "dimensions": {{
        "词汇": {{"score": 80, "comment": "词汇使用评价"}},
        "语法": {{"score": 85, "comment": "语法使用评价"}},
        ...
    }},
    "overall_feedback": "总体评价和建议",
    "errors": [
        {{"text": "错误文本", "correction": "修正", "explanation": "解释"}}
    ],
    "corrected_version": "修正后的完整作文"
}}

注意:
1. 必须输出有效的JSON格式
2. 每个维度都要有具体的评价说明
3. 列出3-5个主要错误并给出修正"""

    messages = [
        {"role": "system", "content": "你是一个专业的英语作文批改专家。只输出JSON格式，不要有任何其他文字。"},
        {"role": "user", "content": prompt}
    ]
    
    result = ""
    try:
        result = await router.call_cloud_first_timeout(
            messages,
            temperature=decision.temperature,
            timeout=10.0,
        )
    except Exception:
        result = ""
    
    # 解析JSON结果
    try:
        data = json.loads(result.strip())
    except json.JSONDecodeError:
        import re
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', result, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
            except json.JSONDecodeError:
                data = {"parse_error": True, "raw_response": result[:500]}
        else:
            json_match = re.search(r'\{[\s\S]*\}', result)
            if json_match:
                try:
                    data = json.loads(json_match.group(0))
                except json.JSONDecodeError:
                    data = {"parse_error": True, "raw_response": result[:500]}
            else:
                data = {"parse_error": True, "raw_response": result[:500]}
    
    return data


# 导出关键组件
__all__ = [
    "ModelRouter",
    "ModelEndpoint",
    "RoutingDecision",
    "ConversationContext",
    "ConversationMessage",
    "SceneType",
    "ModelProvider",
    "get_model_router",
    "expand_scenario",
    "chat_with_context",
    "generate_vocab_with_routing",
    "grade_essay_with_routing",
]

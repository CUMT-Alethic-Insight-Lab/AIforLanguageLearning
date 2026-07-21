"""模型路由模块测试"""

from __future__ import annotations

import pytest

from app.model_router import (
    ConversationContext,
    ConversationMessage,
    ModelEndpoint,
    ModelProvider,
    ModelRouter,
    SceneType,
    _normalize_expanded_system_prompt,
)
from app.token_utils import (
    approximate_token_count,
    compress_messages,
    count_messages_tokens,
    count_tokens,
)


class TestSceneType:
    """场景类型测试"""
    
    def test_scene_type_values(self):
        """测试场景类型枚举值"""
        assert SceneType.CHAT.value == "chat"
        assert SceneType.VOCAB.value == "vocab"
        assert SceneType.ESSAY.value == "essay"
        assert SceneType.SCENARIO_EXPANSION.value == "scenario_expansion"


class TestModelProvider:
    """模型提供商测试"""
    
    def test_provider_values(self):
        """测试提供商枚举值"""
        assert ModelProvider.LOCAL.value == "local"
        assert ModelProvider.KIMI.value == "kimi"


class TestConversationMessage:
    """对话消息测试"""
    
    def test_message_creation(self):
        """测试消息创建"""
        msg = ConversationMessage(
            role="user",
            content="Hello",
            token_count=2
        )
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.token_count == 2
    
    def test_message_default_timestamp(self):
        """测试消息默认时间戳"""
        import time
        before = time.time()
        msg = ConversationMessage(role="assistant", content="Hi")
        after = time.time()
        assert before <= msg.timestamp <= after


class TestConversationContext:
    """对话上下文测试"""
    
    def test_context_creation(self):
        """测试上下文创建"""
        ctx = ConversationContext(
            conversation_id="test-123",
            session_id="session-456"
        )
        assert ctx.conversation_id == "test-123"
        assert ctx.session_id == "session-456"
        assert len(ctx.messages) == 0
    
    def test_add_message(self):
        """测试添加消息"""
        ctx = ConversationContext("test-123", session_id="session-456")
        ctx.add_message("system", "You are a helpful assistant")
        ctx.add_message("user", "Hello")
        
        assert len(ctx.messages) == 2
        assert ctx.messages[0].role == "system"
        assert ctx.messages[1].role == "user"
    
    def test_sliding_window(self):
        """测试滑动窗口限制"""
        ctx = ConversationContext("test-123", session_id="session-456", max_messages=2)
        
        # 添加超过限制的消息 (2轮 = 4条消息)
        ctx.add_message("user", "Q1")
        ctx.add_message("assistant", "A1")
        ctx.add_message("user", "Q2")
        ctx.add_message("assistant", "A2")
        ctx.add_message("user", "Q3")  # 应该触发滑动
        ctx.add_message("assistant", "A3")
        
        # 应该只保留最近2轮 (4条消息)
        assert len(ctx.messages) <= 4
    
    def test_get_total_tokens(self):
        """测试Token总数计算"""
        ctx = ConversationContext("test-123", session_id="session-456")
        ctx.add_message("system", "Sys", 10)
        ctx.add_message("user", "Hello", 2)
        ctx.add_message("assistant", "Hi there", 3)
        
        assert ctx.get_total_tokens() == 15
    
    def test_should_compress(self):
        """测试压缩判断"""
        ctx = ConversationContext(
            "test-123",
            session_id="session-456",
            max_tokens=100,
            token_threshold=0.8
        )
        
        # 未超过阈值
        ctx.add_message("user", "Short", 50)
        assert not ctx.should_compress()  # 50 < 80
        
        # 超过阈值
        ctx.add_message("user", "Long message", 100)
        assert ctx.should_compress()  # 150 > 80


class TestModelEndpoint:
    """模型端点测试"""
    
    def test_endpoint_creation(self):
        """测试端点创建"""
        endpoint = ModelEndpoint(
            provider=ModelProvider.LOCAL,
            base_url="http://localhost:1234/v1",
            api_key="test-key",
            model_id="qwen2.5-7b",
            priority=1
        )
        assert endpoint.provider == ModelProvider.LOCAL
        assert endpoint.base_url == "http://localhost:1234/v1"
        assert endpoint.model_id == "qwen2.5-7b"


class TestModelRouter:
    """模型路由器测试"""
    
    def test_router_creation(self):
        """测试路由器创建"""
        router = ModelRouter()
        assert router is not None
        assert len(router._endpoints) >= 1  # 至少本地模型
    
    def test_route_chat_scene(self):
        """测试对话场景路由"""
        router = ModelRouter()
        decision = router.route(SceneType.CHAT)
        
        assert decision.scene == SceneType.CHAT
        assert decision.primary_endpoint is not None
        assert decision.temperature == 0.7
    
    def test_route_essay_scene(self):
        """测试作文场景路由"""
        router = ModelRouter()
        decision = router.route(SceneType.ESSAY)
        
        assert decision.scene == SceneType.ESSAY
        assert decision.temperature == 0.5  # 更稳定的评分
    
    def test_route_scenario_expansion(self):
        """测试场景扩写路由"""
        router = ModelRouter()
        decision = router.route(SceneType.SCENARIO_EXPANSION)
        
        assert decision.scene == SceneType.SCENARIO_EXPANSION
        assert decision.temperature == 0.9  # 更高的创造性
    
    def test_get_or_create_context(self):
        """测试获取或创建上下文"""
        router = ModelRouter()
        ctx = router.get_or_create_context(
            "conv-123",
            "session-456",
            "System prompt"
        )
        
        assert ctx.conversation_id == "conv-123"
        assert ctx.session_id == "session-456"
        assert len(ctx.messages) == 1
        assert ctx.messages[0].role == "system"
    
    def test_clear_context(self):
        """测试清除上下文"""
        router = ModelRouter()
        router.get_or_create_context("conv-123")
        assert "conv-123" in router._contexts
        
        router.clear_context("conv-123")
        assert "conv-123" not in router._contexts


class TestTokenUtils:
    """Token工具测试"""
    
    def test_count_tokens_empty(self):
        """测试空文本"""
        assert count_tokens("") == 0
        assert count_tokens(None) == 0
    
    def test_approximate_token_count_english(self):
        """测试英文近似计数"""
        text = "Hello world this is a test"
        count = approximate_token_count(text)
        # 5个单词，大约4-6个token
        assert 3 <= count <= 12
    
    def test_approximate_token_count_chinese(self):
        """测试中文近似计数"""
        text = "你好世界"
        count = approximate_token_count(text)
        # 4个中文字符，大约6个token
        assert 4 <= count <= 10
    
    def test_count_messages_tokens(self):
        """测试消息列表Token计数"""
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
        ]
        count = count_messages_tokens(messages)
        assert count > 0
    
    def test_compress_messages(self):
        """测试消息压缩"""
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Question 1"},
            {"role": "assistant", "content": "Answer 1"},
            {"role": "user", "content": "Question 2"},
            {"role": "assistant", "content": "Answer 2"},
        ]
        
        # 压缩到很小的限制
        compressed = compress_messages(messages, max_tokens=50)
        
        # 应该保留system消息
        assert any(m["role"] == "system" for m in compressed)
        
        # Token数应该减少
        original_tokens = count_messages_tokens(messages)
        compressed_tokens = count_messages_tokens(compressed)
        assert compressed_tokens <= original_tokens


class TestIntegration:
    """集成测试"""
    
    @pytest.mark.asyncio
    async def test_context_compression_integration(self):
        """测试上下文压缩集成"""
        router = ModelRouter()
        ctx = router.get_or_create_context("test-compress")
        
        # 添加大量消息触发压缩
        for i in range(50):
            ctx.add_message(
                "user",
                f"This is a long message number {i} with many words to increase token count",
            )
            ctx.add_message(
                "assistant",
                f"This is a detailed response number {i} with even more words to consume tokens",
            )
        
        # 手动设置低阈值触发压缩
        ctx.max_tokens = 100
        ctx.token_threshold = 0.5
        
        # 压缩前
        before_count = len(ctx.messages)
        
        # 执行压缩
        compressed = ctx.compress_if_needed()
        
        # 应该进行了压缩
        assert compressed is True
        
        # 压缩后消息数应该减少
        after_count = len(ctx.messages)
        assert after_count < before_count


class TestScenarioExpansionNormalization:
    """扩写结果规范化测试"""

    def test_strip_system_prompt_tags(self):
        raw = """<SYSTEM_PROMPT>
你是日语口语陪练。
每次回复 2-4 句。
</SYSTEM_PROMPT>"""
        normalized = _normalize_expanded_system_prompt(raw)
        assert normalized == "你是日语口语陪练。\n每次回复 2-4 句。"

    def test_strip_lead_in_prefix(self):
        raw = "以下是可直接使用的System Prompt：你是法语口语陪练。"
        normalized = _normalize_expanded_system_prompt(raw)
        assert normalized == "你是法语口语陪练。"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

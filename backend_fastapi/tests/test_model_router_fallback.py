"""模型路由故障切换测试"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.model_router import (
    ModelEndpoint,
    ModelProvider,
    ModelRouter,
    RoutingDecision,
    SceneType,
)


class TestModelRouterFallback:
    """模型路由器故障切换测试"""

    @pytest.mark.asyncio
    async def test_primary_failure_fallback_to_secondary(self) -> None:
        router = ModelRouter()
        decision = RoutingDecision(
            scene=SceneType.CHAT,
            primary_endpoint=ModelEndpoint(
                provider=ModelProvider.LOCAL,
                base_url="http://fail-1",
                api_key="key1",
                model_id="model1",
            ),
            fallback_endpoints=[
                ModelEndpoint(
                    provider=ModelProvider.LOCAL,
                    base_url="http://success-2",
                    api_key="key2",
                    model_id="model2",
                ),
            ],
            use_streaming=True,
            temperature=0.7,
        )

        async def mock_call(endpoint, messages, stream, temperature):
            if endpoint.base_url == "http://fail-1":
                raise ConnectionError("primary down")
            yield "fallback"

        with patch.object(router, "_call_endpoint", side_effect=mock_call):
            chunks = [c async for c in router.call_with_fallback(decision, messages=[], stream=True)]
            assert chunks == ["fallback"]

    @pytest.mark.asyncio
    async def test_all_endpoints_fail(self) -> None:
        router = ModelRouter()
        decision = RoutingDecision(
            scene=SceneType.CHAT,
            primary_endpoint=ModelEndpoint(
                provider=ModelProvider.LOCAL,
                base_url="http://fail-1",
                api_key="key1",
                model_id="model1",
            ),
            fallback_endpoints=[
                ModelEndpoint(
                    provider=ModelProvider.LOCAL,
                    base_url="http://fail-2",
                    api_key="key2",
                    model_id="model2",
                ),
            ],
            use_streaming=True,
            temperature=0.7,
        )

        async def mock_call(endpoint, messages, stream, temperature):
            if False:
                yield ""
            raise ConnectionError("all down")

        with patch.object(router, "_call_endpoint", side_effect=mock_call):
            with pytest.raises(RuntimeError, match="All model endpoints failed"):
                _ = [c async for c in router.call_with_fallback(decision, messages=[], stream=True)]

    @pytest.mark.asyncio
    async def test_primary_success_no_fallback(self) -> None:
        router = ModelRouter()
        decision = RoutingDecision(
            scene=SceneType.CHAT,
            primary_endpoint=ModelEndpoint(
                provider=ModelProvider.LOCAL,
                base_url="http://success-1",
                api_key="key1",
                model_id="model1",
            ),
            fallback_endpoints=[],
            use_streaming=True,
            temperature=0.7,
        )

        async def mock_call(endpoint, messages, stream, temperature):
            yield "primary"

        with patch.object(router, "_call_endpoint", side_effect=mock_call):
            chunks = [c async for c in router.call_with_fallback(decision, messages=[], stream=True)]
            assert chunks == ["primary"]

    @pytest.mark.asyncio
    async def test_cloud_local_race_stream_uses_fastest_first_token(self) -> None:
        router = ModelRouter()
        cloud = ModelEndpoint(
            provider=ModelProvider.KIMI,
            base_url="http://cloud",
            api_key="cloud-key",
            model_id="kimi",
        )
        local = ModelEndpoint(
            provider=ModelProvider.LOCAL,
            base_url="http://local",
            api_key="local-key",
            model_id="qwen",
        )
        router._endpoints = {
            ModelProvider.KIMI: [cloud],
            ModelProvider.LOCAL: [local],
        }

        async def mock_call(endpoint, messages, stream, temperature):
            if endpoint.provider == ModelProvider.KIMI:
                await asyncio.sleep(0.01)
                yield "cloud-first"
                await asyncio.sleep(0.05)
                yield "-cloud-last"
            else:
                await asyncio.sleep(0.03)
                yield "local-fast-full"

        with patch.object(router, "_call_endpoint", side_effect=mock_call):
            chunks = [
                chunk
                async for chunk in router.call_cloud_local_race_stream(
                    messages=[{"role": "user", "content": "hello"}]
                )
            ]

        assert chunks == ["cloud-first", "-cloud-last"]

    @pytest.mark.asyncio
    async def test_cloud_local_race_preserves_string_api(self) -> None:
        router = ModelRouter()
        cloud = ModelEndpoint(
            provider=ModelProvider.KIMI,
            base_url="http://cloud",
            api_key="cloud-key",
            model_id="kimi",
        )
        local = ModelEndpoint(
            provider=ModelProvider.LOCAL,
            base_url="http://local",
            api_key="local-key",
            model_id="qwen",
        )
        router._endpoints = {
            ModelProvider.KIMI: [cloud],
            ModelProvider.LOCAL: [local],
        }

        async def mock_call(endpoint, messages, stream, temperature):
            if endpoint.provider == ModelProvider.KIMI:
                await asyncio.sleep(0.01)
                yield "a"
                yield "b"
            else:
                await asyncio.sleep(0.03)
                yield "c"

        with patch.object(router, "_call_endpoint", side_effect=mock_call):
            text = await router.call_cloud_local_race(
                messages=[{"role": "user", "content": "hello"}]
            )

        assert text == "ab"

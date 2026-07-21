"""Token计数的离线降级测试。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from app import token_utils


@pytest.fixture(autouse=True)
def reset_tokenizer_state() -> None:
    with token_utils._TOKENIZER_LOCK:
        token_utils._TOKENIZER_CACHE.clear()
        token_utils._LOCAL_ENCODING_CACHE.clear()


def test_missing_cache_uses_approximation_without_constructing(monkeypatch) -> None:
    monkeypatch.setattr(token_utils, "_has_local_encoding_data", lambda _name: False)

    def unexpected_constructor(_name: str):
        raise AssertionError("tiktoken constructor must not run without a local cache")

    monkeypatch.setattr(token_utils.tiktoken, "get_encoding", unexpected_constructor)

    text = "offline token counting"
    assert token_utils.count_tokens(text) == token_utils.approximate_token_count(text)


def test_network_error_falls_back_and_is_not_retried(monkeypatch) -> None:
    attempts = 0
    monkeypatch.setattr(token_utils, "_has_local_encoding_data", lambda _name: True)

    def failing_constructor(_name: str):
        nonlocal attempts
        attempts += 1
        raise ConnectionError("network unavailable")

    monkeypatch.setattr(token_utils.tiktoken, "get_encoding", failing_constructor)

    expected = token_utils.approximate_token_count("hello")
    assert token_utils.count_tokens("hello") == expected
    assert token_utils.count_tokens("hello") == expected
    assert attempts == 1


def test_local_tokenizer_is_used_when_available(monkeypatch) -> None:
    attempts = 0
    monkeypatch.setattr(token_utils, "_has_local_encoding_data", lambda _name: True)

    class FakeEncoding:
        def encode(self, _text: str) -> list[int]:
            return [1, 2, 3]

    def local_constructor(_name: str) -> FakeEncoding:
        nonlocal attempts
        attempts += 1
        return FakeEncoding()

    monkeypatch.setattr(token_utils.tiktoken, "get_encoding", local_constructor)

    assert token_utils.count_tokens("hello") == 3
    assert token_utils.count_tokens("again") == 3
    assert attempts == 1


def test_concurrent_failure_only_attempts_construction_once(monkeypatch) -> None:
    attempts = 0
    monkeypatch.setattr(token_utils, "_has_local_encoding_data", lambda _name: True)

    def failing_constructor(_name: str):
        nonlocal attempts
        attempts += 1
        raise OSError("simulated offline failure")

    monkeypatch.setattr(token_utils.tiktoken, "get_encoding", failing_constructor)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(token_utils.count_tokens, ["hello"] * 16))

    assert all(result == token_utils.approximate_token_count("hello") for result in results)
    assert attempts == 1

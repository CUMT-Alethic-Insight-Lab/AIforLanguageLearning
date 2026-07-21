"""对话体验端到端测试：通过 WebSocket TEXT 分支直接测试 LLM 竞速回复。

覆盖场景：
- 正常日语开场
- 用户卡壳 / 纯中文 / 不恰当表述 / 中外混搭
- 模拟 2-5% ASR 错误（音近词/错别字）
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest
from app.llm import chat_complete
from app.main import app
from fastapi.testclient import TestClient


def _expand_scenario(client: TestClient, description: str, language: str = "ja") -> str:
    resp = client.post(
        "/api/v1/model-routing/expand-scenario",
        json={"description": description, "language": language},
    )
    resp.raise_for_status()
    data = resp.json()
    return str(data.get("system_prompt") or data.get("expanded_scenario") or "")


def _run_text_turn(ws, text: str, request_id: str | None = None) -> dict:
    req_id = request_id or f"text_{uuid.uuid4().hex[:8]}"
    ws.send_json({"type": "TEXT", "request_id": req_id, "payload": {"text": text}})
    seen: list[dict] = []
    for _ in range(60):
        msg = ws.receive_json()
        seen.append(msg)
        if msg.get("type") == "TASK_FINISHED" and msg.get("request_id") == req_id:
            break
    llm_msgs = [m for m in seen if m.get("type") == "LLM_RESULT" and m.get("request_id") == req_id]
    tts_msgs = [m for m in seen if m.get("type") == "TTS_RESULT" and m.get("request_id") == req_id]
    return {
        "request_id": req_id,
        "llm": llm_msgs[-1] if llm_msgs else None,
        "tts": tts_msgs[-1] if tts_msgs else None,
        "all": seen,
    }


@pytest.mark.integration
@pytest.mark.timeout(300)
def test_dialogue_experience_japanese_airport(monkeypatch: pytest.MonkeyPatch) -> None:
    """真实对话体验测试：日语机场值机场景。"""

    if os.getenv("AIFL_RUN_INTEGRATION", "").strip() not in {"1", "true", "True"}:
        pytest.skip("integration tests disabled (set AIFL_RUN_INTEGRATION=1)")

    async def _single_chunk_stream_chat(*, system_prompt: str, user_text: str, history=None):
        text = await chat_complete(system_prompt=system_prompt, user_text=user_text, history=history)
        if text:
            yield text

    monkeypatch.setattr("app.main.stream_chat", _single_chunk_stream_chat)

    with TestClient(app) as client:
        system_prompt = _expand_scenario(
            client,
            "我要在东京机场办理值机并询问行李超重和转机时间，目标练习日语口语",
            language="ja",
        )
        assert system_prompt, "扩写失败，system_prompt 为空"

        with client.websocket_connect("/ws/v1?session_id=dial_test&conversation_id=conv_dial_1") as ws:
            _ = ws.receive_json()  # TASK_STARTED

            # 设置场景
            ctx_req = f"ctx_{uuid.uuid4().hex[:8]}"
            ws.send_json({
                "type": "CONTEXT_SET",
                "request_id": ctx_req,
                "payload": {"system_prompt": system_prompt, "language": "ja"},
            })
            for _ in range(10):
                msg = ws.receive_json()
                if msg.get("type") == "CONTEXT_SET" and msg.get("request_id") == ctx_req:
                    break

            results: list[dict] = []

            # 1. 正常日语开场
            results.append({"case": "normal_opening", **_run_text_turn(ws, "こんにちは、チェックインをお願いします。")})

            # 2. 用户卡壳
            results.append({"case": "stuck", **_run_text_turn(ws, "えーと……")})

            # 3. 纯中文提问
            results.append({"case": "chinese_only", **_run_text_turn(ws, "我的行李超重了吗？")})

            # 4. 不恰当表述（直接命令式）
            results.append({"case": "rude_direct", **_run_text_turn(ws, "水をくれ")})

            # 5. 模拟 ASR 错误：音近词（は/わ 混淆）
            results.append({"case": "asr_error_wa", **_run_text_turn(ws, "わたしわ 東京に行きます")})

    # 持久化结果供人工审阅
    log_path = Path(__file__).resolve().parents[1] / "logs" / "dialogue_experience_test.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    # 基本断言：每轮都有 LLM 返回
    for r in results:
        assert r["llm"] is not None, f"{r['case']} 没有收到 LLM_RESULT"
        payload = dict(r["llm"].get("payload") or {})
        markdown = str(payload.get("markdown") or "").strip()
        assert markdown, f"{r['case']} LLM 返回为空"
        print(f"[{r['case']}] source={payload.get('source')} preview={markdown[:60]}")

    # 断言：正常开场应该收到日语回复
    normal_md = str(results[0]["llm"].get("payload", {}).get("markdown", ""))
    assert any(c in normal_md for c in "はがですを"), "正常开场未收到日语回复"

    # 断言：卡壳场景应该收到引导/提示（而不是空白或错误）
    stuck_md = str(results[1]["llm"].get("payload", {}).get("markdown", ""))
    assert len(stuck_md) > 10, "卡壳场景回复过短"

    # 断言：中文提问应该收到双语回复（含 💡 学习提示 或 中文解释）
    chinese_md = str(results[2]["llm"].get("payload", {}).get("markdown", ""))
    assert "💡" in chinese_md or "学习" in chinese_md or "提示" in chinese_md or "意思是" in chinese_md or any(c in chinese_md for c in "はがですを"), "中文提问未收到预期双语回复"

    # 断言：不恰当表述应该被修正或引导（recasting / 文化语用纠错）
    rude_md = str(results[3]["llm"].get("payload", {}).get("markdown", ""))
    # 允许直接修正，也允许场景内自然 recasting；至少要有内容
    assert len(rude_md) > 10, "不恰当表述回复过短"

    # 断言：ASR 错误场景不应直接粗暴纠正，应先确认或温和处理
    asr_md = str(results[4]["llm"].get("payload", {}).get("markdown", ""))
    # 不期望出现严厉的"你错了"，但允许出现确认句
    assert "間違い" not in asr_md or "すみません" in asr_md, "ASR 错误场景处理过于生硬"

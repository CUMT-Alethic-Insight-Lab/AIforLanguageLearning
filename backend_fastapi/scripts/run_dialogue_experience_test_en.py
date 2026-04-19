"""独立脚本：英文场景对话体验端到端测试。"""

import asyncio
import base64
import json
import uuid
from pathlib import Path

import httpx
import websockets


def _expand_scenario_sync(description: str, language: str = "en") -> str:
    resp = httpx.post(
        "http://127.0.0.1:8012/api/v1/model-routing/expand-scenario",
        json={"description": description, "language": language},
        timeout=60.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return str(data.get("system_prompt") or data.get("expanded_scenario") or "")


async def _run_text_turn(ws, text: str, request_id: str | None = None) -> dict:
    req_id = request_id or f"text_{uuid.uuid4().hex[:8]}"
    await ws.send(json.dumps({"type": "TEXT", "request_id": req_id, "payload": {"text": text}}))
    seen: list[dict] = []
    for _ in range(60):
        msg = json.loads(await ws.recv())
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


async def main() -> None:
    system_prompt = _expand_scenario_sync(
        "I want to check in at a hotel in New York and ask about breakfast hours and gym access, practicing spoken English",
        language="en",
    )
    assert system_prompt, "扩写失败，system_prompt 为空"
    print("[OK] 扩写成功，长度:", len(system_prompt))

    async with websockets.connect("ws://127.0.0.1:8012/ws/v1?session_id=dial_test_en&conversation_id=conv_dial_en_1") as ws:
        _ = json.loads(await ws.recv())  # TASK_STARTED

        # 设置场景
        ctx_req = f"ctx_{uuid.uuid4().hex[:8]}"
        await ws.send(json.dumps({
            "type": "CONTEXT_SET",
            "request_id": ctx_req,
            "payload": {"system_prompt": system_prompt, "language": "en"},
        }))
        for _ in range(10):
            msg = json.loads(await ws.recv())
            if msg.get("type") == "CONTEXT_SET" and msg.get("request_id") == ctx_req:
                break

        results: list[dict] = []

        # 1. 正常英语开场
        results.append({"case": "normal_opening", **await _run_text_turn(ws, "Hi, I have a reservation.")})

        # 2. 用户卡壳
        results.append({"case": "stuck", **await _run_text_turn(ws, "Um...")})

        # 3. 纯中文提问
        results.append({"case": "chinese_only", **await _run_text_turn(ws, "早餐是免费的吗？")})

        # 4. 不恰当表述（直接命令式）
        results.append({"case": "rude_direct", **await _run_text_turn(ws, "Give me a better room.")})

        # 5. 中外混搭
        results.append({"case": "mixed_lang", **await _run_text_turn(ws, "我的 room number 是多少？")})

        # 6. 模拟 ASR 错误：音近词（can / can't 语调或识别混淆）
        results.append({"case": "asr_error_can", **await _run_text_turn(ws, "I can swim in the pool?")})

        # 7. 模拟 ASR 错误：数字/时间识别错误
        results.append({"case": "asr_error_time", **await _run_text_turn(ws, "Breakfast starts at 6:30? No, 7:30.")})

        # 8. 模拟 ASR 错误：个别错别字（gym → jim）
        results.append({"case": "asr_error_typo", **await _run_text_turn(ws, "Is the jim open 24 hours?")})

    # 持久化结果
    log_dir = Path("e:/projects/AiforForiegnLanguageLearning/backend_fastapi/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "dialogue_experience_test_en.json"
    log_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] 结果已保存: {log_path}")

    # 输出摘要
    for r in results:
        payload = dict(r["llm"].get("payload") or {}) if r["llm"] else {}
        markdown = str(payload.get("markdown") or "").strip()
        source = str(payload.get("source") or "unknown")
        print(f"[{r['case']}] source={source} len={len(markdown)}")
        print(f"  preview: {markdown[:120]}")

    # 快速断言
    normal_md = str(results[0]["llm"].get("payload", {}).get("markdown", ""))
    assert any(w in normal_md.lower() for w in ["welcome", "check", "reservation", "room", "hotel"]), "正常开场未收到英语回复"

    stuck_md = str(results[1]["llm"].get("payload", {}).get("markdown", ""))
    assert len(stuck_md) > 10, "卡壳场景回复过短"

    chinese_md = str(results[2]["llm"].get("payload", {}).get("markdown", ""))
    assert "💡" in chinese_md or "学习" in chinese_md or "提示" in chinese_md or "意思是" in chinese_md or any(c in chinese_md for c in "theisare"), "中文提问未收到预期双语回复"

    rude_md = str(results[3]["llm"].get("payload", {}).get("markdown", ""))
    assert len(rude_md) > 10, "不恰当表述回复过短"

    asr_md = str(results[5]["llm"].get("payload", {}).get("markdown", ""))
    assert len(asr_md) > 10, "ASR模拟场景回复过短"

    typo_md = str(results[7]["llm"].get("payload", {}).get("markdown", ""))
    assert any(w in typo_md.lower() for w in ["gym", "fitness", "exercise", "workout", "24"]), "ASR typo场景未拉回健身房/酒店场景"

    print("\n[ALL PASSED]")


if __name__ == "__main__":
    asyncio.run(main())

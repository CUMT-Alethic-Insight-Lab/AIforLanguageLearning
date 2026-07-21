"""独立脚本：对话体验端到端测试（不依赖内部模块导入）。"""

import asyncio
import base64
import json
import uuid
from pathlib import Path

import httpx
import websockets


def _expand_scenario_sync(description: str, language: str = "ja") -> str:
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
        "我要在东京机场办理值机并询问行李超重和转机时间，目标练习日语口语",
        language="ja",
    )
    assert system_prompt, "扩写失败，system_prompt 为空"
    print("[OK] 扩写成功，长度:", len(system_prompt))

    async with websockets.connect("ws://127.0.0.1:8012/ws/v1?session_id=dial_test&conversation_id=conv_dial_1") as ws:
        _ = json.loads(await ws.recv())  # TASK_STARTED

        # 设置场景
        ctx_req = f"ctx_{uuid.uuid4().hex[:8]}"
        await ws.send(json.dumps({
            "type": "CONTEXT_SET",
            "request_id": ctx_req,
            "payload": {"system_prompt": system_prompt, "language": "ja"},
        }))
        for _ in range(10):
            msg = json.loads(await ws.recv())
            if msg.get("type") == "CONTEXT_SET" and msg.get("request_id") == ctx_req:
                break

        results: list[dict] = []

        # 1. 正常日语开场
        results.append({"case": "normal_opening", **await _run_text_turn(ws, "こんにちは、チェックインをお願いします。")})

        # 2. 用户卡壳
        results.append({"case": "stuck", **await _run_text_turn(ws, "えーと……")})

        # 3. 纯中文提问
        results.append({"case": "chinese_only", **await _run_text_turn(ws, "我的行李超重了吗？")})

        # 4. 不恰当表述（直接命令式）
        results.append({"case": "rude_direct", **await _run_text_turn(ws, "水をくれ")})

        # 5. 中外混搭
        results.append({"case": "mixed_lang", **await _run_text_turn(ws, "我的 boarding pass 在哪里？")})

        # 6. 模拟 ASR 错误：音近词（は/わ 混淆）
        results.append({"case": "asr_error_wa", **await _run_text_turn(ws, "わたしわ 東京に行きます")})

        # 7. 模拟 ASR 错误：数字/时间识别错误
        results.append({"case": "asr_error_time", **await _run_text_turn(ws, "フライトは 13時30分ですか？いいえ、3時です")})

        # 8. 模拟 ASR 错误：个别错别字（にほんご → にほんこ），但整句仍与场景相关
        results.append({"case": "asr_error_typo", **await _run_text_turn(ws, "にほんこ で はなせます か")})

    # 持久化结果
    log_dir = Path(__file__).resolve().parents[1] / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "dialogue_experience_test.json"
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
    assert any(c in normal_md for c in "はがですを"), "正常开场未收到日语回复"

    stuck_md = str(results[1]["llm"].get("payload", {}).get("markdown", ""))
    assert len(stuck_md) > 10, "卡壳场景回复过短"

    chinese_md = str(results[2]["llm"].get("payload", {}).get("markdown", ""))
    assert "💡" in chinese_md or "学习" in chinese_md or "提示" in chinese_md or "意思是" in chinese_md or any(c in chinese_md for c in "はがですを"), "中文提问未收到预期双语回复"

    rude_md = str(results[3]["llm"].get("payload", {}).get("markdown", ""))
    assert len(rude_md) > 10, "不恰当表述回复过短"

    asr_md = str(results[5]["llm"].get("payload", {}).get("markdown", ""))
    assert "間違い" not in asr_md or "すみません" in asr_md, "ASR 错误场景处理过于生硬"

    print("\n[ALL PASSED]")


if __name__ == "__main__":
    asyncio.run(main())

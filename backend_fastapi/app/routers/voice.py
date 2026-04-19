from __future__ import annotations

import base64

from fastapi import APIRouter
from pydantic import BaseModel

from ..prompts import render_prompt
from ..tts import synthesize_tts_wav

router = APIRouter(prefix="/api/voice", tags=["voice"])


class GeneratePromptRequest(BaseModel):
    scenario: str
    language: str


class GeneratePromptResponse(BaseModel):
    success: bool
    systemPrompt: str


@router.post("/generate-prompt", response_model=GeneratePromptResponse)
async def generate_prompt(req: GeneratePromptRequest) -> GeneratePromptResponse:
    scenario = (req.scenario or "").strip()
    language = (req.language or "").strip()

    # 最小可用：不依赖 LLM 可用性，直接用模板生成 system prompt。
    # 前端会允许用户在 review step 里编辑。
    system_prompt = render_prompt("voice_system_prompt.j2", scenario=scenario, language=language)

    return GeneratePromptResponse(success=True, systemPrompt=system_prompt)


class StartSessionRequest(BaseModel):
    systemPrompt: str


class StartSessionResponse(BaseModel):
    success: bool
    openingText: str
    openingAudio: str


@router.post("/start", response_model=StartSessionResponse)
async def start_session(req: StartSessionRequest) -> StartSessionResponse:
    system_prompt = (req.systemPrompt or "").strip()

    # 从 system prompt 中推断场景，生成对应的开场白
    scenario_hints = {
        "restaurant": "欢迎来到餐厅场景，让我们一起练习点餐吧。",
        "airport": "欢迎来到机场场景，让我们一起练习登机手续吧。",
        "hotel": "欢迎来到酒店场景，让我们一起练习入住登记吧。",
        "shopping": "欢迎来到购物场景，让我们一起练习选购商品吧。",
        "interview": "欢迎来到面试场景，让我们一起练习自我介绍吧。",
    }

    opening_text = "好的，我们开始练习吧。你可以先说一句话。"
    if system_prompt:
        lower_sp = system_prompt.lower()
        for key, hint in scenario_hints.items():
            if key in lower_sp:
                opening_text = hint
                break

    wav = synthesize_tts_wav(opening_text)
    opening_audio_b64 = base64.b64encode(wav).decode("utf-8") if wav else ""
    return StartSessionResponse(success=True, openingText=opening_text, openingAudio=opening_audio_b64)

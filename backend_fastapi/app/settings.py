from __future__ import annotations

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_env: str = Field(
        default="development", validation_alias=AliasChoices("AIFL_APP_ENV", "APP_ENV")
    )
    port: int = Field(default=8012, validation_alias=AliasChoices("AIFL_PORT", "PORT"))
    enable_legacy_compat_api: bool = Field(
        default=True,
        validation_alias=AliasChoices("AIFL_ENABLE_LEGACY_COMPAT_API", "ENABLE_LEGACY_COMPAT_API"),
    )

    # LM Studio (OpenAI compatible)
    llm_base_url: str = Field(
        default="http://127.0.0.1:1234/v1",
        validation_alias=AliasChoices("AIFL_LLM_BASE_URL", "LLM_BASE_URL"),
    )
    llm_api_key: str = Field(
        default="lm-studio", validation_alias=AliasChoices("AIFL_LLM_API_KEY", "LLM_API_KEY")
    )

    llm_model: str = Field(
        default="qwen/qwen3.5-9b", validation_alias=AliasChoices("AIFL_LLM_MODEL", "LLM_MODEL")
    )
    llm_timeout_seconds: float = Field(
        default=30.0,
        validation_alias=AliasChoices("AIFL_LLM_TIMEOUT_SECONDS", "LLM_TIMEOUT_SECONDS"),
    )
    kimi_base_url: str = Field(
        default="https://api.moonshot.cn/v1",
        validation_alias=AliasChoices("AIFL_KIMI_BASE_URL", "KIMI_BASE_URL"),
    )
    kimi_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("AIFL_KIMI_API_KEY", "KIMI_API_KEY"),
    )

    # DB
    database_url: str = Field(
        default="sqlite:///./data/app.db",
        validation_alias=AliasChoices("AIFL_DATABASE_URL", "DATABASE_URL"),
    )

    jwt_secret: str = Field(
        default="your-super-secret-key-change-this-in-production",
        validation_alias=AliasChoices("AIFL_JWT_SECRET", "JWT_SECRET"),
    )
    seed_admin_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("AIFL_SEED_ADMIN_ENABLED", "SEED_ADMIN_ENABLED"),
    )
    seed_admin_username: str = Field(
        default="admin",
        validation_alias=AliasChoices("AIFL_SEED_ADMIN_USERNAME", "SEED_ADMIN_USERNAME"),
    )
    seed_admin_email: str = Field(
        default="admin@helix.local",
        validation_alias=AliasChoices("AIFL_SEED_ADMIN_EMAIL", "SEED_ADMIN_EMAIL"),
    )
    seed_admin_password: str = Field(
        default="Admin1234!",
        validation_alias=AliasChoices("AIFL_SEED_ADMIN_PASSWORD", "SEED_ADMIN_PASSWORD"),
    )

    @model_validator(mode="after")
    def reject_insecure_production_auth_defaults(self) -> Settings:
        environment = str(self.app_env or "").strip().lower()
        if environment in {"development", "dev", "local", "test", "testing"}:
            return self

        insecure_settings: list[str] = []
        if not self.jwt_secret or self.jwt_secret in {
            "your-super-secret-key-change-this-in-production",
            "change-me-in-production",
        }:
            insecure_settings.append("AIFL_JWT_SECRET")
        if self.seed_admin_enabled and (
            not self.seed_admin_password or self.seed_admin_password == "Admin1234!"
        ):
            insecure_settings.append("AIFL_SEED_ADMIN_PASSWORD")

        if insecure_settings:
            names = ", ".join(insecure_settings)
            raise ValueError(
                f"Unsafe authentication defaults for {environment or 'non-development'}: {names}"
            )
        return self

    # Infrastructure
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias=AliasChoices("AIFL_REDIS_URL", "REDIS_URL"),
    )
    es_url: str = Field(
        default="http://localhost:9200",
        validation_alias=AliasChoices("AIFL_ES_URL", "ES_URL"),
    )
    neo4j_url: str = Field(
        default="bolt://localhost:7687",
        validation_alias=AliasChoices("AIFL_NEO4J_URL", "NEO4J_URL"),
    )
    neo4j_user: str = Field(
        default="neo4j",
        validation_alias=AliasChoices("AIFL_NEO4J_USER", "NEO4J_USER"),
    )
    neo4j_password: str = Field(
        default="password",
        validation_alias=AliasChoices("AIFL_NEO4J_PASSWORD", "NEO4J_PASSWORD"),
    )
    minio_endpoint: str = Field(
        default="localhost:9000",
        validation_alias=AliasChoices("AIFL_MINIO_ENDPOINT", "MINIO_ENDPOINT"),
    )
    minio_access_key: str = Field(
        default="minioadmin",
        validation_alias=AliasChoices("AIFL_MINIO_ACCESS_KEY", "MINIO_ACCESS_KEY"),
    )
    minio_secret_key: str = Field(
        default="minioadmin",
        validation_alias=AliasChoices("AIFL_MINIO_SECRET_KEY", "MINIO_SECRET_KEY"),
    )

    # Voice (P0): 默认开启；若运行环境缺少 ASR 依赖，会降级为“ASR 后端不可用”的提示文本。
    enable_asr: bool = Field(
        default=True, validation_alias=AliasChoices("AIFL_ENABLE_ASR", "ENABLE_ASR")
    )
    asr_backend: str = Field(
        default="seamless",
        validation_alias=AliasChoices("AIFL_ASR_BACKEND", "ASR_BACKEND"),
    )
    asr_model: str = Field(
        default="small", validation_alias=AliasChoices("AIFL_ASR_MODEL", "ASR_MODEL")
    )
    asr_device: str = Field(
        default="cpu", validation_alias=AliasChoices("AIFL_ASR_DEVICE", "ASR_DEVICE")
    )
    asr_compute_type: str = Field(
        default="int8",
        validation_alias=AliasChoices("AIFL_ASR_COMPUTE_TYPE", "ASR_COMPUTE_TYPE"),
    )
    asr_local_files_only: bool = Field(
        default=True,
        validation_alias=AliasChoices("AIFL_ASR_LOCAL_FILES_ONLY", "ASR_LOCAL_FILES_ONLY"),
    )

    # Voice WS: 请求级别空闲超时（秒）；防止客户端未发送 AUDIO_END 导致会话长期占用。
    voice_request_idle_seconds: int = 30

    # Voice VAD（P1）：停顿判定，支持“无需客户端发送 AUDIO_END 也能自动收句”。
    enable_vad: bool = Field(
        default=True,
        validation_alias=AliasChoices("AIFL_ENABLE_VAD", "ENABLE_VAD"),
    )
    vad_mode: int = Field(default=2, validation_alias=AliasChoices("AIFL_VAD_MODE", "VAD_MODE"))
    vad_silence_ms: int = Field(
        default=800,
        validation_alias=AliasChoices("AIFL_VAD_SILENCE_MS", "VAD_SILENCE_MS"),
    )

    # TTS（P1）：默认使用 Kokoro（轻量 CPU real-time）；若依赖不可用，代码层自动回退到静音 wav。
    tts_backend: str = Field(
        default="kokoro",
        validation_alias=AliasChoices("AIFL_TTS_BACKEND", "TTS_BACKEND"),
    )
    tts_chunk_size_bytes: int = Field(
        default=16 * 1024,
        validation_alias=AliasChoices("AIFL_TTS_CHUNK_SIZE_BYTES", "TTS_CHUNK_SIZE_BYTES"),
    )

    # Kokoro TTS (lightweight, CPU, recommended)
    kokoro_lang_code: str = Field(
        default="a",
        validation_alias=AliasChoices("AIFL_KOKORO_LANG_CODE", "KOKORO_LANG_CODE"),
    )
    kokoro_voice: str = Field(
        default="af_bella",
        validation_alias=AliasChoices("AIFL_KOKORO_VOICE", "KOKORO_VOICE"),
    )
    kokoro_speed: float = Field(
        default=1.0,
        validation_alias=AliasChoices("AIFL_KOKORO_SPEED", "KOKORO_SPEED"),
    )

    # Edge TTS (online, free, multilingual fallback)
    edge_tts_voice: str = Field(
        default="en-US-AriaNeural",
        validation_alias=AliasChoices("AIFL_EDGE_TTS_VOICE", "EDGE_TTS_VOICE"),
    )
    edge_tts_speed: str = Field(
        default="+0%",
        validation_alias=AliasChoices("AIFL_EDGE_TTS_SPEED", "EDGE_TTS_SPEED"),
    )

    # Real-time Teaching Assistant
    rta_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("AIFL_RTA_ENABLED", "RTA_ENABLED"),
    )
    rta_llm_model: str = Field(
        default="moonshot-v1-auto",
        validation_alias=AliasChoices("AIFL_RTA_LLM_MODEL", "RTA_LLM_MODEL"),
    )
    rta_llm_base_url: str = Field(
        default="",
        validation_alias=AliasChoices("AIFL_RTA_LLM_BASE_URL", "RTA_LLM_BASE_URL"),
    )
    rta_llm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("AIFL_RTA_LLM_API_KEY", "RTA_LLM_API_KEY"),
    )
    rta_llm_timeout_seconds: float = Field(
        default=15.0,
        validation_alias=AliasChoices("AIFL_RTA_LLM_TIMEOUT", "RTA_LLM_TIMEOUT"),
    )
    rta_cooldown_seconds: float = Field(
        default=5.0,
        validation_alias=AliasChoices("AIFL_RTA_COOLDOWN", "RTA_COOLDOWN"),
    )
    rta_max_context_turns: int = Field(
        default=6,
        validation_alias=AliasChoices("AIFL_RTA_MAX_CONTEXT", "RTA_MAX_CONTEXT"),
    )
    rta_tts_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("AIFL_RTA_TTS_ENABLED", "RTA_TTS_ENABLED"),
    )
    rta_ocr_language: str = Field(
        default="english",
        validation_alias=AliasChoices("AIFL_RTA_OCR_LANG", "RTA_OCR_LANG"),
    )


settings = Settings()

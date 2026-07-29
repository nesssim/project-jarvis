from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceEndpoint(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


class RedisStreamsConfig(BaseModel):
    consumer_group: str = "jarvis"
    max_length: int = 10000


class RedisConfig(BaseModel):
    url: str = "redis://:password@redis:6379/0"
    streams: RedisStreamsConfig = RedisStreamsConfig()


class OllamaConfig(BaseModel):
    url: str = "http://ollama:11434"
    model: str = "qwen2.5:8b"
    keep_alive: int = -1


class GroqConfig(BaseModel):
    api_key: str = ""
    model: str = "llama-3.3-70b-versatile"


class GeminiConfig(BaseModel):
    api_key: str = ""
    model: str = "gemini-2.0-flash"


class GenerationConfig(BaseModel):
    max_tokens: int = 512
    temperature: float = 0.7
    top_p: float = 0.9


class LLMConfig(BaseModel):
    provider: Literal["ollama", "groq", "gemini"] = "ollama"
    ollama: OllamaConfig = OllamaConfig()
    groq: GroqConfig = GroqConfig()
    gemini: GeminiConfig = GeminiConfig()
    generation: GenerationConfig = GenerationConfig()


class WhisperConfig(BaseModel):
    model_size: str = "base"
    device: str = "cpu"
    compute_type: str = "int8"


class VADConfig(BaseModel):
    threshold: float = 0.5
    silence_duration_ms: int = 800


class STTConfig(BaseModel):
    provider: Literal["whisper"] = "whisper"
    whisper: WhisperConfig = WhisperConfig()
    vad: VADConfig = VADConfig()


class PiperConfig(BaseModel):
    voice: str = "default"
    model_path: str = "/models/piper"


class KokoroConfig(BaseModel):
    voice: str = "default"


class TTSConfig(BaseModel):
    provider: Literal["piper", "kokoro"] = "piper"
    piper: PiperConfig = PiperConfig()
    kokoro: KokoroConfig = KokoroConfig()


class AudioConfig(BaseModel):
    sample_rate: int = 16000
    channels: int = 1
    sample_width: int = 2
    chunk_size_ms: int = 100


class ListeningConfig(BaseModel):
    timeout_seconds: int = 5
    silence_threshold_ms: int = 800


class ChromaDBConfig(BaseModel):
    path: str = "/data/chromadb"


class ShortTermMemoryConfig(BaseModel):
    max_turns: int = 20


class LongTermMemoryConfig(BaseModel):
    provider: str = "chromadb"
    chromadb: ChromaDBConfig = ChromaDBConfig()
    embedding_model: str = "nomic-embed-text"
    max_facts_per_query: int = 5
    latency_threshold_ms: int = 100


class MemoryConfig(BaseModel):
    short_term: ShortTermMemoryConfig = ShortTermMemoryConfig()
    long_term: LongTermMemoryConfig = LongTermMemoryConfig()


class WebSearchConfig(BaseModel):
    provider: str = "searxng"
    searxng_url: str = "http://searxng:8888"
    fallback_provider: str = "duckduckgo"


class SandboxConfig(BaseModel):
    allowed_directory: str = "/data/sandbox"


class ToolsConfig(BaseModel):
    web_search: WebSearchConfig = WebSearchConfig()
    sandbox: SandboxConfig = SandboxConfig()
    safety_tiers: dict[str, list[str]] = {
        "safe": ["get_datetime", "web_search", "read_file"],
        "confirm": ["send_email", "write_file", "delete_file"],
        "restricted": ["execute_command", "modify_system", "control_hardware"],
    }


class RateLimitConfig(BaseModel):
    default: str = "60/minute"
    per_endpoint: dict[str, str] = {"/chat": "30/minute", "/health": "120/minute"}


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: Literal["json", "text"] = "json"
    correlation_id: bool = True
    redact_fields: list[str] = ["api_key", "password", "token"]

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR"}
        if v.upper() not in allowed:
            raise ValueError(f"Invalid log level: {v}. Must be one of {allowed}")
        return v.upper()


class CORSConfig(BaseModel):
    allowed_origins: list[str] = ["http://localhost:3000", "http://localhost:8000"]
    allow_credentials: bool = True
    allow_methods: list[str] = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    allow_headers: list[str] = ["Content-Type", "Authorization", "X-API-Key"]


class AuthConfig(BaseModel):
    enabled: bool = False
    api_key_header: str = "X-API-Key"
    api_key: str = ""


class ShutdownConfig(BaseModel):
    grace_period_seconds: int = 10
    force_exit_after_seconds: int = 15


class ServiceConfig(BaseModel):
    orchestrator: ServiceEndpoint = ServiceEndpoint()
    stt: ServiceEndpoint = ServiceEndpoint(port=8001)
    tts: ServiceEndpoint = ServiceEndpoint(port=8002)
    memory: ServiceEndpoint = ServiceEndpoint(port=8003)
    tools: ServiceEndpoint = ServiceEndpoint(port=8004)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service: ServiceConfig = ServiceConfig()
    redis: RedisConfig = RedisConfig()
    llm: LLMConfig = LLMConfig()
    stt: STTConfig = STTConfig()
    tts: TTSConfig = TTSConfig()
    audio: AudioConfig = AudioConfig()
    listening: ListeningConfig = ListeningConfig()
    memory: MemoryConfig = MemoryConfig()
    tools: ToolsConfig = ToolsConfig()
    rate_limiting: RateLimitConfig = RateLimitConfig()
    logging: LoggingConfig = LoggingConfig()
    cors: CORSConfig = CORSConfig()
    auth: AuthConfig = AuthConfig()
    shutdown: ShutdownConfig = ShutdownConfig()

    @classmethod
    def from_yaml(cls, path: Path) -> Settings:
        if not path.exists():
            raise FileNotFoundError(f"Settings file not found: {path}")
        with path.open() as f:
            raw = f.read()
        expanded = os.path.expandvars(raw)
        data = yaml.safe_load(expanded)
        return cls(**data)

    def validate_provider_keys(self) -> None:
        if self.llm.provider == "groq" and not self.llm.groq.api_key:
            raise ValueError(
                "LLM provider is 'groq' but GROQ_API_KEY is not set. "
                "Set it in .env or switch provider to 'ollama'."
            )
        if self.llm.provider == "gemini" and not self.llm.gemini.api_key:
            raise ValueError(
                "LLM provider is 'gemini' but GEMINI_API_KEY is not set. "
                "Set it in .env or switch provider to 'ollama'."
            )


def load_settings(yaml_path: str | None = None) -> Settings:
    env_file = Path(".env")
    if env_file.exists():
        load_dotenv(env_file, override=False)
    if yaml_path:
        settings = Settings.from_yaml(Path(yaml_path))
    else:
        yaml_candidate = Path("config/settings.yaml")
        settings = (
            Settings.from_yaml(yaml_candidate)
            if yaml_candidate.exists()
            else Settings()
        )
    settings.validate_provider_keys()
    return settings

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from shared.config import Settings, load_settings


def test_settings_defaults() -> None:
    settings = Settings()
    assert settings.service.orchestrator.port == 8000
    assert settings.service.stt.port == 8001
    assert settings.llm.provider == "ollama"
    assert settings.llm.ollama.model == "qwen2.5:8b"
    assert settings.stt.whisper.model_size == "base"
    assert settings.tts.provider == "piper"
    assert settings.audio.sample_rate == 16000
    assert settings.shutdown.grace_period_seconds == 10


def test_settings_env_override() -> None:
    os.environ["LLM__PROVIDER"] = "groq"
    os.environ["GROQ__API_KEY"] = "test-key"
    settings = Settings()
    assert settings.llm.provider == "groq"
    del os.environ["LLM__PROVIDER"]
    del os.environ["GROQ__API_KEY"]


def test_settings_yaml_roundtrip(tmp_path: Path) -> None:
    settings = Settings()
    yaml_path = tmp_path / "test_settings.yaml"
    data = settings.model_dump()
    with yaml_path.open("w") as f:
        yaml.dump(data, f)
    loaded = Settings.from_yaml(yaml_path)
    assert loaded.service.orchestrator.port == settings.service.orchestrator.port
    assert loaded.llm.provider == settings.llm.provider


def test_settings_missing_yaml_raises() -> None:
    with pytest.raises(FileNotFoundError):
        Settings.from_yaml(Path("/nonexistent/settings.yaml"))


def test_log_level_validation() -> None:
    settings = Settings(logging={"level": "DEBUG"})
    assert settings.logging.level == "DEBUG"
    with pytest.raises(ValueError):
        Settings(logging={"level": "INVALID"})


def test_validate_provider_keys_missing_groq() -> None:
    settings = Settings(llm={"provider": "groq", "groq": {"api_key": ""}})
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        settings.validate_provider_keys()


def test_validate_provider_keys_missing_gemini() -> None:
    settings = Settings(llm={"provider": "gemini", "gemini": {"api_key": ""}})
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        settings.validate_provider_keys()


def test_validate_provider_keys_ollama_ok() -> None:
    settings = Settings(llm={"provider": "ollama"})
    settings.validate_provider_keys()


def test_rate_limit_config() -> None:
    settings = Settings(
        rate_limiting={"default": "30/minute", "per_endpoint": {"/chat": "10/minute"}}
    )
    assert settings.rate_limiting.default == "30/minute"
    assert settings.rate_limiting.per_endpoint["/chat"] == "10/minute"


def test_audio_config() -> None:
    settings = Settings(audio={"sample_rate": 44100, "channels": 2})
    assert settings.audio.sample_rate == 44100
    assert settings.audio.channels == 2


def test_shutdown_config() -> None:
    settings = Settings(shutdown={"grace_period_seconds": 30})
    assert settings.shutdown.grace_period_seconds == 30


def test_load_settings_no_yaml() -> None:
    settings = load_settings()
    assert settings is not None


def test_yaml_env_var_expansion(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEST_REDIS_PASSWORD", "strong_pass_123")
    yaml_path = tmp_path / "settings.yaml"
    yaml_path.write_text(
        'redis:\n  url: "redis://:${TEST_REDIS_PASSWORD}@redis:6379/0"\n'
    )
    settings = Settings.from_yaml(yaml_path)
    assert settings.redis.url == "redis://:strong_pass_123@redis:6379/0"


def test_cors_config_defaults() -> None:
    settings = Settings()
    assert "http://localhost:3000" in settings.cors.allowed_origins
    assert settings.cors.allow_credentials is True


def test_auth_config_defaults() -> None:
    settings = Settings()
    assert settings.auth.enabled is False
    assert settings.auth.api_key_header == "X-API-Key"

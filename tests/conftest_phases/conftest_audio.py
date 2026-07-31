from __future__ import annotations

from pathlib import Path

import pytest
from shared.audio import FileAudioSource, NullAudioSink

AUDIO_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "audio"


@pytest.fixture
def audio_fixture_dir() -> Path:
    return AUDIO_FIXTURE_DIR


@pytest.fixture
def clean_speech_source() -> FileAudioSource:
    return FileAudioSource(str(AUDIO_FIXTURE_DIR / "speech_clean_16khz.wav"))


@pytest.fixture
def clean_speech_44khz_source() -> FileAudioSource:
    return FileAudioSource(str(AUDIO_FIXTURE_DIR / "speech_clean_44khz.wav"))


@pytest.fixture
def noisy_speech_source() -> FileAudioSource:
    return FileAudioSource(str(AUDIO_FIXTURE_DIR / "speech_noisy_16khz.wav"))


@pytest.fixture
def silence_source() -> FileAudioSource:
    return FileAudioSource(str(AUDIO_FIXTURE_DIR / "silence_1s_16khz.wav"))


@pytest.fixture
def short_utterance_source() -> FileAudioSource:
    return FileAudioSource(str(AUDIO_FIXTURE_DIR / "utterance_short_16khz.wav"))


@pytest.fixture
def null_audio_sink() -> NullAudioSink:
    return NullAudioSink()

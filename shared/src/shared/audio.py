from __future__ import annotations

import struct
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from os import PathLike
from pathlib import Path


class AudioError(Exception):
    """Base exception for audio-related errors."""


class InvalidWAVError(AudioError):
    """Raised when a WAV file has an invalid or unsupported format."""


@dataclass(frozen=True)
class AudioFormat:
    sample_rate: int
    channels: int
    bit_depth: int
    pcm_data_size: int = 0

    @property
    def byte_width(self) -> int:
        return self.bit_depth // 8

    @property
    def frame_size(self) -> int:
        return self.channels * self.byte_width

    @property
    def duration_seconds(self) -> float:
        if self.sample_rate == 0 or self.frame_size == 0:
            return 0.0
        return self.pcm_data_size / (self.sample_rate * self.frame_size)


def parse_wav_header(data: bytes) -> AudioFormat:
    if len(data) < 44:
        raise InvalidWAVError(f"WAV header too short: {len(data)} bytes (minimum 44)")

    if data[:4] != b"RIFF":
        raise InvalidWAVError(f"Not a RIFF file: expected 'RIFF', got {data[:4]!r}")

    if data[8:12] != b"WAVE":
        raise InvalidWAVError(f"Not a WAVE file: expected 'WAVE', got {data[8:12]!r}")

    offset = 12
    fmt_found = False
    sample_rate = 0
    channels = 0
    bit_depth = 0

    while offset + 8 <= len(data):
        chunk_id = data[offset : offset + 4]
        chunk_size = struct.unpack("<I", data[offset + 4 : offset + 8])[0]

        if chunk_id == b"fmt ":
            if offset + 16 > len(data):
                raise InvalidWAVError("Truncated fmt chunk")
            audio_format = struct.unpack("<H", data[offset + 8 : offset + 10])[0]
            if audio_format != 1:
                raise InvalidWAVError(
                    f"Unsupported audio format: {audio_format} (expected 1 = PCM)"
                )
            channels = struct.unpack("<H", data[offset + 10 : offset + 12])[0]
            sample_rate = struct.unpack("<I", data[offset + 12 : offset + 16])[0]
            bit_depth = struct.unpack("<H", data[offset + 22 : offset + 24])[0]
            fmt_found = True
        elif chunk_id == b"data":
            if not fmt_found:
                raise InvalidWAVError("Data chunk found before fmt chunk")
            return AudioFormat(
                sample_rate=sample_rate,
                channels=channels,
                bit_depth=bit_depth,
                pcm_data_size=chunk_size,
            )

        offset += 8 + chunk_size
        if chunk_size % 2 != 0:
            offset += 1

    raise InvalidWAVError("No data chunk found in WAV file")


class AudioSource(ABC):
    @abstractmethod
    def read(self, chunk_size: int = 4096) -> Iterator[bytes]: ...

    @abstractmethod
    def reset(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    def __enter__(self) -> AudioSource:
        """Enter the context manager."""
        return self

    def __exit__(self, *args: object) -> None:
        """Exit the context manager and close the source."""
        self.close()


class AudioSink(ABC):
    @abstractmethod
    def write(self, data: bytes) -> None: ...

    @abstractmethod
    def reset(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    def __enter__(self) -> AudioSink:
        """Enter the context manager."""
        return self

    def __exit__(self, *args: object) -> None:
        """Exit the context manager and close the sink."""
        self.close()


class FileAudioSource(AudioSource):
    def __init__(self, path: str | PathLike[str]) -> None:
        self._path = str(path)
        with Path(self._path).open("rb") as f:
            raw = f.read()

        if not raw:
            raise InvalidWAVError("Empty WAV file")

        self._format = parse_wav_header(raw)

        offset = 12
        while offset + 8 <= len(raw):
            chunk_id = raw[offset : offset + 4]
            chunk_size = struct.unpack("<I", raw[offset + 4 : offset + 8])[0]
            if chunk_id == b"data":
                data_start = offset + 8
                self._pcm_data = raw[data_start : data_start + chunk_size]
                break
            offset += 8 + chunk_size
            if chunk_size % 2 != 0:
                offset += 1
        else:
            raise InvalidWAVError("No data chunk found in WAV file")

        self._pos = 0

    @property
    def sample_rate(self) -> int:
        return self._format.sample_rate

    @property
    def channels(self) -> int:
        return self._format.channels

    @property
    def bit_depth(self) -> int:
        return self._format.bit_depth

    @property
    def pcm_data_size(self) -> int:
        return len(self._pcm_data)

    @property
    def format(self) -> AudioFormat:
        return self._format

    def read(self, chunk_size: int = 4096) -> Iterator[bytes]:
        while self._pos < len(self._pcm_data):
            chunk = self._pcm_data[self._pos : self._pos + chunk_size]
            self._pos += len(chunk)
            yield chunk

    def reset(self) -> None:
        self._pos = 0

    def close(self) -> None:
        self._pos = len(self._pcm_data)


class NullAudioSink(AudioSink):
    def __init__(self) -> None:
        self._total_bytes = 0
        self._start_time: float | None = None
        self._last_write_time: float | None = None

    @property
    def total_bytes_written(self) -> int:
        return self._total_bytes

    @property
    def throughput_bytes_per_sec(self) -> float:
        if self._start_time is None or self._last_write_time is None:
            return 0.0
        elapsed = self._last_write_time - self._start_time
        if elapsed <= 0:
            return 0.0
        return self._total_bytes / elapsed

    def write(self, data: bytes) -> None:
        if not data:
            return
        now = time.monotonic()
        if self._start_time is None:
            self._start_time = now
        self._last_write_time = now
        self._total_bytes += len(data)

    def reset(self) -> None:
        self._total_bytes = 0
        self._start_time = None
        self._last_write_time = None

    def close(self) -> None:
        pass


class MicrophoneAudioSource(AudioSource):
    def __init__(
        self, sample_rate: int = 16000, channels: int = 1, device: int | None = None
    ) -> None:
        self._sample_rate = sample_rate
        self._channels = channels
        self._device = device
        self._stream = None

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def channels(self) -> int:
        return self._channels

    def read(
        self, chunk_size: int = 4096, duration_sec: float | None = None
    ) -> Iterator[bytes]:
        import sounddevice as sd  # type: ignore[import-untyped]

        frames: int | None = None
        if duration_sec is not None:
            frames = int(duration_sec * self._sample_rate)

        recorded = sd.rec(
            frames or chunk_size,
            samplerate=self._sample_rate,
            channels=self._channels,
            dtype="int16",
            device=self._device,
            blocking=True,
        )
        yield recorded.tobytes()

    def reset(self) -> None:
        pass

    def close(self) -> None:
        pass


class SpeakerAudioSink(AudioSink):
    def __init__(
        self, sample_rate: int = 16000, channels: int = 1, device: int | None = None
    ) -> None:
        self._sample_rate = sample_rate
        self._channels = channels
        self._device = device

    def write(self, data: bytes) -> None:
        if not data:
            return
        import numpy as np  # type: ignore[import-untyped]
        import sounddevice as sd  # type: ignore[import-untyped]

        audio = np.frombuffer(data, dtype=np.int16).reshape(-1, self._channels)
        sd.play(audio, samplerate=self._sample_rate, device=self._device)
        sd.wait()

    def reset(self) -> None:
        pass

    def close(self) -> None:
        import sounddevice as sd

        sd.stop()

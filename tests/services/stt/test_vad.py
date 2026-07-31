from __future__ import annotations

import builtins
import pathlib
import sys
import types
import urllib.request

import numpy as np
import pytest
from stt.vad import MODEL_FILENAME, VADError, VADEventType, VADProcessor

ZERO_FRAME = b"\x00\x00" * 256  # 512 samples = one 16kHz frame


class _FakeInput:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeSession:
    def __init__(self, probabilities: list[float]) -> None:
        self._probabilities = list(probabilities)
        self._inputs = [_FakeInput("input"), _FakeInput("input_1"), _FakeInput("sr")]

    def get_inputs(self):
        return self._inputs

    def run(self, _output_names: list[str], _inputs: dict):
        prob = self._probabilities.pop(0) if self._probabilities else 0.0
        return (
            np.array([[prob]], dtype=np.float32),
            np.zeros((2, 1, 64), dtype=np.float32),
            np.zeros((2, 1, 64), dtype=np.float32),
        )


def _install_fake_onnx(monkeypatch: pytest.MonkeyPatch, session_factory) -> None:
    """Inject a fake onnxruntime module so _ensure_model() can load."""
    import stt.vad as vad_module

    fake_ort = types.ModuleType("onnxruntime")
    fake_ort.InferenceSession = session_factory
    fake_ort.SessionOptions = types.SimpleNamespace
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)
    monkeypatch.setattr(vad_module, "onnxruntime", fake_ort, raising=False)


@pytest.fixture
def fake_onnx(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    """Point the VAD at a temp model dir with a fake onnxruntime session."""
    import stt.vad as vad_module

    model_path = tmp_path / "models" / MODEL_FILENAME
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(b"fake-model")
    monkeypatch.setattr(vad_module, "MODEL_DIR", tmp_path / "models")

    _install_fake_onnx(
        monkeypatch, lambda _path, _opts: _FakeSession([0.9, 0.9, 0.1, 0.1, 0.1, 0.1])
    )


class TestVADProcessorInit:
    def test_valid_defaults(self) -> None:
        vad = VADProcessor()
        assert vad.threshold == 0.5
        assert vad.silence_duration_ms == 800
        assert not vad.is_speaking
        assert vad.last_probability == 0.0

    def test_invalid_threshold_low(self) -> None:
        with pytest.raises(VADError, match="threshold"):
            VADProcessor(threshold=0.0)

    def test_invalid_threshold_high(self) -> None:
        with pytest.raises(VADError, match="threshold"):
            VADProcessor(threshold=1.5)

    def test_invalid_silence_duration(self) -> None:
        with pytest.raises(VADError, match="silence_duration_ms"):
            VADProcessor(silence_duration_ms=50)


class TestVADProcessorValidation:
    def test_empty_chunk_raises(self) -> None:
        with pytest.raises(VADError, match="Empty audio chunk"):
            VADProcessor().process(b"")

    def test_odd_length_chunk_raises(self) -> None:
        with pytest.raises(VADError, match="even byte length"):
            VADProcessor().process(b"\x00\x00\x00")


class TestVADProcessorFlow:
    def test_speech_start_end_sequence(self, fake_onnx) -> None:
        vad = VADProcessor(silence_duration_ms=100)

        assert vad.process(ZERO_FRAME).type == VADEventType.SPEECH_START
        assert vad.is_speaking
        assert vad.process(ZERO_FRAME) is None  # continuing speech

        assert vad.process(ZERO_FRAME) is None  # 32ms silence
        assert vad.process(ZERO_FRAME) is None  # 64ms silence
        assert vad.process(ZERO_FRAME) is None  # 96ms silence

        event = vad.process(ZERO_FRAME)  # 128ms >= 100ms silence
        assert event is not None
        assert event.type == VADEventType.SPEECH_END
        assert not vad.is_speaking
        assert vad.last_probability == pytest.approx(0.1)
        assert vad.silence_ms == 0.0

    def test_partial_frame_is_padded(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        import stt.vad as vad_module

        model_path = tmp_path / "models" / MODEL_FILENAME
        model_path.parent.mkdir(parents=True, exist_ok=True)
        model_path.write_bytes(b"fake-model")
        monkeypatch.setattr(vad_module, "MODEL_DIR", tmp_path / "models")

        _install_fake_onnx(
            monkeypatch, lambda _path, _opts: _FakeSession([0.95, 0.1, 0.1, 0.1, 0.1])
        )

        vad = VADProcessor(silence_duration_ms=100)
        event = vad.process(b"\x00\x00" * 50)  # 50 samples < FRAME_SIZE
        assert event is not None
        assert event.type == VADEventType.SPEECH_START

    def test_reset_clears_state(self, fake_onnx) -> None:
        vad = VADProcessor(silence_duration_ms=100)
        vad.process(ZERO_FRAME)
        assert vad.is_speaking
        vad.reset()
        assert not vad.is_speaking
        assert vad.last_probability == 0.0
        assert vad.silence_ms == 0.0


class TestVADProcessorModelLoading:
    def test_missing_onnxruntime_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real_import = builtins.__import__

        def fake_import(name: str, *args, **kwargs):
            if name == "onnxruntime":
                raise ImportError("no onnxruntime")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(VADError, match="onnxruntime not installed"):
            VADProcessor().process(ZERO_FRAME)

    def test_downloads_model_when_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        import stt.vad as vad_module

        model_dir = tmp_path / "empty-models"
        monkeypatch.setattr(vad_module, "MODEL_DIR", model_dir)

        downloaded: list[str] = []

        def fake_download(url: str, path: str) -> None:
            downloaded.append(url)
            pathlib.Path(path).write_bytes(b"fake-model")

        monkeypatch.setattr(urllib.request, "urlretrieve", fake_download)
        _install_fake_onnx(monkeypatch, lambda _path, _opts: _FakeSession([0.9]))

        vad = VADProcessor()
        event = vad.process(ZERO_FRAME)
        assert event is not None
        assert event.type == VADEventType.SPEECH_START
        assert len(downloaded) == 1
        assert (model_dir / MODEL_FILENAME).exists()

    def test_uses_cached_model_without_downloading(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        import stt.vad as vad_module

        model_dir = tmp_path / "cached-models"
        model_dir.mkdir(parents=True, exist_ok=True)
        (model_dir / MODEL_FILENAME).write_bytes(b"fake-model")
        monkeypatch.setattr(vad_module, "MODEL_DIR", model_dir)
        monkeypatch.setattr(
            urllib.request,
            "urlretrieve",
            lambda *_a, **_k: (_ for _ in ()).throw(
                AssertionError("should not download")
            ),
        )
        _install_fake_onnx(monkeypatch, lambda _path, _opts: _FakeSession([0.9]))

        vad = VADProcessor()
        event = vad.process(ZERO_FRAME)
        assert event is not None
        assert event.type == VADEventType.SPEECH_START

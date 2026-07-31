from __future__ import annotations

import struct
from pathlib import Path

import pytest
from shared.audio import (
    AudioFormat,
    AudioSink,
    AudioSource,
    FileAudioSource,
    InvalidWAVError,
    NullAudioSink,
    parse_wav_header,
)

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "audio"


@pytest.fixture
def clean_speech_source() -> FileAudioSource:
    return FileAudioSource(str(FIXTURE_DIR / "speech_clean_16khz.wav"))


@pytest.fixture
def clean_speech_44khz_source() -> FileAudioSource:
    return FileAudioSource(str(FIXTURE_DIR / "speech_clean_44khz.wav"))


@pytest.fixture
def silence_source() -> FileAudioSource:
    return FileAudioSource(str(FIXTURE_DIR / "silence_1s_16khz.wav"))


class TestAudioSource:
    def test_is_abstract(self):
        with pytest.raises(TypeError):
            AudioSource()  # type: ignore[abstract]


class TestAudioSink:
    def test_is_abstract(self):
        with pytest.raises(TypeError):
            AudioSink()  # type: ignore[abstract]


class TestFileAudioSource:
    def test_reads_complete_file(self, clean_speech_source):
        all_bytes = b"".join(clean_speech_source.read(chunk_size=4096))
        assert len(all_bytes) == clean_speech_source.pcm_data_size

    def test_chunk_size_respected(self, clean_speech_source):
        for chunk in clean_speech_source.read(chunk_size=1024):
            assert len(chunk) <= 1024

    def test_reports_correct_properties_16khz(self, clean_speech_source):
        assert clean_speech_source.sample_rate == 16000
        assert clean_speech_source.channels == 1
        assert clean_speech_source.bit_depth == 16

    def test_reports_correct_properties_44khz(self, clean_speech_44khz_source):
        assert clean_speech_44khz_source.sample_rate == 44100
        assert clean_speech_44khz_source.channels == 1
        assert clean_speech_44khz_source.bit_depth == 16

    def test_reset_allows_reread(self, clean_speech_source):
        first_read = b"".join(clean_speech_source.read(chunk_size=4096))
        clean_speech_source.reset()
        second_read = b"".join(clean_speech_source.read(chunk_size=4096))
        assert first_read == second_read

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            FileAudioSource("/nonexistent/file.wav")

    def test_invalid_wav_rejected(self, tmp_path):
        bad_file = tmp_path / "not_a_wav.wav"
        bad_file.write_bytes(b"\x00\x00\x00\x00")
        with pytest.raises(InvalidWAVError):
            FileAudioSource(str(bad_file))

    def test_empty_wav_rejected(self, tmp_path):
        empty_file = tmp_path / "empty.wav"
        empty_file.write_bytes(b"")
        with pytest.raises(InvalidWAVError):
            FileAudioSource(str(empty_file))

    @pytest.mark.parametrize(
        "fixture_name,expected_rate",
        [("speech_clean_16khz.wav", 16000), ("speech_clean_44khz.wav", 44100)],
    )
    def test_sample_rate_detection(self, fixture_name, expected_rate):
        source = FileAudioSource(str(FIXTURE_DIR / fixture_name))
        assert source.sample_rate == expected_rate

    def test_context_manager(self, clean_speech_source):
        with clean_speech_source as source:
            data = b"".join(source.read(chunk_size=4096))
        assert len(data) == clean_speech_source.pcm_data_size

    def test_silence_source_returns_zeroes(self, silence_source):
        all_bytes = b"".join(silence_source.read(chunk_size=4096))
        assert len(all_bytes) == silence_source.pcm_data_size
        assert all(b == 0 for b in all_bytes)


class TestNullAudioSink:
    def test_discards_bytes(self):
        sink = NullAudioSink()
        sink.write(b"\x00" * 1024)

    def test_counts_written_bytes(self):
        sink = NullAudioSink()
        sink.write(b"\x00" * 1024)
        sink.write(b"\x00" * 512)
        assert sink.total_bytes_written == 1536

    def test_reports_throughput(self):
        sink = NullAudioSink()
        sink.write(b"\x00" * 8000)
        sink.write(b"\x00" * 8000)
        assert sink.throughput_bytes_per_sec > 0

    def test_reset_clears_counters(self):
        sink = NullAudioSink()
        sink.write(b"\x00" * 1024)
        sink.reset()
        assert sink.total_bytes_written == 0

    def test_empty_bytes_handled(self):
        sink = NullAudioSink()
        sink.write(b"")

    def test_large_chunk_handled(self):
        sink = NullAudioSink()
        large_chunk = b"\x00" * (10 * 1024 * 1024)
        sink.write(large_chunk)
        assert sink.total_bytes_written == 10 * 1024 * 1024

    def test_context_manager(self):
        with NullAudioSink() as sink:
            sink.write(b"\x00" * 512)
        assert sink.total_bytes_written == 512


class TestWAVParsing:
    def test_parse_valid_wav_header(self, clean_speech_source):
        fmt = clean_speech_source.format
        assert isinstance(fmt, AudioFormat)
        assert fmt.sample_rate == 16000
        assert fmt.channels == 1
        assert fmt.bit_depth == 16

    def test_parse_wav_header_44khz(self, clean_speech_44khz_source):
        fmt = clean_speech_44khz_source.format
        assert fmt.sample_rate == 44100
        assert fmt.channels == 1
        assert fmt.bit_depth == 16

    def test_parse_wav_from_bytes(self):
        filepath = FIXTURE_DIR / "speech_clean_16khz.wav"
        with filepath.open("rb") as f:
            raw = f.read(80)
        fmt = parse_wav_header(raw)
        assert fmt.sample_rate == 16000
        assert fmt.channels == 1
        assert fmt.bit_depth == 16

    def test_reject_truncated_header(self):
        with pytest.raises(InvalidWAVError):
            parse_wav_header(b"RIFF")

    def test_reject_no_riff_marker(self):
        data = b"\x00" * 44
        with pytest.raises(InvalidWAVError, match="RIFF"):
            parse_wav_header(data)

    def test_reject_no_wave_marker(self):
        data = b"RIFF" + struct.pack("<I", 4) + b"NOTWAVE" + b"\x00" * 32
        with pytest.raises(InvalidWAVError, match="WAVE"):
            parse_wav_header(data)

    def test_reject_unsupported_format(self):
        data = (
            b"RIFF"
            + struct.pack("<I", 100)
            + b"WAVEfmt "
            + struct.pack("<I", 16)
            + struct.pack("<H", 3)
            + struct.pack("<H", 1)
            + struct.pack("<I", 16000)
            + struct.pack("<I", 32000)
            + struct.pack("<H", 2)
            + struct.pack("<H", 16)
            + b"data"
            + struct.pack("<I", 0)
        )
        with pytest.raises(InvalidWAVError, match="PCM"):
            parse_wav_header(data)


class TestPipelineIntegration:
    def test_file_source_to_null_sink_pipeline(self, clean_speech_source):
        sink = NullAudioSink()
        for chunk in clean_speech_source.read(chunk_size=4096):
            sink.write(chunk)
        assert sink.total_bytes_written == clean_speech_source.pcm_data_size

    def test_pipeline_all_fixtures(self):
        for wav_file in sorted(FIXTURE_DIR.iterdir()):
            if wav_file.suffix != ".wav":
                continue
            source = FileAudioSource(str(wav_file))
            sink = NullAudioSink()
            for chunk in source.read(chunk_size=4096):
                sink.write(chunk)
            assert sink.total_bytes_written == source.pcm_data_size
            source_size = wav_file.stat().st_size
            assert source.pcm_data_size < source_size

    def test_pipeline_consistency(self, clean_speech_source):
        sink1 = NullAudioSink()
        for chunk in clean_speech_source.read(chunk_size=4096):
            sink1.write(chunk)
        clean_speech_source.reset()
        sink2 = NullAudioSink()
        for chunk in clean_speech_source.read(chunk_size=4096):
            sink2.write(chunk)
        assert sink1.total_bytes_written == sink2.total_bytes_written

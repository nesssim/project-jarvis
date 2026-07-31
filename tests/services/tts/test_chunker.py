from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_single_sentence():
    from tts.chunker import SentenceChunker

    chunker = SentenceChunker(min_chars=1)
    sentences = []
    async for s in chunker.add_token("Hello world."):
        sentences.append(s)
    assert sentences == ["Hello world."]


@pytest.mark.asyncio
async def test_multiple_sentences():
    from tts.chunker import SentenceChunker

    chunker = SentenceChunker(min_chars=1)
    sentences = []
    async for s in chunker.add_token("Hello. World. Test."):
        sentences.append(s)
    assert sentences == ["Hello.", "World.", "Test."]


@pytest.mark.asyncio
async def test_streaming_tokens():
    from tts.chunker import SentenceChunker

    chunker = SentenceChunker(min_chars=1)
    sentences = []
    for token in [
        "The",
        " weather",
        " is",
        " nice",
        " today.",
        " Let's",
        " go",
        " out.",
    ]:
        async for s in chunker.add_token(token):
            sentences.append(s)
    assert len(sentences) == 2
    assert "today." in sentences[0]
    assert "out." in sentences[1]


@pytest.mark.asyncio
async def test_abbreviation_handling():
    from tts.chunker import SentenceChunker

    chunker = SentenceChunker(min_chars=1)
    sentences = []
    async for s in chunker.add_token("Dr. Smith is here. He came early."):
        sentences.append(s)
    assert len(sentences) >= 2

    flushed = []
    async for s in chunker.flush():
        flushed.append(s)
    assert "He came early." in sentences or "He came early." in flushed


@pytest.mark.asyncio
async def test_flush():
    from tts.chunker import SentenceChunker

    chunker = SentenceChunker()
    async for _ in chunker.add_token("Hello world"):
        pass
    flushed = []
    async for s in chunker.flush():
        flushed.append(s)
    assert flushed == ["Hello world"]


@pytest.mark.asyncio
async def test_max_chars_force_break():
    from tts.chunker import SentenceChunker

    chunker = SentenceChunker(min_chars=50, max_chars=50)
    long_text = "A" * 60 + " B" * 10
    sentences = []
    async for s in chunker.add_token(long_text):
        sentences.append(s)
    assert len(sentences) >= 1
    assert all(len(s) <= 55 for s in sentences)


@pytest.mark.asyncio
async def test_empty_token_skipped():
    from tts.chunker import SentenceChunker

    chunker = SentenceChunker()
    sentences = []
    async for s in chunker.add_token(""):
        sentences.append(s)
    assert len(sentences) == 0


@pytest.mark.asyncio
async def test_whitespace_token_skipped():
    from tts.chunker import SentenceChunker

    chunker = SentenceChunker()
    sentences = []
    async for s in chunker.add_token("   "):
        sentences.append(s)
    assert len(sentences) == 0


@pytest.mark.asyncio
async def test_flush_empty():
    from tts.chunker import SentenceChunker

    chunker = SentenceChunker()
    flushed = []
    async for s in chunker.flush():
        flushed.append(s)
    assert len(flushed) == 0


@pytest.mark.asyncio
async def test_is_empty_property():
    from tts.chunker import SentenceChunker

    chunker = SentenceChunker()
    assert chunker.is_empty
    async for _ in chunker.add_token("hello"):
        pass
    assert not chunker.is_empty


@pytest.mark.asyncio
async def test_sentence_with_quotes():
    from tts.chunker import SentenceChunker

    chunker = SentenceChunker(min_chars=1)
    sentences = []
    async for s in chunker.add_token('He said "Hello." Then he left.'):
        sentences.append(s)
    assert len(sentences) == 2
    assert "Hello" in sentences[0]

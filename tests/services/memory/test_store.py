from __future__ import annotations

import fakeredis.aioredis
import pytest
from memory.store import MemoryStore, extract_keywords


@pytest.fixture
def store():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return MemoryStore(redis, max_turns=5)


@pytest.fixture
def null_store():
    return MemoryStore(None, max_turns=5)


class TestExtractKeywords:
    def test_removes_stop_words(self):
        result = extract_keywords("the quick brown fox jumps")
        assert "the" not in result
        assert "quick" in result
        assert "brown" in result

    def test_short_words_excluded(self):
        result = extract_keywords("a an is to be")
        assert result == []

    def test_mixed_text(self):
        result = extract_keywords("I love programming in Python")
        assert "love" in result
        assert "programming" in result
        assert "python" in result


class TestMemoryStore:
    async def test_store_and_get_recent(self, store):
        turn_id = await store.store_turn("s1", "user", "hello world")
        assert turn_id
        assert len(turn_id) == 16

        turns = await store.get_recent("s1", limit=20)
        assert len(turns) == 1
        assert turns[0]["role"] == "user"
        assert turns[0]["content"] == "hello world"
        assert turns[0]["turn_id"] == turn_id

    async def test_store_respects_max_turns(self, store):
        for i in range(10):
            await store.store_turn("s1", "user", f"turn {i}")

        turns = await store.get_recent("s1", limit=20)
        assert len(turns) == 5

    async def test_get_recent_respects_limit(self, store):
        for i in range(5):
            await store.store_turn("s1", "user", f"turn {i}")

        turns = await store.get_recent("s1", limit=2)
        assert len(turns) == 2

    async def test_recall_finds_keyword_matches(self, store):
        await store.store_turn("s1", "user", "I love Python programming")
        await store.store_turn("s1", "user", "My favorite food is pizza")

        results = await store.recall("s1", "tell me about Python", max_results=5)
        assert len(results) >= 1
        assert "Python" in results[0]["content"]

    async def test_recall_no_match(self, store):
        await store.store_turn("s1", "user", "I love Python")

        results = await store.recall("s1", "quantum physics", max_results=5)
        assert results == []

    async def test_recall_returns_scored(self, store):
        await store.store_turn("s1", "user", "Python is great for data science")
        await store.store_turn("s1", "user", "I enjoy hiking in mountains")

        results = await store.recall("s1", "Python data science", max_results=5)
        assert len(results) >= 1

    async def test_clear_session(self, store):
        await store.store_turn("s1", "user", "hello")
        await store.clear_session("s1")
        turns = await store.get_recent("s1")
        assert turns == []

    async def test_store_without_redis(self, null_store):
        turn_id = await null_store.store_turn("s1", "user", "hello")
        assert turn_id

    async def test_get_recent_without_redis(self, null_store):
        turns = await null_store.get_recent("s1")
        assert turns == []

    async def test_recall_without_redis(self, null_store):
        results = await null_store.recall("s1", "hello")
        assert results == []

    async def test_clear_without_redis(self, null_store):
        await null_store.clear_session("s1")

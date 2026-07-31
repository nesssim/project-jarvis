from __future__ import annotations

import json
import time
import uuid

import redis.asyncio as redis
from shared.logging import get_logger

logger = get_logger("memory.store")

STOP_WORDS: set[str] = {
    "a", "an", "the", "is", "are", "was", "were", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "can",
    "could", "shall", "should", "may", "might", "must", "to", "of",
    "in", "for", "on", "with", "at", "by", "from", "as", "into",
    "through", "during", "before", "after", "above", "below", "between",
    "out", "off", "over", "under", "again", "further", "then", "once",
    "here", "there", "when", "where", "why", "how", "all", "each",
    "every", "both", "few", "more", "most", "other", "some", "such",
    "no", "nor", "not", "only", "own", "same", "so", "than", "too",
    "very", "just", "about", "up", "down", "it", "its", "i", "me",
    "my", "we", "our", "you", "your", "he", "him", "his", "she",
    "her", "they", "them", "their", "what", "which", "who", "this",
    "that", "these", "those", "am", "be", "having", "doing",
}


def extract_keywords(text: str) -> list[str]:
    words = text.lower().split()
    return [w for w in words if len(w) > 2 and w not in STOP_WORDS]


def _turns_key(session_id: str) -> str:
    return f"session:{session_id}:turns"


class MemoryStore:
    def __init__(
        self,
        redis_client: redis.Redis | None,
        max_turns: int = 20,
    ) -> None:
        self.redis = redis_client
        self.max_turns = max_turns

    async def store_turn(
        self, session_id: str, role: str, content: str
    ) -> str:
        turn_id = uuid.uuid4().hex[:16]
        timestamp = time.time()
        turn = {
            "turn_id": turn_id,
            "role": role,
            "content": content,
            "timestamp": timestamp,
        }
        key = _turns_key(session_id)
        if self.redis:
            await self.redis.lpush(key, json.dumps(turn))
            await self.redis.ltrim(key, 0, self.max_turns - 1)

        logger.info(
            "stored turn", session_id=session_id, role=role, turn_id=turn_id
        )
        return turn_id

    async def get_recent(
        self, session_id: str, limit: int = 20
    ) -> list[dict]:
        if not self.redis:
            return []
        key = _turns_key(session_id)
        raw = await self.redis.lrange(key, 0, limit - 1)
        turns = []
        for item in raw:
            try:
                data = json.loads(item)
                data["timestamp"] = float(data.get("timestamp", 0))
                turns.append(data)
            except (json.JSONDecodeError, TypeError):
                continue
        return turns

    async def recall(
        self, session_id: str, query: str, max_results: int = 5
    ) -> list[dict]:
        if not self.redis:
            return []
        query_keywords = set(extract_keywords(query))
        if not query_keywords:
            return []
        key = _turns_key(session_id)
        raw = await self.redis.lrange(key, 0, 199)
        scored = []
        for item in raw:
            try:
                data = json.loads(item)
            except (json.JSONDecodeError, TypeError):
                continue
            content = data.get("content", "")
            content_keywords = set(extract_keywords(content))
            if not content_keywords:
                continue
            overlap = len(query_keywords & content_keywords)
            if overlap > 0:
                score = overlap / len(query_keywords)
                data["timestamp"] = float(data.get("timestamp", 0))
                data["score"] = score
                scored.append((score, data))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s[1] for s in scored[:max_results]]

    async def clear_session(self, session_id: str) -> None:
        if self.redis:
            key = _turns_key(session_id)
            await self.redis.delete(key)
            logger.info("cleared session", session_id=session_id)

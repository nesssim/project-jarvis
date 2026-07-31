from __future__ import annotations

from unittest.mock import patch

from tools.search import web_search


class TestWebSearch:
    @patch("duckduckgo_search.DDGS")
    async def test_search_success(self, mock_ddgs):
        mock_ddgs.return_value.__enter__.return_value.text.return_value = [
            {
                "title": "Python Programming",
                "href": "https://python.org",
                "body": "Python is a programming language",
            }
        ]
        result = await web_search("Python", max_results=3)
        assert "results" in result
        assert len(result["results"]) == 1
        assert result["results"][0]["title"] == "Python Programming"

    @patch("duckduckgo_search.DDGS")
    async def test_search_sanitizes_urls(self, mock_ddgs):
        mock_ddgs.return_value.__enter__.return_value.text.return_value = [
            {"title": "Bad", "href": "javascript:alert(1)", "body": "bad"},
            {"title": "Good", "href": "https://example.com", "body": "good"},
        ]
        result = await web_search("test", max_results=5)
        urls = [r["url"] for r in result["results"]]
        assert "javascript:alert(1)" not in urls
        assert "https://example.com" in urls

    @patch("duckduckgo_search.DDGS")
    async def test_search_respects_max_results(self, mock_ddgs):
        mock_ddgs.return_value.__enter__.return_value.text.return_value = [
            {"title": f"Result {i}", "href": f"https://example.com/{i}", "body": "test"}
            for i in range(10)
        ]
        result = await web_search("test", max_results=3)
        assert len(result["results"]) == 3

    async def test_search_import_error(self):
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "duckduckgo_search":
                raise ImportError("No module named duckduckgo_search")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", mock_import):
            result = await web_search("test")
            assert "error" in result
            assert "not installed" in result["error"]

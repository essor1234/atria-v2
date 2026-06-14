"""Tests for domain_enrich search backend."""
from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch


def _import_search():
    import atria.skills.builtin.domain_enrich.search as m
    importlib.reload(m)
    return m


class TestSerperSearch:
    def test_returns_empty_when_no_api_key(self, monkeypatch):
        monkeypatch.delenv("SERPER_API_KEY", raising=False)
        m = _import_search()
        assert m._serper_search("python", 5) == []

    def test_returns_results_when_key_set(self, monkeypatch):
        monkeypatch.setenv("SERPER_API_KEY", "fake-key")
        fake_response = {
            "organic": [
                {"title": "Python Docs", "link": "https://python.org", "snippet": "Official docs"},
            ]
        }
        from unittest.mock import AsyncMock, patch as async_patch

        mock_resp = MagicMock()
        mock_resp.json.return_value = fake_response
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        with async_patch("httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            m = _import_search()
            results = m._serper_search("python", 5)

        assert len(results) == 1
        assert results[0]["title"] == "Python Docs"
        assert results[0]["url"] == "https://python.org"
        assert results[0]["snippet"] == "Official docs"

    def test_returns_empty_on_serper_error(self, monkeypatch):
        monkeypatch.setenv("SERPER_API_KEY", "fake-key")
        with patch("httpx.AsyncClient", side_effect=Exception("network error")):
            m = _import_search()
            assert m._serper_search("python", 5) == []


class TestDdgSearch:
    def test_returns_results_from_ddgs(self):
        fake_results = [
            {"title": "DDG Result", "href": "https://example.com", "body": "A snippet"},
        ]
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.return_value = fake_results

        with patch("duckduckgo_search.DDGS", return_value=mock_ddgs):
            m = _import_search()
            results = m._ddg_search("python", 5)

        assert results == [{"title": "DDG Result", "url": "https://example.com", "snippet": "A snippet"}]

    def test_returns_empty_on_ddg_error(self):
        with patch("duckduckgo_search.DDGS", side_effect=Exception("rate limited")):
            m = _import_search()
            assert m._ddg_search("python", 5) == []


class TestSearchFallback:
    def test_uses_serper_when_key_present(self, monkeypatch):
        monkeypatch.setenv("SERPER_API_KEY", "key")
        m = _import_search()
        serper_results = [{"title": "S", "url": "https://s.com", "snippet": "s"}]
        with patch.object(m, "_serper_search", return_value=serper_results) as mock_s, \
             patch.object(m, "_ddg_search", return_value=[]) as mock_d:
            results = m.search("python", 5)
        mock_s.assert_called_once_with("python", 5)
        mock_d.assert_not_called()
        assert results == serper_results

    def test_falls_back_to_ddg_when_serper_empty(self, monkeypatch):
        monkeypatch.delenv("SERPER_API_KEY", raising=False)
        m = _import_search()
        ddg_results = [{"title": "D", "url": "https://d.com", "snippet": "d"}]
        with patch.object(m, "_serper_search", return_value=[]) as mock_s, \
             patch.object(m, "_ddg_search", return_value=ddg_results) as mock_d:
            results = m.search("python", 5)
        mock_s.assert_called_once()
        mock_d.assert_called_once_with("python", 5)
        assert results == ddg_results

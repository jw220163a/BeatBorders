import pytest
import json
from pathlib import Path
from spotify_data_refresh import (
    safe_request, get_token, get_all_categories,
    fetch_genre_tracks, fetch_top_artists_for_genre
)
import requests

# --- Fixtures & Helpers ---

class DummyResp:
    def __init__(self, status_code, json_data=None, headers=None):
        self.status_code = status_code
        self._json = json_data or {}
        self.headers = headers or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

@pytest.fixture(autouse=True)
def no_real_http(monkeypatch):
    monkeypatch.setattr(requests, "request", lambda *args, **kw: DummyResp(200, {"markets": ["US","GB"]}))

# --- Tests ---

def test_safe_request_skips_4xx(monkeypatch):
    """safe_request should return None immediately on a 404."""
    def fake_request(*a, **kw):
        return DummyResp(404)
    monkeypatch.setattr(requests, "request", fake_request)
    assert safe_request("GET", "http://example.com") is None

def test_safe_request_retries_on_429(monkeypatch):
    """safe_request should retry after 429 and eventually return a good resp."""
    calls = {"count": 0}
    def fake_request(method, url, **kw):
        calls["count"] += 1
        if calls["count"] < 2:
            return DummyResp(429, headers={"Retry-After": "0"})
        return DummyResp(200, {"ok": True})
    monkeypatch.setattr(requests, "request", fake_request)
    resp = safe_request("GET", "http://example.com")
    assert resp.json() == {"ok": True}
    assert calls["count"] == 2

def test_get_markets_formats(monkeypatch):
    """get_markets should slice to MARKETS_LIMIT."""
    from spotify_data_refresh import get_markets, MARKETS_LIMIT
    # monkeypatch safe_request to return many markets
    monkeypatch.setattr(requests, "request", lambda *a, **kw: DummyResp(200, {"markets": list("ABCDEFGHIJK")} ))
    token = "dummy"
    mk = get_markets(token)
    assert isinstance(mk, list)
    assert len(mk) == MARKETS_LIMIT

def test_fetch_genre_tracks_pages(monkeypatch):
    """fetch_genre_tracks should page through batches until exhausted."""
    # simulate two pages then empty
    pages = {
        0: [{"id": 1}, {"id":2}],
        50: [{"id":3}],
        100: []
    }
    def fake_req(method, url, timeout, headers, params):
        off = params.get("offset", 0)
        return DummyResp(200, {"tracks": {"items": pages.get(off, [])}})
    monkeypatch.setattr(requests, "request", fake_req)
    from spotify_data_refresh import fetch_genre_tracks
    tracks = fetch_genre_tracks("token", "Pop", total_tracks=200)
    assert [t["id"] for t in tracks] == [1,2,3]

def test_fetch_top_artists_for_genre(monkeypatch):
    """fetch_top_artists_for_genre should aggregate primary artist popularity."""
    # tracks: two tracks by A, one by B
    fake_tracks = [
        {"popularity": 10, "artists": [{"name":"A"}]},
        {"popularity": 20, "artists": [{"name":"A"}]},
        {"popularity": 5,  "artists": [{"name":"B"}]}
    ]
    monkeypatch.setattr(
        'spotify_data_refresh.fetch_genre_tracks',
        lambda token, genre, market=None, total_tracks=None: fake_tracks
    )
    from spotify_data_refresh import fetch_top_artists_for_genre
    top = fetch_top_artists_for_genre("token", "Pop", market="US", total_tracks=50, top_n=2)
    assert top[0][0] == "A" and top[0][1] == 30
    assert top[1][0] == "B" and top[1][1] == 5

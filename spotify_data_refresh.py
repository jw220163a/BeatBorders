#!/usr/bin/env python3
# spotify_data_refresh.py

import yaml
import json
import requests
import time
import logging
from typing import Optional, Dict, Any, List, Tuple
from collections import defaultdict
from pathlib import Path

# ───────────────────────────────────────────────────────────────
# CONFIGURATION (config.yaml)
# ───────────────────────────────────────────────────────────────
# spotify:
#   client_id: YOUR_CLIENT_ID
#   client_secret: YOUR_CLIENT_SECRET
# markets_limit: 10
# genres_limit: 200
# tracks_per_genre: 200
# top_n_genres: 10
# top_n_artists: 5

with open('config.yaml') as f:
    cfg = yaml.safe_load(f)

CLIENT_ID        = cfg['spotify']['client_id']
CLIENT_SECRET    = cfg['spotify']['client_secret']
MARKETS_LIMIT    = cfg.get('markets_limit', 10)
GENRES_LIMIT     = cfg.get('genres_limit', 200)
TRACKS_LIMIT     = cfg.get('tracks_per_genre', 200)
TOP_N_GENRES     = cfg.get('top_n_genres', 10)
TOP_N_ARTISTS    = cfg.get('top_n_artists', 5)

DATA_DIR         = Path("data")
DATA_DIR.mkdir(exist_ok=True)

OUTPUT_JSON      = DATA_DIR / 'spotify_data.json'

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

# ───────────────────────────────────────────────────────────────
# SAFE REQUEST WITH RETRIES & RATE LIMIT HANDLING
# ───────────────────────────────────────────────────────────────
def safe_request(method: str, url: str, **kwargs) -> Optional[requests.Response]:
    for attempt in range(1, 4):
        try:
            resp = requests.request(method, url, timeout=10, **kwargs)
            if resp.status_code == 429:
                retry = int(resp.headers.get('Retry-After', '1'))
                logging.warning(f"429 rate limit on {url}; retrying in {retry}s (attempt {attempt}/3)")
                time.sleep(retry)
                continue
            if 400 <= resp.status_code < 500:
                logging.warning(f"{resp.status_code} error on {url}; skipping resource.")
                return None
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            logging.warning(f"Error ({attempt}/3) fetching {url}: {e}")
            time.sleep(2 ** attempt)
    logging.error(f"Failed to fetch {url} after 3 attempts")
    return None

# ───────────────────────────────────────────────────────────────
# AUTHENTICATION
# ───────────────────────────────────────────────────────────────
def get_token() -> Optional[str]:
    resp = safe_request(
        'POST',
        'https://accounts.spotify.com/api/token',
        data={'grant_type': 'client_credentials'},
        auth=(CLIENT_ID, CLIENT_SECRET)
    )
    if not resp:
        return None
    return resp.json().get('access_token')

# ───────────────────────────────────────────────────────────────
# PAGINATED CATEGORY FETCH
# ───────────────────────────────────────────────────────────────
def get_all_categories(token: str, total: int) -> List[Tuple[str, str]]:
    categories = []
    batch = 50
    for offset in range(0, total, batch):
        resp = safe_request(
            'GET',
            'https://api.spotify.com/v1/browse/categories',
            headers={'Authorization': f'Bearer {token}'},
            params={'limit': batch, 'offset': offset}
        )
        if not resp:
            break
        items = resp.json().get('categories', {}).get('items', [])
        if not items:
            break
        categories.extend((i['name'], i['id']) for i in items)
        if len(items) < batch:
            break
        time.sleep(0.1)
    logging.info(f"Fetched {len(categories)} categories (requested {total})")
    return categories[:total]

# ───────────────────────────────────────────────────────────────
# PAGINATED TRACK FETCH
# ───────────────────────────────────────────────────────────────
def fetch_genre_tracks(
    token: str,
    genre: str,
    market: Optional[str] = None,
    total_tracks: int = TRACKS_LIMIT
) -> List[Dict[str, Any]]:
    all_tracks = []
    batch = 50
    for offset in range(0, total_tracks, batch):
        params = {
            'q': f'genre:"{genre}"',
            'type': 'track',
            'limit': batch,
            'offset': offset
        }
        if market:
            params['market'] = market
        resp = safe_request(
            'GET',
            'https://api.spotify.com/v1/search',
            headers={'Authorization': f'Bearer {token}'},
            params=params
        )
        if not resp:
            break
        items = resp.json().get('tracks', {}).get('items', [])
        if not items:
            break
        all_tracks.extend(items)
        if len(items) < batch:
            break
        time.sleep(0.1)
    logging.info(f"Fetched {len(all_tracks)} tracks for genre {genre} (market={market})")
    return all_tracks[:total_tracks]

# ───────────────────────────────────────────────────────────────
# FETCH MARKETS
# ───────────────────────────────────────────────────────────────
def get_markets(token: str) -> List[str]:
    resp = safe_request(
        'GET',
        'https://api.spotify.com/v1/markets',
        headers={'Authorization': f'Bearer {token}'},
        params={'limit': MARKETS_LIMIT}
    )
    if not resp:
        return []
    markets = resp.json().get('markets', [])
    logging.info(f"Fetched {len(markets)} markets (capped at {MARKETS_LIMIT})")
    return markets[:MARKETS_LIMIT]

# ───────────────────────────────────────────────────────────────
# FETCH TOP ARTISTS FOR A GENRE
# ───────────────────────────────────────────────────────────────
def fetch_top_artists_for_genre(
    token: str,
    genre: str,
    market: Optional[str],
    total_tracks: int = TRACKS_LIMIT,
    top_n: int = TOP_N_ARTISTS
) -> List[Tuple[str, int]]:
    tracks = fetch_genre_tracks(token, genre, market=market, total_tracks=total_tracks)
    artist_scores = defaultdict(int)
    for t in tracks:
        artists = t.get('artists', [])
        if not artists:
            continue
        primary_name = artists[0].get('name')
        popularity = t.get('popularity', 0)
        artist_scores[primary_name] += popularity
    sorted_artists = sorted(artist_scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_artists[:top_n]

# ───────────────────────────────────────────────────────────────
# MAIN LOGIC
# ───────────────────────────────────────────────────────────────
def main():
    token = get_token()
    if not token:
        logging.error("Failed to obtain access token.")
        return

    categories = get_all_categories(token, GENRES_LIMIT)
    global_scores: List[Tuple[str, int]] = []
    for name, _ in categories:
        tracks = fetch_genre_tracks(token, name)
        score = sum(t.get('popularity', 0) for t in tracks)
        global_scores.append((name, score))
        logging.info(f"Global score for {name}: {score}")
        time.sleep(0.2)

    top_genres = [g for g, _ in sorted(global_scores, key=lambda x: x[1], reverse=True)[:TOP_N_GENRES]]
    logging.info(f"Top {TOP_N_GENRES} genres globally: {top_genres}")

    markets = get_markets(token)
    if not markets:
        logging.error("No markets available.")
        return

    result: Dict[str, Any] = {
        'top_genres': top_genres,
        'country_genre_popularity': {},
        'top_artists': {}
    }

    for market in markets:
        logging.info(f"Processing market: {market}")
        country_scores: Dict[str, int] = {}
        country_artists: Dict[str, List[Tuple[str, int]]] = {}
        for genre in top_genres:
            tracks = fetch_genre_tracks(token, genre, market=market)
            score = sum(t.get('popularity', 0) for t in tracks)
            country_scores[genre] = score
            country_artists[genre] = fetch_top_artists_for_genre(token, genre, market=market)
            logging.info(f"  {genre} in {market}: score={score}, top_artists={country_artists[genre]}")
            time.sleep(0.2)

        result['country_genre_popularity'][market] = country_scores
        result['top_artists'][market] = country_artists

    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    logging.info(f"Results written to {OUTPUT_JSON}")

if __name__ == "__main__":
    main()

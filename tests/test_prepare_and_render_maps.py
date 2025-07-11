import pytest
import json
import pandas as pd
import geopandas as gpd
from pathlib import Path
from prepare_and_render_maps import world, load_spotify_data, prepare_merged_total

# --- Fixtures ---

@pytest.fixture
def sample_data(tmp_path, monkeypatch):
    # write a minimal spotify_data.json
    data = {
        "top_genres": ["G1","G2"],
        "country_genre_popularity": {"US": {"G1": 10, "G2": 20}, "GB": {"G1":5, "G2":0}},
        "top_artists": {"US": {"G1":[["A",10]]}, "GB":{"G1":[["B",5]]}}
    }
    p = tmp_path / "data"
    p.mkdir()
    fp = p / "genre_country_artist_data.json"
    fp.write_text(json.dumps(data))
    # monkeypatch INPUT_JSON
    monkeypatch.setattr('prepare_and_render_maps.INPUT_JSON', fp)
    return data

# --- Tests ---

def test_iso2_column_present():
    """GeoDataFrame must have iso_a2 column after import."""
    assert "iso_a2" in world.columns
    assert world["iso_a2"].str.len().gt(0).any()

def test_merge_total(sample_data, monkeypatch):
    """prepare_merged_total should merge country values correctly."""
    from prepare_and_render_maps import merge_total
    # build df
    df = merge_total()
    # should contain US and GB entries
    assert set(df["iso_a2"]) >= {"US","GB"}
    # values match sample
    row_us = df[df["iso_a2"]=="US"].iloc[0]
    assert row_us["value"] == 30  # 10+20
    assert "G1: 10" in row_us["tooltip"]

def test_load_spotify_data(sample_data):
    """load_spotify_data returns DataFrame with correct columns."""
    from prepare_and_render_maps import load_spotify_data
    df = load_spotify_data()
    assert {"iso_a2","value"}.issubset(df.columns)
    assert df[df["iso_a2"]=="US"]["value"].iloc[0] == 30

#!/usr/bin/env python3
# prepare_and_render_maps.py

import json
import requests
import pandas as pd
import geopandas as gpd
import plotly.express as px
import logging
from pathlib import Path

# ───────────────────────────────────────────────────────────────
# CONFIGURATION
# ───────────────────────────────────────────────────────────────
GEOJSON_URL     = "https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson"
BOUNDARIES_GEO  = Path("data") / "countries.geojson"
INPUT_JSON      = Path("data") / "spotify_data.json"
MAP_DIR         = Path("map")
GENRE_MAP_DIR   = MAP_DIR / "genre"
TOTAL_HTML      = MAP_DIR / "total_popularity.html"

# ensure data directory
(BOUNDARIES_GEO.parent).mkdir(exist_ok=True, parents=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ───────────────────────────────────────────────────────────────
# 1) Download boundaries if missing
# ───────────────────────────────────────────────────────────────
if not BOUNDARIES_GEO.exists():
    logging.info(f"Downloading boundaries from {GEOJSON_URL}")
    r = requests.get(GEOJSON_URL, timeout=10)
    r.raise_for_status()
    BOUNDARIES_GEO.write_text(r.text, encoding="utf-8")
    logging.info(f"Saved {BOUNDARIES_GEO}")

# ───────────────────────────────────────────────────────────────
# 2) Load & normalize GeoDataFrame
# ───────────────────────────────────────────────────────────────
world = gpd.read_file(str(BOUNDARIES_GEO))
for col in world.columns:
    if col.lower() in ("iso_a2", "iso2", "iso_3166_1_alpha_2", "iso3166-1-alpha-2"):
        world = world.rename(columns={col: "iso_a2"})
        break
else:
    raise RuntimeError("No ISO-2 column found in boundaries file")
world["iso_a2"] = world["iso_a2"].str.upper()

# ───────────────────────────────────────────────────────────────
# 3) Load Spotify data
# ───────────────────────────────────────────────────────────────
data       = json.loads(INPUT_JSON.read_text(encoding="utf-8"))
top_genres = data["top_genres"]
popularity = data["country_genre_popularity"]
artists    = data["top_artists"]

# ───────────────────────────────────────────────────────────────
# 4) Build DataFrame for total popularity
# ───────────────────────────────────────────────────────────────
records = []
for iso2, vals in popularity.items():
    iso2_u = iso2.upper()
    total  = sum(vals.values())
    top5   = sorted(vals.items(), key=lambda x: x[1], reverse=True)[:5]
    tip    = "<br>".join(f"{g}: {v}" for g, v in top5)
    records.append({"iso_a2": iso2_u, "value": total, "top_5_genres": tip})
df_total = pd.DataFrame(records)

# ───────────────────────────────────────────────────────────────
# 5) Merge & prepare total GeoDataFrame
# ───────────────────────────────────────────────────────────────
merged_total = world.merge(df_total, how="left", on="iso_a2")
merged_total["value"]   = merged_total["value"].fillna(0)
merged_total["top_5_genres"] = merged_total["top_5_genres"].fillna("No data")

# ───────────────────────────────────────────────────────────────
# 6) Ensure output directories
# ───────────────────────────────────────────────────────────────
MAP_DIR.mkdir(exist_ok=True)
GENRE_MAP_DIR.mkdir(exist_ok=True)

# ───────────────────────────────────────────────────────────────
# 7) Render total popularity map
# ───────────────────────────────────────────────────────────────
geojson_total = merged_total.__geo_interface__
fig = px.choropleth(
    merged_total,
    geojson=geojson_total,
    locations="iso_a2",
    color="value",
    hover_name="name",
    hover_data={"top_5_genres": True, "value": True},
    featureidkey="properties.iso_a2",
    projection="mercator",
    title="Total Spotify Popularity by Country",
)
fig.update_geos(fitbounds="locations", visible=False)
fig.write_html(str(TOTAL_HTML))
logging.info(f"Saved total popularity map to {TOTAL_HTML}")

# ───────────────────────────────────────────────────────────────
# 8) Render one map per genre
# ───────────────────────────────────────────────────────────────
for genre in top_genres:
    recs = []
    for iso2, vals in popularity.items():
        iso2_u = iso2.upper()
        val     = vals.get(genre, 0)
        top5a   = artists.get(iso2, {}).get(genre, [])[:5]
        tip     = "<br>".join(f"{a}: {s}" for a, s in top5a) or "No artists"
        recs.append({"iso_a2": iso2_u, "value": val, "top_5_artists": tip})
    df_genre = pd.DataFrame(recs)
    merged_g = world.merge(df_genre, how="left", on="iso_a2")
    merged_g["value"]   = merged_g["value"].fillna(0)
    merged_g["top_5_artists"] = merged_g["top_5_artists"].fillna("No data")
    geojson_g = merged_g.__geo_interface__
    fig = px.choropleth(
        merged_g,
        geojson=geojson_g,
        locations="iso_a2",
        color="value",
        hover_name="name",
        hover_data={"top_5_artists": True, "value": True},
        featureidkey="properties.iso_a2",
        projection="mercator",
        title=f"{genre} Popularity by Country",
    )
    fig.update_geos(fitbounds="locations", visible=False)
    outfile = GENRE_MAP_DIR / f"{genre.replace(' ', '_')}.html"
    fig.write_html(str(outfile))
    logging.info(f"Saved {genre} map to {outfile}")

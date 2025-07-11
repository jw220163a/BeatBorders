import json
import pathlib

from dash import Dash, html, dcc, Input, Output
import plotly.express as px
import geopandas as gpd
import pandas as pd

# Paths
DATA_DIR = pathlib.Path("data")
MAP_DIR = pathlib.Path("map/genre")

# Load Spotify data with explicit UTF-8
with open(DATA_DIR / "spotify_data.json", "r", encoding="utf-8") as f:
    spotify_data = json.load(f)

top_genres = spotify_data["top_genres"]
country_pop = spotify_data["country_genre_popularity"]
country_art = spotify_data["top_artists"]

# Load world GeoJSON
world = gpd.read_file(DATA_DIR / "countries.geojson")

# Normalize ISO-2 column
iso2_col = [c for c in world.columns if c.lower().startswith("iso") and "2" in c][-1]
world = world.rename(columns={iso2_col: "iso_a2"})
world["iso_a2"] = world["iso_a2"].str.upper()

# Detect a country-name column (e.g. 'NAME', 'ADMIN', etc.)
name_cols = [c for c in world.columns if c.lower() in ("name", "admin") or "name" in c.lower()]
country_name_col = name_cols[0] if name_cols else None

# --- Total-popularity map + table of global genre popularity ---

# Build DataFrame for total values + top 5 genres per country
tot_records = []
for iso2, vals in country_pop.items():
    # Total
    total_val = sum(vals.values())
    # Top 5 genres for that country
    sorted_genres = sorted(vals.items(), key=lambda kv: kv[1], reverse=True)[:5]
    top5_genres = ", ".join(f"{g} ({v})" for g, v in sorted_genres)
    tot_records.append({
        "iso_a2": iso2.upper(),
        "value": total_val,
        "top5": top5_genres
    })
df_tot = pd.DataFrame(tot_records)

merged_tot = world.merge(df_tot, how="left", on="iso_a2").fillna({"value": 0, "top5": "None"})
if country_name_col:
    merged_tot["country"] = merged_tot[country_name_col]

fig_total = px.choropleth(
    merged_tot,
    geojson=merged_tot.__geo_interface__,
    locations="iso_a2",
    color="value",
    featureidkey="properties.iso_a2",
    projection="mercator",
    hover_name="country" if country_name_col else None,
    hover_data={
        "value": True,
        "top5": True
    },
)
fig_total.update_geos(fitbounds="locations", visible=False)

# Compute global genre totals for homepage table
genre_totals = {
    genre: sum(country_pop[iso2].get(genre, 0) for iso2 in country_pop)
    for genre in top_genres
}
df_genre_tot = (
    pd.DataFrame.from_dict(genre_totals, orient="index", columns=["total"])
      .reset_index()
      .rename(columns={"index": "genre"})
      .sort_values("total", ascending=False)
)

# --- Per-genre map figures (with top 5 artists per country) ---

genre_figs = {}
# also precompute per-country top-artists text
per_country_artists = {}
for genre in top_genres:
    recs = []
    country_tooltips = {}
    for iso2, arts in country_art.items():
        # genre-specific popularity value for the country
        val = country_pop[iso2].get(genre, 0)
        recs.append({"iso_a2": iso2.upper(), "value": val})
        # top 5 artists in this country for this genre
        top5 = arts.get(genre, [])[:5]
        country_tooltips[iso2.upper()] = ", ".join(f"{a} ({s})" for a, s in top5) or "None"
    per_country_artists[genre] = country_tooltips

    df_g = pd.DataFrame(recs)
    merged_g = world.merge(df_g, how="left", on="iso_a2").fillna({"value": 0})
    # Add the country name & tooltip column
    if country_name_col:
        merged_g["country"] = merged_g[country_name_col]
    merged_g["top5"] = merged_g["iso_a2"].map(country_tooltips)

    fig = px.choropleth(
        merged_g,
        geojson=merged_g.__geo_interface__,
        locations="iso_a2",
        color="value",
        featureidkey="properties.iso_a2",
        projection="mercator",
        hover_name="country" if country_name_col else None,
        hover_data={
            "value": True,
            "top5": True
        }
    )
    fig.update_geos(fitbounds="locations", visible=False)
    genre_figs[genre] = fig

# --- Dash app setup ---

app = Dash(__name__, suppress_callback_exceptions=True)
server = app.server

app.layout = html.Div([
    dcc.Location(id="url", refresh=False),
    html.Nav([
        dcc.Link("Home", href="/"), " | ",
        dcc.Link("Genres Explorer", href="/genres")
    ], style={"padding": "10px", "fontSize": "20px"}),
    html.Div(id="page-content")
])

# Home page
home_layout = html.Div([
    html.H1("BeatBorders", style={"textAlign": "center"}),
    html.H3("Global Genre Popularity", style={"textAlign": "center"}),
    dcc.Graph(figure=fig_total),
    html.H3("Genre Popularity Rankings", style={"textAlign": "center", "marginTop": "40px"}),
    html.Table(
        [html.Thead(html.Tr([html.Th("Genre"), html.Th("Total Popularity")]))]
        + [html.Tr([html.Td(r.genre), html.Td(r.total)]) for _, r in df_genre_tot.iterrows()],
        style={"margin": "0 auto", "width": "60%", "border": "1px solid #ccc", "borderCollapse": "collapse"}
    )
])

# Genres Explorer page
genre_layout = html.Div([
    html.H1("Genres Explorer", style={"textAlign": "center"}),
    html.Div([
        html.Label("Select Genre:"),
        dcc.Dropdown(
            id="genre-dropdown",
            options=[{"label": g, "value": g} for g in top_genres],
            value=top_genres[0]
        )
    ], style={"width": "300px", "margin": "auto"}),
    dcc.Graph(id="genre-map"),
    html.H3("Overall Top Artists", style={"textAlign": "center", "marginTop": "40px"}),
    html.Div(id="artist-table-container")
])

# Page routing
@app.callback(
    Output("page-content", "children"),
    Input("url", "pathname")
)
def display_page(pathname):
    return genre_layout if pathname == "/genres" else home_layout

# Update genre map + top-artists table
@app.callback(
    Output("genre-map", "figure"),
    Output("artist-table-container", "children"),
    Input("genre-dropdown", "value")
)
def update_genre_page(selected_genre):
    fig = genre_figs[selected_genre]

    # Global top artists table (unchanged)
    agg = {}
    for arts in country_art.values():
        for artist, score in arts.get(selected_genre, []):
            agg[artist] = agg.get(artist, 0) + score

    df_art = (
        pd.DataFrame.from_dict(agg, orient="index", columns=["score"])
          .reset_index()
          .rename(columns={"index": "artist"})
          .sort_values("score", ascending=False)
          .head(10)
    )

    table = html.Table(
        [html.Thead(html.Tr([html.Th("Artist"), html.Th("Total Score")]))] +
        [html.Tr([html.Td(r.artist), html.Td(r.score)]) for _, r in df_art.iterrows()],
        style={"margin": "0 auto", "width": "50%", "border": "1px solid #ccc", "borderCollapse": "collapse"}
    )

    return fig, table

if __name__ == "__main__":
    app.run(debug=True)

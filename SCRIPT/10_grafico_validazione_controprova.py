# -*- coding: utf-8 -*-
"""
Step 10 - grafico di validazione a controprova, su 3 sezioni di esempio del
gruppo "controprova" (§7 della metodologia): Solaro (SEZ2011 152130000005),
Trezzo sull'Adda (152210000004), Calvignasco (150420000001) - scelte tra le
74 sezioni di controprova con i 3 candidati di siting pieni, per un buon
numero di colonnine reali rimosse (mappa non spoglia) e una buona distanza
dal reale (esempio "da manuale").

Stessa impostazione visiva delle mappe di 09_grafici_presentazione.py
(basemap CartoDB Positron via contextily, Web Mercator, palette INK/MUTED),
ma qui il confronto e' tra:
  - COLONNINE REALI ESISTENTI nella sezione (rosso), rimosse solo nella
    simulazione (§7.1 della metodologia) - "da spegnere" nell'esperimento
  - PUNTI RACCOMANDATI dal modello di siting (verde, script 06) - "da
    accendere" se il modello avesse dovuto scoprire da zero questa sezione

Una linea tratteggiata collega ogni punto raccomandato alla colonnina reale
piu' vicina, con la distanza in etichetta: e' la stessa metrica calcolata da
07_validazione_controprova.py, qui resa visivamente immediata invece che in
una tabella.

Le colonnine reali sono deduplicate per coordinata (round a 5 decimali): il
dataset colonnine_rimosse_controprova.csv ha una riga per CONNETTORE
(evse_id), non per stallo fisico - una colonnina con 3 prese comparirebbe
altrimenti come 3 punti sovrapposti, gonfiando visivamente il conteggio.

Input: sezioni_target_validazione.geojson, candidati_siting_provincia.csv
       (script 06), Contesto lavoro di gruppo ETL/colonnine_rimosse_controprova.csv
Output: Progetto4-Master-ProvinciaMilano/grafici di validazione/*.png
"""

from pathlib import Path

import contextily as ctx
import geopandas as gpd
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pyproj import Transformer

CARTELLA_SCRIPT = Path(__file__).resolve().parent
CARTELLA_PROGETTO = CARTELLA_SCRIPT.parent
CARTELLA_GRAFICI = CARTELLA_PROGETTO / "grafici di validazione"
CARTELLA_GRAFICI.mkdir(exist_ok=True)

CARTELLA_PROGETTO_PRINCIPALE = Path(r"C:\Users\fasanelli michele\OneDrive\Desktop\Contesto lavoro di gruppo ETL")

IN_GEOJSON = CARTELLA_SCRIPT / "sezioni_target_validazione.geojson"
IN_CANDIDATI_SITING = CARTELLA_SCRIPT / "candidati_siting_provincia.csv"
IN_COLONNINE_RIMOSSE = CARTELLA_PROGETTO_PRINCIPALE / "colonnine_rimosse_controprova.csv"

SEZIONI_ESEMPIO = [152130000005, 152210000004, 150420000001]  # Solaro, Trezzo sull'Adda, Calvignasco

INK = "#2b2b2b"
MUTED = "#5a5a5a"
ROSSO = "#c0392b"   # colonnina reale, da spegnere nella simulazione
VERDE = "#1a9850"   # punto raccomandato dal modello, da accendere
ORDINALI = ["1°", "2°", "3°", "4°", "5°"]
ZOOM_BASEMAP = 16

CRS_WGS84 = "EPSG:4326"
CRS_UTM = "EPSG:32632"
_to_utm = Transformer.from_crs(CRS_WGS84, CRS_UTM, always_xy=True).transform


def slug(comune):
    return comune.lower().replace(" ", "_").replace("'", "")


def imposta_estensione(ax, *geoseries_3857, margine_frazione=0.18):
    """Estensione della mappa sull'UNIONE di tutte le geometrie passate (poligono +
    colonnine reali + candidati), non sul solo poligono della sezione: le colonnine
    reali rimosse possono trovarsi fino a 500m dal confine (assegnate per buffer, non
    per appartenenza al poligono - vedi §7.1 della metodologia), quindi zoomare solo
    sul poligono le taglierebbe fuori dall'inquadratura."""
    bounds = np.array([g.total_bounds for g in geoseries_3857 if len(g)])
    minx, miny = bounds[:, 0].min(), bounds[:, 1].min()
    maxx, maxy = bounds[:, 2].max(), bounds[:, 3].max()
    margine = margine_frazione * max(maxx - minx, maxy - miny)
    ax.set_xlim(minx - margine, maxx + margine)
    ax.set_ylim(miny - margine, maxy + margine)


def grafico_validazione(sez, comune, poligono, candidati_scelti, colonnine_sez):
    # dedup colonnine reali per coordinata (round 5 decimali): un evse_id per connettore,
    # una colonnina fisica puo' averne piu' di uno sulla stessa coordinata
    reali = colonnine_sez[["colonnina_lat", "colonnina_lon"]].round(5).drop_duplicates()
    reali = reali.rename(columns={"colonnina_lat": "lat", "colonnina_lon": "lon"})

    rx, ry = _to_utm(reali["lon"].to_numpy(), reali["lat"].to_numpy())
    reali_utm = np.column_stack([rx, ry])

    gdf_reali = gpd.GeoDataFrame(reali, geometry=gpd.points_from_xy(reali["lon"], reali["lat"]),
                                  crs=CRS_WGS84).to_crs("EPSG:3857")
    gdf_scelti = gpd.GeoDataFrame(candidati_scelti, geometry=gpd.points_from_xy(
        candidati_scelti["lon"], candidati_scelti["lat"]), crs=CRS_WGS84).to_crs("EPSG:3857")
    poligono_3857 = gpd.GeoSeries([poligono], crs=CRS_WGS84).to_crs("EPSG:3857")

    fig, ax = plt.subplots(figsize=(10, 10), dpi=200)
    poligono_3857.plot(ax=ax, facecolor="none", edgecolor=INK, linewidth=2, zorder=2)
    imposta_estensione(ax, poligono_3857, gdf_reali, gdf_scelti)

    gdf_reali.plot(ax=ax, color=ROSSO, marker="X", markersize=170, edgecolor="white",
                    linewidth=1.1, zorder=4, label=f"colonnina reale attiva, spenta nella simulazione ({len(reali)})")

    # linea tratteggiata verso la colonnina reale piu' vicina + etichetta di distanza (stessa
    # metrica di 07_validazione_controprova.py: distanza minima punto-per-punto in UTM)
    for i, (_, riga) in enumerate(candidati_scelti.iterrows()):
        px, py = _to_utm(riga["lon"], riga["lat"])
        dist = np.hypot(reali_utm[:, 0] - px, reali_utm[:, 1] - py)
        i_vicina = int(np.argmin(dist))
        d_metri = float(dist[i_vicina])

        punto_3857 = gdf_scelti.geometry.iloc[i]
        vicina_3857 = gdf_reali.geometry.iloc[i_vicina]
        ax.plot([punto_3857.x, vicina_3857.x], [punto_3857.y, vicina_3857.y],
                color=MUTED, linestyle=(0, (4, 3)), linewidth=1.3, zorder=3)
        mx, my = (punto_3857.x + vicina_3857.x) / 2, (punto_3857.y + vicina_3857.y) / 2
        ax.annotate(f"{d_metri:.0f}m", (mx, my), fontsize=9, color=MUTED, fontweight="bold",
                    ha="center", va="center",
                    path_effects=[pe.withStroke(linewidth=3, foreground="white")], zorder=4)

    gdf_scelti.plot(ax=ax, color=VERDE, markersize=170, edgecolor="white", linewidth=1.1, zorder=5)
    for i, (_, riga) in enumerate(candidati_scelti.iterrows()):
        punto = gdf_scelti.geometry.iloc[i]
        nome = riga["nome"] if isinstance(riga["nome"], str) and riga["nome"] else riga["categoria"]
        etichetta = f"{ORDINALI[i]} raccomandato — {nome}"
        dy = 30 + (len(candidati_scelti) - 1 - i) * 40
        ax.annotate(etichetta, (punto.x, punto.y), xytext=(20, dy), textcoords="offset points",
                    ha="left", va="bottom", fontsize=9.5, color=VERDE, fontweight="bold",
                    path_effects=[pe.withStroke(linewidth=3, foreground="white")],
                    arrowprops=dict(arrowstyle="-", color=VERDE, linewidth=1.2,
                                     shrinkA=0, shrinkB=9, connectionstyle="arc3,rad=0.1"))

    ctx.add_basemap(ax, source=ctx.providers.CartoDB.Positron, zoom=ZOOM_BASEMAP)
    ax.set_axis_off()
    ax.set_title(f"Controprova: colonnine reali vs punti raccomandati — {comune}",
                 fontsize=14.5, color=INK, loc="left", pad=12, fontweight="bold")

    handles, labels = ax.get_legend_handles_labels()
    handles.append(plt.Line2D([0], [0], marker="o", linestyle="none", markerfacecolor=VERDE,
                               markeredgecolor="white", markersize=10,
                               label=f"punto raccomandato dal modello, mai visto le colonnine reali ({len(candidati_scelti)})"))
    ax.legend(handles=handles, loc="lower right", frameon=True, facecolor="white", framealpha=0.9,
              edgecolor="none", fontsize=8.5)

    mediana_d = np.median([np.hypot(reali_utm[:, 0] - px, reali_utm[:, 1] - py).min()
                            for px, py in zip(*_to_utm(candidati_scelti["lon"].to_numpy(),
                                                        candidati_scelti["lat"].to_numpy()))])
    fig.text(0.01, 0.014,
              f"SEZ2011 {sez} · {len(reali)} colonnine reali (stalli fisici, connettori multipli "
              f"deduplicati) · distanza mediana candidato→colonnina più vicina: {mediana_d:.0f}m",
              fontsize=9.5, color=INK, path_effects=[pe.withStroke(linewidth=3, foreground="white")])

    fig.subplots_adjust(left=0.01, right=0.99, top=0.95, bottom=0.055)
    out = CARTELLA_GRAFICI / f"controprova_{slug(comune)}_{sez}.png"
    plt.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Salvato: {out.name} (distanza mediana {mediana_d:.0f}m)")


def main():
    sezioni = gpd.read_file(IN_GEOJSON)
    sezioni["SEZ2011"] = sezioni["SEZ2011"].astype(int)
    candidati = pd.read_csv(IN_CANDIDATI_SITING)
    colonnine = pd.read_csv(IN_COLONNINE_RIMOSSE)

    for sez in SEZIONI_ESEMPIO:
        riga_sez = sezioni[sezioni["SEZ2011"] == sez]
        if riga_sez.empty:
            print(f"SEZ2011={sez} non trovata nel geojson target, salto.")
            continue
        riga_sez = riga_sez.iloc[0]
        comune = riga_sez["COMUNE"]
        poligono = riga_sez.geometry
        print(f"=== SEZ2011 {sez} ({comune}) ===")

        candidati_scelti = candidati[candidati["SEZ2011"] == sez].sort_values("rank")
        if candidati_scelti.empty:
            print(f"  Nessun candidato di siting per SEZ2011={sez}, salto.")
            continue
        colonnine_sez = colonnine[colonnine["SEZ2011"] == sez]
        if colonnine_sez.empty:
            print(f"  Nessuna colonnina reale rimossa per SEZ2011={sez}, salto.")
            continue

        grafico_validazione(sez, comune, poligono, candidati_scelti, colonnine_sez)

    print(f"\nTutti i grafici sono in: {CARTELLA_GRAFICI}")


if __name__ == "__main__":
    main()

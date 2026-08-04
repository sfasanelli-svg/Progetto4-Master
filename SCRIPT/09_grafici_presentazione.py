# -*- coding: utf-8 -*-
"""
Step 9 - grafici per la presentazione, su 2 sezioni di esempio scelte tra le
818 critiche (stessa logica di scelta usata per Mediglia in
Progetto3-Master-VectorTiles/SCRIPT/08_grafico_gap_score_colonnine.py: una
sezione che richiede 3 colonnine per scendere sotto soglia, con dati di
traffico/POI/siting abbastanza "corposi" da fare un buon esempio):

  - SEZ2011 152010000007, San Vittore Olona
  - SEZ2011 151390000005, Mediglia (stessa sezione gia' presentata in
    Progetto3, qui con dati reali di traffico/POI della fase provinciale)

Per ciascuna sezione genera 4 grafici, riusando le stesse funzioni della
pipeline (import diretto di 05_quante_colonnine.py e
06_candidati_siting_provincia.py, nessuna logica duplicata):

  1. traffico_<comune>_<SEZ2011>.png - mappa dei segmenti monitorati
     (colorati per congestione massima, solo quelli robusti >=5 letture) +
     pattern orario del segmento piu' critico. Stesso stile di
     Progetto3-Master-VectorTiles/SCRIPT/03_grafico_esempio_sezione.py.
  2. poi_<comune>_<SEZ2011>.png - mappa dei POI candidati (livello 1-3)
     dentro il confine della sezione, colorati per livello di confidenza.
  3. siting_<comune>_<SEZ2011>.png - mappa dei punti di siting raccomandati
     (rank 1-3, script 06) sovrapposti a POI disponibili e segmenti di
     traffico robusti, per mostrare visivamente il "perche'" della scelta.
  4. gap_score_<comune>_<SEZ2011>.png - impatto di 0-3 nuove colonnine sul
     GAP score, stessa metodologia e stile di
     Progetto3-Master-VectorTiles/SCRIPT/08_grafico_gap_score_colonnine.py.

Output: Progetto4-Master-ProvinciaMilano/grafici/*.png
"""

import importlib.util
from pathlib import Path
from zoneinfo import ZoneInfo

import geopandas as gpd
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize

CARTELLA_SCRIPT = Path(__file__).resolve().parent
CARTELLA_PROGETTO = CARTELLA_SCRIPT.parent
CARTELLA_GRAFICI = CARTELLA_PROGETTO / "grafici"
CARTELLA_GRAFICI.mkdir(exist_ok=True)

CARTELLA_PROGETTO_PRINCIPALE = Path(r"C:\Users\fasanelli michele\OneDrive\Desktop\Contesto lavoro di gruppo ETL")
IN_GAP_SCORE_NAZIONALE = CARTELLA_PROGETTO_PRINCIPALE / "sezioni_gap_score_DEFINITIVO.parquet"

IN_GEOJSON = CARTELLA_SCRIPT / "sezioni_target_validazione.geojson"
IN_CANDIDATI_SITING = CARTELLA_SCRIPT / "candidati_siting_provincia.csv"
IN_QUANTE_COLONNINE = CARTELLA_SCRIPT / "quante_colonnine_critiche.csv"

SEZIONI_ESEMPIO = [152010000007, 151390000005]  # San Vittore Olona, Mediglia
MIN_LETTURE = 5
SCENARI_NUOVE_COLONNINE = [0, 1, 2, 3]
FUSO_ITALIA = ZoneInfo("Europe/Rome")

INK = "#2b2b2b"
MUTED = "#5a5a5a"
GRID = "#e6e6e6"
ACCENT = "#c0392b"
COLORI_LIVELLO = {1: "#1a9850", 2: "#fc8d59", 3: "#4575b4"}
NOMI_LIVELLO = {1: "1 - parcheggio quasi certo", 2: "2 - parcheggio dedicato certo", 3: "3 - parcheggio plausibile"}
COLORI_RANK = {1: "#c0392b", 2: "#e67e22", 3: "#8e44ad"}


def _importa(nome_file):
    spec = importlib.util.spec_from_file_location(nome_file.stem, nome_file)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


m05 = _importa(CARTELLA_SCRIPT / "05_quante_colonnine.py")
m06 = _importa(CARTELLA_SCRIPT / "06_candidati_siting_provincia.py")


def slug(comune):
    return comune.lower().replace(" ", "_").replace("'", "")


def carica_traffico():
    file_giorni = sorted(CARTELLA_SCRIPT.glob("traffico_provincia_*.parquet"))
    return pd.concat([pd.read_parquet(f) for f in file_giorni], ignore_index=True)


def imposta_stile_assi(ax):
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(labelsize=7.5, colors=MUTED)
    ax.set_aspect("equal")


# ---------------------------------------------------------------- 1. traffico
def grafico_traffico(sez, comune, poligono, traffico_sez):
    d = traffico_sez.copy()
    d["lat_r"] = d["lat"].round(5)
    d["lon_r"] = d["lon"].round(5)

    per_segmento = d.groupby(["lat_r", "lon_r", "road_type"]).agg(
        congestione_max=("congestione", "max"), n_letture=("congestione", "size")
    ).reset_index()
    punti = gpd.GeoDataFrame(per_segmento, geometry=gpd.points_from_xy(
        per_segmento["lon_r"], per_segmento["lat_r"]), crs="EPSG:4326")
    per_segmento = per_segmento[punti.within(poligono).to_numpy()].copy()

    robusti = per_segmento[per_segmento["n_letture"] >= MIN_LETTURE].sort_values(
        ["congestione_max", "n_letture"], ascending=[False, False])
    non_robusti = per_segmento[per_segmento["n_letture"] < MIN_LETTURE]
    if robusti.empty:
        print(f"  [traffico] SEZ2011={sez}: nessun segmento robusto, salto il grafico.")
        return
    top = robusti.iloc[0]

    letture_top = d[(d["lat_r"] == top["lat_r"]) & (d["lon_r"] == top["lon_r"])].copy()
    letture_top["ts"] = pd.to_datetime(letture_top["timestamp_utc"], utc=True)
    letture_top["ora_locale"] = letture_top["ts"].dt.tz_convert(FUSO_ITALIA).dt.hour
    pattern_orario = letture_top.groupby("ora_locale")["congestione"].agg(["mean", "max", "count"]).reset_index()

    cmap = plt.get_cmap("YlOrRd")
    norm = Normalize(vmin=0, vmax=robusti["congestione_max"].max())

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 5.6), dpi=130, gridspec_kw={"wspace": 0.32})

    poligono_wgs = gpd.GeoSeries([poligono], crs="EPSG:4326")
    poligono_wgs.plot(ax=ax1, facecolor="none", edgecolor=MUTED, linewidth=1.1, zorder=1)
    ax1.scatter(non_robusti["lon_r"], non_robusti["lat_r"], s=14, facecolor="#d9d9d9",
                edgecolor="none", zorder=2, label=f"< {MIN_LETTURE} letture (dato insufficiente)")
    sizes = 18 + robusti["n_letture"].clip(upper=60)
    ax1.scatter(robusti["lon_r"], robusti["lat_r"], c=robusti["congestione_max"],
                cmap=cmap, norm=norm, s=sizes, edgecolor="white", linewidth=0.4, zorder=3)
    ax1.scatter([top["lon_r"]], [top["lat_r"]], s=220, facecolor="none", edgecolor=ACCENT, linewidth=2, zorder=4)
    ax1.annotate(f"segmento piu' critico\n(robusto, {int(top['n_letture'])} letture)",
                 (top["lon_r"], top["lat_r"]), xytext=(-14, -30), textcoords="offset points",
                 ha="right", fontsize=8.5, color=ACCENT, path_effects=[pe.withStroke(linewidth=2.5, foreground="white")])
    ax1.set_title(f"Congestione massima per segmento — {comune}", fontsize=11, color=INK, loc="left", pad=10)
    ax1.set_xlabel("longitudine", fontsize=8.5, color=MUTED)
    ax1.set_ylabel("latitudine", fontsize=8.5, color=MUTED)
    imposta_stile_assi(ax1)
    ax1.legend(loc="lower left", frameon=True, facecolor="white", edgecolor="none",
               framealpha=0.85, fontsize=7.5, handletextpad=0.3)
    cbar = fig.colorbar(ScalarMappable(norm=norm, cmap=cmap), ax=ax1, fraction=0.045, pad=0.03)
    cbar.set_label(f"congestione massima\n(min. {MIN_LETTURE} letture)", fontsize=7.5, color=MUTED)
    cbar.ax.tick_params(labelsize=7.5, color=MUTED)

    ax2.bar(pattern_orario["ora_locale"], pattern_orario["max"], color="#fde3cf", width=0.7,
            label="massimo nell'ora", zorder=1)
    ax2.plot(pattern_orario["ora_locale"], pattern_orario["mean"], color=ACCENT, marker="o",
             markersize=5, linewidth=2, label="media nell'ora", zorder=2)
    for _, r in pattern_orario.iterrows():
        ax2.annotate(str(int(r["count"])), (r["ora_locale"], r["max"]), xytext=(0, 4),
                     textcoords="offset points", ha="center", fontsize=6.5, color=MUTED)
    ax2.set_title(f"Pattern orario del segmento più critico ({top['road_type']})",
                  fontsize=11, color=INK, loc="left", pad=10)
    ax2.set_xlabel("ora del giorno (locale)", fontsize=8.5, color=MUTED)
    ax2.set_ylabel("congestione", fontsize=8.5, color=MUTED)
    ax2.set_xticks(range(5, 23, 2))
    ax2.set_ylim(0, 1)
    ax2.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    ax2.legend(frameon=False, fontsize=8, loc="upper right")
    for spine in ["top", "right"]:
        ax2.spines[spine].set_visible(False)
    for spine in ["left", "bottom"]:
        ax2.spines[spine].set_color(GRID)

    ultima_data = pd.to_datetime(d["timestamp_utc"]).max().strftime("%d/%m %H:%M UTC")
    fig.suptitle(f"Raccolta 03-04/08/2026, dati fino al {ultima_data}", fontsize=9.5, color=MUTED, x=0.01, ha="left", y=1.04)
    fig.text(0.01, 0.005,
              f"SEZ2011 {sez} ({comune}) · {len(per_segmento)} segmenti monitorati totali "
              f"({len(robusti)} robusti, colorati · {len(non_robusti)} non robusti, in grigio) · "
              "dimensione del punto = n. letture.", fontsize=7.3, color=MUTED)

    plt.tight_layout(rect=(0, 0.05, 1, 0.96))
    out = CARTELLA_GRAFICI / f"traffico_{slug(comune)}_{sez}.png"
    plt.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Salvato: {out.name}")


# --------------------------------------------------------------------- 2. POI
def grafico_poi(sez, comune, poligono):
    candidati = m06.poi_candidati_sezione(sez, poligono)
    if not candidati:
        print(f"  [poi] SEZ2011={sez}: nessun POI candidato, salto il grafico.")
        return

    fig, ax = plt.subplots(figsize=(7, 7), dpi=150)
    poligono_wgs = gpd.GeoSeries([poligono], crs="EPSG:4326")
    poligono_wgs.plot(ax=ax, facecolor="#f7f7f7", edgecolor=MUTED, linewidth=1.2, zorder=1)

    for livello in (1, 2, 3):
        sotto = [c for c in candidati if c["livello"] == livello]
        if not sotto:
            continue
        ax.scatter([c["lon"] for c in sotto], [c["lat"] for c in sotto],
                   s=90, color=COLORI_LIVELLO[livello], edgecolor="white", linewidth=0.8,
                   zorder=3, label=f"{NOMI_LIVELLO[livello]} ({len(sotto)})")

    ax.set_title(f"POI candidati per il siting — {comune}", fontsize=13, color=INK,
                 loc="left", pad=12, fontweight="bold")
    ax.set_xlabel("longitudine", fontsize=8.5, color=MUTED)
    ax.set_ylabel("latitudine", fontsize=8.5, color=MUTED)
    imposta_stile_assi(ax)
    ax.legend(loc="best", frameon=True, facecolor="white", edgecolor="none", framealpha=0.9, fontsize=8.5)

    categorie = pd.Series([c["categoria"] for c in candidati]).value_counts()
    dettaglio_cat = ", ".join(f"{c} ({n})" for c, n in categorie.items())
    fig.text(0.01, 0.01, f"SEZ2011 {sez} ({comune}) · {len(candidati)} POI totali candidati (livello 1-3) · "
                          f"per categoria: {dettaglio_cat}", fontsize=7.3, color=MUTED, wrap=True)

    plt.tight_layout(rect=(0, 0.05, 1, 1))
    out = CARTELLA_GRAFICI / f"poi_{slug(comune)}_{sez}.png"
    plt.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Salvato: {out.name}")


# ----------------------------------------------------------------- 3. siting
def grafico_siting(sez, comune, poligono, traffico_sez, candidati_scelti):
    robusti = m06.segmenti_robusti_sezione(traffico_sez, poligono)
    tutti_poi = m06.poi_candidati_sezione(sez, poligono)

    fig, ax = plt.subplots(figsize=(7.5, 7.5), dpi=150)
    poligono_wgs = gpd.GeoSeries([poligono], crs="EPSG:4326")
    poligono_wgs.plot(ax=ax, facecolor="#f7f7f7", edgecolor=MUTED, linewidth=1.2, zorder=1)

    if not robusti.empty:
        sizes = 25 + robusti["n_letture"].clip(upper=60)
        ax.scatter(robusti["lon_r"], robusti["lat_r"], c=robusti["congestione_max"],
                   cmap=plt.get_cmap("YlOrRd"), vmin=0, vmax=1, s=sizes, edgecolor="white",
                   linewidth=0.4, zorder=2, label="segmento traffico robusto")

    ax.scatter([c["lon"] for c in tutti_poi], [c["lat"] for c in tutti_poi],
               s=40, facecolor="none", edgecolor="#9b9b9b", linewidth=1.1, zorder=3,
               label=f"POI disponibile ({len(tutti_poi)})")

    # offset del testo differenziato per rank (non solo (10,10) fisso): quando due
    # candidati sono vicini e con punteggio simile (es. San Vittore Olona, #1 e #2),
    # un offset uguale per tutti fa sovrapporre le etichette - qui si allontanano in
    # direzioni diverse, con una sottile linea guida (arrowprops) a ricollegarle al
    # punto esatto senza ambiguita'.
    OFFSET_PER_RANK = {1: (18, 26), 2: (18, -30), 3: (-95, -10)}
    for _, riga in candidati_scelti.sort_values("rank").iterrows():
        rank = int(riga["rank"])
        colore = COLORI_RANK[rank]
        ax.scatter([riga["lon"]], [riga["lat"]], s=320, marker="*", color=colore,
                   edgecolor="white", linewidth=1, zorder=5)
        ax.annotate(f"#{rank} {riga['categoria']}\npunteggio {riga['punteggio_traffico']:.2f}",
                    (riga["lon"], riga["lat"]), xytext=OFFSET_PER_RANK.get(rank, (18, 10)),
                    textcoords="offset points", ha="left", fontsize=8, color=colore, fontweight="bold",
                    path_effects=[pe.withStroke(linewidth=2.5, foreground="white")], zorder=6,
                    arrowprops=dict(arrowstyle="-", color=colore, linewidth=0.9, alpha=0.7,
                                     shrinkA=0, shrinkB=8))

    ax.set_title(f"Punti di siting raccomandati — {comune}", fontsize=13, color=INK,
                 loc="left", pad=12, fontweight="bold")
    ax.set_xlabel("longitudine", fontsize=8.5, color=MUTED)
    ax.set_ylabel("latitudine", fontsize=8.5, color=MUTED)
    imposta_stile_assi(ax)
    ax.legend(loc="best", frameon=True, facecolor="white", edgecolor="none", framealpha=0.9, fontsize=8)

    fig.text(0.01, 0.01,
              f"SEZ2011 {sez} ({comune}) · le stelle numerate #1-#3 sono i candidati scelti "
              "(rank per punteggio di traffico, diversificati a >=100m tra loro).",
              fontsize=7.3, color=MUTED)

    plt.tight_layout(rect=(0, 0.05, 1, 1))
    out = CARTELLA_GRAFICI / f"siting_{slug(comune)}_{sez}.png"
    plt.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Salvato: {out.name}")


# --------------------------------------------------------------- 4. gap score
def grafico_gap_score(sez, comune, gap_nazionale, parametri, soglia_critica):
    riga = gap_nazionale[gap_nazionale["SEZ2011"] == sez]
    if riga.empty:
        print(f"  [gap_score] SEZ2011={sez}: non trovata nel dataset nazionale, salto il grafico.")
        return
    sezione = riga.iloc[0]

    offerta_norm_iniziale = m05.offerta_norm_da_conteggio(
        [sezione["offerta_colonnine_500m"]], [sezione["distanza_colonnina_piu_vicina_m"]], parametri)[0]
    domanda_norm = sezione["gap_score"] + offerta_norm_iniziale

    risultati = []
    for n_nuove in SCENARI_NUOVE_COLONNINE:
        colonnine_simulate = sezione["offerta_colonnine_500m"] + n_nuove
        offerta_norm_sim = m05.offerta_norm_da_conteggio(
            [colonnine_simulate], [sezione["distanza_colonnina_piu_vicina_m"]], parametri)[0]
        risultati.append({"nuove_colonnine": n_nuove, "gap_score": domanda_norm - offerta_norm_sim})
    scenari = pd.DataFrame(risultati)

    scarto = abs(scenari.loc[scenari["nuove_colonnine"] == 0, "gap_score"].iloc[0] - sezione["gap_score"])
    assert scarto < 1e-6, f"Scenario 0 non riproduce il gap_score originale (scarto {scarto:.2e})"

    cmap = plt.get_cmap("YlOrRd")
    vmax = float(np.ceil(scenari["gap_score"].max() * 20) / 20)
    norm = Normalize(vmin=0, vmax=vmax)

    fig, ax = plt.subplots(figsize=(7.5, 5.5), dpi=200)
    colori = [cmap(norm(v)) for v in scenari["gap_score"]]
    barre = ax.bar(scenari["nuove_colonnine"], scenari["gap_score"], color=colori,
                    edgecolor="white", linewidth=1.2, width=0.62, zorder=3)
    for barra, valore in zip(barre, scenari["gap_score"]):
        ax.annotate(f"{valore:.3f}", (barra.get_x() + barra.get_width() / 2, valore),
                    xytext=(0, 6), textcoords="offset points", ha="center", va="bottom",
                    fontsize=10, color=INK, fontweight="bold")

    ax.axhline(soglia_critica, color=ACCENT, linestyle=(0, (5, 3)), linewidth=1.6, zorder=2)
    ax.text(0.015, soglia_critica, f"soglia critica (gomito) = {soglia_critica:.3f}",
            transform=ax.get_yaxis_transform(), ha="left", va="bottom", fontsize=9.5,
            color=ACCENT, fontweight="bold", path_effects=[pe.withStroke(linewidth=2.5, foreground="white")])

    idx_sotto_soglia = next((i for i, v in enumerate(scenari["gap_score"]) if v < soglia_critica), None)
    ax.set_xticks(scenari["nuove_colonnine"])
    ax.set_xlabel("nuove colonnine installate entro 500 m", fontsize=10, color=MUTED)
    ax.set_ylabel("GAP score", fontsize=10, color=MUTED)
    ax.set_ylim(0, max(vmax, soglia_critica) * 1.12)
    ax.set_title(f"Impatto di nuove colonnine sul GAP score — {comune}",
                 fontsize=14, color=INK, loc="left", pad=14, fontweight="bold")
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    for spine in ["left", "bottom"]:
        ax.spines[spine].set_color(GRID)
    ax.tick_params(colors=MUTED)

    n_sotto = None
    if idx_sotto_soglia is not None:
        n_sotto = int(scenari["nuove_colonnine"].iloc[idx_sotto_soglia])
        for etichetta in ax.get_xticklabels():
            if etichetta.get_text() == str(n_sotto):
                etichetta.set_color(ACCENT)
                etichetta.set_fontweight("bold")

    nota_soglia = (f" · scende sotto soglia con {n_sotto} nuove colonnin{'a' if n_sotto == 1 else 'e'}"
                   if n_sotto is not None else "")
    fig.text(0.01, 0.01,
              f"SEZ2011 {sez} ({comune}) · simulazione: solo la componente di offerta cambia, "
              f"la domanda resta invariata{nota_soglia}", fontsize=7.6, color=MUTED)

    plt.tight_layout(rect=(0, 0.035, 1, 1))
    out = CARTELLA_GRAFICI / f"gap_score_{slug(comune)}_{sez}.png"
    plt.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Salvato: {out.name}")
    print(scenari.round(4).to_string(index=False))


def main():
    sezioni = gpd.read_file(IN_GEOJSON)
    sezioni["SEZ2011"] = sezioni["SEZ2011"].astype(int)
    candidati = pd.read_csv(IN_CANDIDATI_SITING)
    traffico = carica_traffico()

    gap_nazionale = pd.read_parquet(
        IN_GAP_SCORE_NAZIONALE,
        columns=["SEZ2011", "gap_score", "offerta_colonnine_500m", "distanza_colonnina_piu_vicina_m"])
    eleggibili = gap_nazionale.dropna(subset=["gap_score"]).copy()
    critiche_ord = eleggibili[eleggibili["gap_score"] > 0].sort_values("gap_score", ascending=False)
    soglia_critica = float(critiche_ord["gap_score"].to_numpy()[m05.trova_gomito(critiche_ord["gap_score"].to_numpy())])
    parametri = m05.costruisci_parametri_offerta(eleggibili)
    print(f"Soglia critica (gomito nazionale): {soglia_critica:.4f}\n")

    for sez in SEZIONI_ESEMPIO:
        riga_sez = sezioni[sezioni["SEZ2011"] == sez]
        if riga_sez.empty:
            print(f"SEZ2011={sez} non trovata nel geojson target, salto.")
            continue
        riga_sez = riga_sez.iloc[0]
        comune = riga_sez["COMUNE"]
        poligono = riga_sez.geometry
        print(f"=== SEZ2011 {sez} ({comune}) ===")

        traffico_sez = traffico[traffico["SEZ2011"] == sez]
        grafico_traffico(sez, comune, poligono, traffico_sez)
        grafico_poi(sez, comune, poligono)

        scelti = candidati[candidati["SEZ2011"] == sez]
        if scelti.empty:
            print(f"  [siting] SEZ2011={sez}: nessun candidato in {IN_CANDIDATI_SITING.name}, salto il grafico.")
        else:
            grafico_siting(sez, comune, poligono, traffico_sez, scelti)

        grafico_gap_score(sez, comune, gap_nazionale, parametri, soglia_critica)
        print()

    print(f"Tutti i grafici sono in: {CARTELLA_GRAFICI}")


if __name__ == "__main__":
    main()

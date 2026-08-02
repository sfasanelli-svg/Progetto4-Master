"""
Step 2 del progetto di validazione modello di siting (vector tiles sulle
sezioni target della provincia di Milano: 818 critiche + 150 di
controprova, 968 totali, 803 tile) - script principale.

Stessa logica di Progetto3-Master-VectorTiles/SCRIPT/02_monitoraggio_traffico_tile.py
(stesso endpoint, stesso fix del bug y_coord_down, stessa congestione = 1 -
traffic_level), con tre differenze dovute alla scala (968 sezioni, 803
tile invece di 50/63):

1. CADENZA ADATTIVA (5 minuti in punta, 30 fuori punta), non fissa. Un
   ciclo completo con 803 tile richiede ~4 minuti di sole pause
   (PAUSA_TRA_RICHIESTE_S x 803), quindi 5 minuti nelle fasce di punta e'
   fattibile. Cadenza fissa a 5 minuti su tutte le 48h costerebbe 803 x 12
   x 48 = 462.528 chiamate (231% della quota mensile TomTom, 200.000):
   non sostenibile. Cadenza fissa oraria rientrerebbe ampiamente in quota
   ma sacrifica la risoluzione proprio dove serve di piu'. La cadenza
   adattiva (vedi FASCE_PUNTA_ORA_LOCALE, INTERVALLO_PUNTA_MINUTI/
   INTERVALLO_FUORI_PUNTA_MINUTI piu' sotto) costa ~173.448 chiamate su
   48h (87% quota, su una chiave DEDICATA a questo progetto, non
   condivisa con Progetto3-Master-VectorTiles): 5 minuti nelle 2 fasce di
   punta (mattino/sera, ora locale italiana), dove il pattern da
   catturare e' concentrato, 30 minuti nel resto della giornata. Il
   trigger esterno (cron-job.org) resta invariato a "ogni 5 minuti" - e'
   gia' la granularita' piu' fine di cui c'e' bisogno; e' la logica DENTRO
   lo script (funzione intervallo_corrente) a decidere, in base all'ora
   locale italiana corrente, se lasciar passare il tentativo (punta) o
   scartarlo fino al prossimo bucket da 30 minuti (fuori punta).

2. OUTPUT IN PARQUET, PARTIZIONATO PER GIORNO, non un unico CSV in
   append. Motivo: un CSV che cresce all'infinito e viene ri-committato a
   ogni esecuzione, alla scala di questo progetto, arriverebbe a decine o
   centinaia di MB entro pochi giorni - GitHub rifiuta push di file
   singoli sopra i 100MB, l'automazione si romperebbe a meta' campagna. Un
   file Parquet compresso per giorno (traffico_provincia_AAAA-MM-GG.parquet)
   resta piccolo e non cresce mai oltre un giorno di dati: a ogni
   esecuzione il file del giorno corrente viene letto, concatenato con le
   nuove righe e riscritto (Parquet non supporta l'append nativo come il
   CSV, ma riscrivere un giorno di dati resta un'operazione da pochi
   secondi anche a cadenza fitta).

3. ASSEGNAZIONE FALLBACK VETTORIALE (sjoin_nearest), non un ciclo Python
   sezione per sezione. Con 50 sezioni un ciclo "per ogni sezione senza
   segmenti, calcola la distanza da OGNI segmento scaricato" era
   trascurabile; con centinaia di migliaia di segmenti per esecuzione (803
   tile) e cadenza fino a 5 minuti, sarebbe troppo lento - si usa l'indice
   spaziale di geopandas invece del ciclo esplicito.

API key TomTom:
  1. variabile d'ambiente TOMTOM_API_KEY (GitHub Actions, via secret);
  2. altrimenti SCRIPT/tomtom_key.txt (uso locale).

Output: traffico_provincia_AAAA-MM-GG.parquet (uno per giorno). Colonne:
        timestamp_utc, SEZ2011, COMUNE, gap_score, road_type,
        traffic_road_coverage, congestione, lat, lon, assegnazione,
        distanza_m
"""

import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import geopandas as gpd
import mapbox_vector_tile
import pandas as pd
import requests
from shapely.geometry import LineString, MultiLineString

CARTELLA_SCRIPT = Path(__file__).resolve().parent
IN_GEOJSON = CARTELLA_SCRIPT / "sezioni_target_validazione.geojson"
IN_TILE = CARTELLA_SCRIPT / "tile_necessari.csv"
KEY_PATH = CARTELLA_SCRIPT / "tomtom_key.txt"

TOMTOM_TILE_URL = "https://api.tomtom.com/traffic/map/4/tile/flow/relative/{zoom}/{x}/{y}.pbf"
PAUSA_TRA_RICHIESTE_S = 0.3
BUFFER_SEZIONE_METRI = 50

# Cadenza ADATTIVA, non fissa: 803 tile a 5 minuti fissi per 48h costerebbero
# 462.528 chiamate (231% della quota mensile TomTom, 200.000) - non
# sostenibile. A cadenza oraria fissa si rientra ampiamente in quota, ma si
# perde la risoluzione fine sui picchi di punta, che e' dove il pattern
# conta davvero (la soglia di robustezza del progetto, >= 5 letture, serve
# proprio a distinguere un pattern vero da un episodio isolato: per farlo
# bene servono PIU' picchi osservati, non un solo picco campionato fitto).
# Compromesso: 5 minuti nelle 2 fasce di punta (mattino/sera, dove la
# congestione da catturare e' concentrata), 30 minuti nel resto della
# giornata. Per 48h: 173.448 chiamate (87% quota) - due mattine e due sere
# indipendenti a piena risoluzione, invece di una sola finestra fissa.
#
# Le fasce sono in ora locale italiana (Europe/Rome, gestisce CEST/CET da
# solo via zoneinfo): il traffico di punta segue gli orari di lavoro locali,
# non l'orario UTC.
FASCE_PUNTA_ORA_LOCALE = [(7, 10), (17, 20)]  # [ora_inizio, ora_fine) coppie
INTERVALLO_PUNTA_MINUTI = 5
INTERVALLO_FUORI_PUNTA_MINUTI = 30
FUSO_ITALIA = ZoneInfo("Europe/Rome")

CRS_WGS84 = "EPSG:4326"
CRS_UTM = "EPSG:32632"


def intervallo_corrente(adesso_utc):
    """Cadenza da applicare ADESSO: 5 minuti se l'ora locale italiana cade
    in una fascia di punta, 30 minuti altrimenti."""
    ora_locale = adesso_utc.astimezone(FUSO_ITALIA).hour
    in_punta = any(inizio <= ora_locale < fine for inizio, fine in FASCE_PUNTA_ORA_LOCALE)
    return INTERVALLO_PUNTA_MINUTI if in_punta else INTERVALLO_FUORI_PUNTA_MINUTI


def leggi_api_key():
    da_env = os.environ.get("TOMTOM_API_KEY")
    if da_env:
        return da_env.strip()
    return KEY_PATH.read_text(encoding="utf-8").strip()


def out_path_giorno(data):
    return CARTELLA_SCRIPT / f"traffico_provincia_{data.isoformat()}.parquet"


def bucket(dt, intervallo_minuti):
    """Chiave dell'intervallo temporale (data, ora, minuto arrotondato
    per difetto a multipli di intervallo_minuti) a cui appartiene dt."""
    minuto_arrotondato = (dt.minute // intervallo_minuti) * intervallo_minuti
    return (dt.date(), dt.hour, minuto_arrotondato)


def intervallo_gia_coperto(adesso, intervallo_minuti):
    """True se l'ultima riga del parquet del giorno corrente cade nello
    stesso intervallo temporale (bucket) di 'adesso'."""
    path = out_path_giorno(adesso.date())
    if not path.exists():
        return False
    df = pd.read_parquet(path, columns=["timestamp_utc"])
    if df.empty:
        return False
    ultimo_dt = datetime.fromisoformat(df["timestamp_utc"].iloc[-1])
    return bucket(ultimo_dt, intervallo_minuti) == bucket(adesso, intervallo_minuti)


def tile_px_to_lonlat(x_tile, y_tile, zoom, px, py, extent):
    n = 2 ** zoom
    lon = (x_tile + px / extent) / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * (y_tile + py / extent) / n)))
    lat = math.degrees(lat_rad)
    return lon, lat


def scarica_e_decodifica_tile(x, y, zoom, api_key, tentativi=3):
    for tentativo in range(1, tentativi + 1):
        r = requests.get(TOMTOM_TILE_URL.format(zoom=zoom, x=x, y=y),
                          params={"key": api_key}, timeout=20)
        if r.status_code == 200:
            if not r.content:
                return []
            # y_coord_down=True: stesso fix di Progetto3-Master-VectorTiles, vedi
            # quel repository per la spiegazione completa del bug (doppio flip
            # verticale corretto usando questa opzione di mapbox_vector_tile.decode).
            return mapbox_vector_tile.decode(r.content, default_options={"y_coord_down": True})
        if r.status_code == 429:
            print("    rate limit (429), attendo 10s e riprovo...")
            time.sleep(10)
            continue
        print(f"    tentativo {tentativo}: HTTP {r.status_code} - {r.text[:200]}")
        time.sleep(3)
    return None


def estrai_segmenti_lonlat(tile_decodificato, x, y, zoom):
    """Ritorna una lista di dict {geometry (shapely, lon/lat), road_type,
    traffic_road_coverage, congestione} per tutti i segmenti del tile."""
    segmenti = []
    if not tile_decodificato:
        return segmenti

    for layer in tile_decodificato.values():
        extent = layer.get("extent", 4096)
        for feat in layer["features"]:
            props = feat["properties"]
            traffic_level = props.get("traffic_level")
            if traffic_level is None:
                continue
            geom = feat["geometry"]

            def converti_linea(coords_px):
                return [tile_px_to_lonlat(x, y, zoom, px, py, extent) for px, py in coords_px]

            if geom["type"] == "LineString":
                linea = LineString(converti_linea(geom["coordinates"]))
            elif geom["type"] == "MultiLineString":
                parti = [LineString(converti_linea(c)) for c in geom["coordinates"] if len(c) >= 2]
                if not parti:
                    continue
                linea = MultiLineString(parti) if len(parti) > 1 else parti[0]
            else:
                continue

            segmenti.append({
                "geometry": linea,
                "road_type": props.get("road_type"),
                "traffic_road_coverage": props.get("traffic_road_coverage"),
                "congestione": 1 - traffic_level,
            })
    return segmenti


def main(forza=False):
    ora_corrente = datetime.now(timezone.utc)
    intervallo_minuti = intervallo_corrente(ora_corrente)

    if not forza and intervallo_gia_coperto(ora_corrente, intervallo_minuti):
        print(f"Intervallo di {intervallo_minuti} minuti (cadenza "
              f"{'di punta' if intervallo_minuti == INTERVALLO_PUNTA_MINUTI else 'fuori punta'}) "
              f"gia' coperto da un'esecuzione precedente "
              f"({ora_corrente.isoformat(timespec='minutes')}): nessuna chiamata TomTom, esco.")
        return

    api_key = leggi_api_key()
    timestamp_utc = ora_corrente.isoformat(timespec="seconds")

    sezioni = gpd.read_file(IN_GEOJSON)[["SEZ2011", "COMUNE", "gap_score", "geometry"]]
    sezioni_utm = sezioni.to_crs(CRS_UTM)
    sezioni_buff_utm = sezioni_utm.copy()
    sezioni_buff_utm["geometry"] = sezioni_utm.geometry.buffer(BUFFER_SEZIONE_METRI)
    sezioni_buff = gpd.GeoDataFrame(
        sezioni_buff_utm[["SEZ2011", "COMUNE", "gap_score"]],
        geometry=sezioni_buff_utm.geometry, crs=CRS_UTM
    ).to_crs(CRS_WGS84)

    tile_df = pd.read_csv(IN_TILE)
    print(f"Tile da scaricare: {len(tile_df)}")

    tutti_i_segmenti = []
    for i, row in tile_df.iterrows():
        x, y, zoom = int(row["tile_x"]), int(row["tile_y"]), int(row["zoom"])
        tile_decodificato = scarica_e_decodifica_tile(x, y, zoom, api_key)
        segmenti = estrai_segmenti_lonlat(tile_decodificato, x, y, zoom)
        tutti_i_segmenti.extend(segmenti)
        if (i + 1) % 200 == 0 or i + 1 == len(tile_df):
            print(f"  [{i+1}/{len(tile_df)}] tile scaricati, {len(tutti_i_segmenti)} segmenti finora")
        time.sleep(PAUSA_TRA_RICHIESTE_S)

    if not tutti_i_segmenti:
        print("Nessun segmento scaricato, esco senza scrivere output.")
        return

    gdf_segmenti = gpd.GeoDataFrame(tutti_i_segmenti, geometry="geometry", crs=CRS_WGS84)
    gdf_segmenti_utm = gdf_segmenti.to_crs(CRS_UTM)

    # assegna ciascun segmento alla/e sezione/i con cui interseca (poligono bufferizzato)
    join = gpd.sjoin(gdf_segmenti, sezioni_buff, how="inner", predicate="intersects")

    righe = []
    for _, r in join.iterrows():
        centro = r["geometry"].centroid
        righe.append({
            "timestamp_utc": timestamp_utc,
            "SEZ2011": r["SEZ2011"],
            "COMUNE": r["COMUNE"],
            "gap_score": r["gap_score"],
            "road_type": r["road_type"],
            "traffic_road_coverage": r["traffic_road_coverage"],
            "congestione": r["congestione"],
            "lat": centro.y,
            "lon": centro.x,
            "assegnazione": "dentro_sezione",
            "distanza_m": 0.0,
        })

    # fallback "distance-aware" per le sezioni senza alcun segmento dentro il
    # buffer: assegna il segmento scaricato piu' vicino, segnalando la
    # distanza. sjoin_nearest usa l'indice spaziale di geopandas (molto piu'
    # veloce, alla scala della provincia, del ciclo "distanza da ogni
    # segmento" usato nella versione a 50 sezioni - vedi punto 3 in cima).
    sezioni_coperte = set(r["SEZ2011"] for r in righe)
    sezioni_mancanti_utm = sezioni_utm[~sezioni_utm["SEZ2011"].isin(sezioni_coperte)].copy()

    if len(sezioni_mancanti_utm):
        gdf_segmenti_utm_idx = gdf_segmenti_utm.reset_index(drop=True)
        vicini = gpd.sjoin_nearest(
            sezioni_mancanti_utm[["SEZ2011", "COMUNE", "gap_score", "geometry"]],
            gdf_segmenti_utm_idx[["road_type", "traffic_road_coverage", "congestione", "geometry"]],
            distance_col="distanza_m",
        )
        for _, r in vicini.iterrows():
            seg_geom_wgs84 = gdf_segmenti.geometry.iloc[r["index_right"]]
            centro = seg_geom_wgs84.centroid
            righe.append({
                "timestamp_utc": timestamp_utc,
                "SEZ2011": r["SEZ2011"],
                "COMUNE": r["COMUNE"],
                "gap_score": r["gap_score"],
                "road_type": r["road_type"],
                "traffic_road_coverage": r["traffic_road_coverage"],
                "congestione": r["congestione"],
                "lat": centro.y,
                "lon": centro.x,
                "assegnazione": "piu_vicino_esterno",
                "distanza_m": round(r["distanza_m"], 1),
            })

    out = pd.DataFrame(righe)
    n_sezioni_coperte = out["SEZ2011"].nunique() if len(out) else 0
    print(f"\nSegmenti totali scaricati: {len(gdf_segmenti)}")
    print(f"Righe assegnate a una sezione: {len(out)}")
    print(f"Sezioni con almeno un segmento: {n_sezioni_coperte} / {len(sezioni)}")

    path_giorno = out_path_giorno(ora_corrente.date())
    if path_giorno.exists():
        out_precedente = pd.read_parquet(path_giorno)
        out = pd.concat([out_precedente, out], ignore_index=True)
    out.to_parquet(path_giorno, compression="gzip", index=False)
    print(f"Salvate {len(out)} righe totali (oggi) in: {path_giorno}")


if __name__ == "__main__":
    import sys
    forza = "--forza" in sys.argv
    main(forza=forza)

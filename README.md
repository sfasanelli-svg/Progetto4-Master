# Progetto EV Charge Desert — Validazione modello di siting, provincia di Milano

Estensione di [Progetto3-Master-VectorTiles](https://github.com/sfasanelli-svg/Progetto3-Master)
(stessa pipeline: TomTom Traffic Flow Vector Tile, stesso fix del bug di
posizionamento, stessa logica di assegnazione a confine esatto) a un set
mirato di sezioni della provincia di Milano, per validare il modello di
siting (quante colonnine + dove) su scala provinciale.

**Non copre l'intera provincia** (13.557 sezioni): analizzando lo scope
reale del modello è emerso che serve solo su due gruppi di sezioni — le
critiche (per l'uso reale del modello) e un campione di controprova (per
validarlo confrontando le raccomandazioni con le colonnine reali già
esistenti). Vedi `Contesto lavoro di gruppo ETL/SCRIPT/seleziona_sezioni_target_validazione.py`
per come sono state scelte.

## Le 968 sezioni target

- **818 sezioni critiche** (gap_score sopra la soglia del gomito nazionale,
  0,4287): qui il modello va applicato per davvero — quante colonnine
  servono e dove installarle.
- **150 sezioni di controprova**, campionate stratificando per comune (124
  comuni distinti, nessuno domina il campione) dal pool di sezioni oggi
  *servite* che tornerebbero critiche se le loro colonnine locali (entro
  500m) venissero rimosse. Per queste si applica il modello **fingendo che
  le colonnine non esistano** (il modello non le vede comunque: nessuna
  categoria POI corrisponde a una colonnina) e si confronta il punto
  raccomandato con la posizione reale della colonnina rimossa
  (`Contesto lavoro di gruppo ETL/colonnine_rimosse_controprova.csv`,
  1.829 colonnine reali, da `pun_colonnine_pulito.csv`).

## Differenze rispetto a Progetto3

| | Progetto3 (50 sezioni) | Questo progetto (968 sezioni target) |
|---|---|---|
| Sezioni | 50 | 968 (818 critiche + 150 controprova) |
| Tile zoom 15 | 63 | 803 |
| Cadenza | ogni 5 minuti, fissa | **adattiva**: 5 min in punta (7-10, 17-20 ora locale), 30 min fuori punta |
| Finestra oraria | 7-22 ora italiana | **stessa finestra**, 7-22 ora italiana (le notti sono escluse: la congestione massima, la metrica usata ovunque, non è quasi mai raggiunta di notte) |
| Durata raccolta | continuativa, indefinita | campagna a tempo, **48 ore, si ferma da sola** |
| Output | un unico CSV in append | un file Parquet per giorno |
| Chiave TomTom | condivisa con Progetto1/2 | **dedicata a questo progetto** |

Il conteggio tile non scala con il numero di sezioni ma con l'AREA
coperta: le 50 sezioni di Progetto3 sono isole sparse (63 tile), le 968 di
qui sono più diffuse ma non contigue come l'intera provincia (803 tile,
calcolati sulle geometrie reali, non stimati — molto meno dei 2.404 che
servirebbero per tutta la provincia).

## Perché cadenza adattiva, non fissa

Cadenza fissa a 5 minuti su 48h costerebbe 803 × 12 × 48 = 462.528 chiamate
(231% della quota mensile TomTom, 200.000): non sostenibile. Cadenza fissa
oraria rientrerebbe ampiamente in quota ma sacrifica risoluzione proprio
nelle ore di punta, dove il pattern da individuare è concentrato — e la
soglia di robustezza del progetto (≥5 letture per fidarsi di un segmento)
esiste apposta per distinguere un pattern vero da un episodio isolato: per
farlo bene servono **più picchi osservati indipendentemente**, non uno
solo campionato fitto. La cadenza adattiva (5 min in punta, 30 min fuori
punta) dà due mattine e due sere indipendenti a piena risoluzione su 48h,
proiezione totale ~193.500 chiamate (96,8% della quota, finestra 7-22 ora
italiana come Progetto3 — le notti sono escluse deliberatamente, non solo
per risparmiare quota).

**Nota sull'incidente del 03/08**: il fuori-punta era stato infittito a 15
minuti la sera prima (per più robustezza), ma un bug — un run troppo
lento (~10 minuti, corretto poi con download parallelo + sessione HTTP
condivisa, da 586s a 28-48s) — ha causato molte esecuzioni fallite durante
la prima punta serale della campagna. Le esecuzioni fallite consumano
comunque la quota TomTom (fallisce solo il commit successivo, non la
chiamata): a 15 minuti la proiezione avrebbe superato il 100% della quota
verso la fine della campagna. Riportato a 30 minuti per restare in quota
con margine — vedi il docstring di `02_monitoraggio_traffico_tile.py`
(punti 5-6) per il dettaglio completo.

## Perché Parquet partizionato per giorno, non un CSV che cresce

Un CSV unico in append, alla scala di questo progetto, potrebbe arrivare a
decine/centinaia di MB in 48 ore — GitHub rifiuta push di file singoli
sopra 100MB, l'automazione si romperebbe a metà campagna. Un file Parquet
compresso per giorno (`traffico_provincia_AAAA-MM-GG.parquet`) resta
piccolo e non cresce mai oltre un giorno di dati.

## Finestra di campagna: lunedì-martedì, si ferma da sola

`CAMPAGNA_INIZIO`/`CAMPAGNA_FINE` in `02_monitoraggio_traffico_tile.py`
fissano la raccolta a **lunedì 03/08/2026 00:00 → mercoledì 05/08/2026
00:00 ora italiana** (48 ore, lunedì+martedì — dati più verosimili di un
giorno feriale "tipico" invece di un giorno scelto a caso, che potrebbe
cadere di weekend). Fuori da questa finestra lo script esce subito senza
fare alcuna chiamata TomTom: si può quindi attivare il trigger esterno
anche con giorni di anticipo (nessun costo di quota finché non arriva
lunedì) e lasciarlo attivo — la raccolta si interrompe da sola dopo 48
ore, senza bisogno di disattivare nulla manualmente (a differenza di
Progetto3).

## Setup da completare (fuori dal codice)

1. Creare il repository GitHub vuoto
2. Aggiungere il secret `TOMTOM_API_KEY` nelle impostazioni del repository
   (Settings → Secrets and variables → Actions) — **usare una chiave TomTom
   dedicata a questo progetto**, non quella di Progetto1/2/3, per non
   condividere la quota mensile con la raccolta ancora in corso sulle 50
   sezioni
3. Creare un job su [cron-job.org](https://cron-job.org) che chiami l'API
   GitHub (`workflow_dispatch`) su questo repository ogni 5 minuti, **7-22
   ora italiana** (stessa finestra di Progetto3, `*/5 7-22 * * *`: le notti
   sono escluse deliberatamente, la congestione massima non le raggiunge
   quasi mai) — può restare attivo fin da subito, vedi sopra

## Contenuto

- `SCRIPT/00_esporta_sezioni_provincia.py` — script originale (prima
  versione, intera provincia): esporta le 13.557 sezioni dal dataset
  nazionale in GeoJSON WGS84. Non più l'input effettivo di 01/02 (vedi
  sotto), lasciato come riferimento. **Attenzione**: la geometria del
  parquet sorgente è in EPSG:32632 (UTM, metri), non lon/lat — va
  riproiettata esplicitamente (verificato: un primo tentativo senza
  conversione è andato in loop per decine di minuti).
- `SCRIPT/sezioni_target_validazione.geojson` — le 968 sezioni target
  effettive, prodotte da
  `Contesto lavoro di gruppo ETL/SCRIPT/seleziona_sezioni_target_validazione.py`
  (non in questo repository), copiate qui come input di 01/02.
- `SCRIPT/01_calcola_tile_necessari.py` — stessa logica di Progetto3, input
  il GeoJSON delle 968 sezioni target
- `SCRIPT/02_monitoraggio_traffico_tile.py` — script principale, vedi sopra
  per le differenze rispetto a Progetto3 (cadenza adattiva, Parquet per
  giorno, fallback vettoriale)

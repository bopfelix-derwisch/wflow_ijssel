"""WL-BRO-1 — BRO grondwater connector (GLD + GMW via PDOK).

Data Hub-adapter voor gemeten grondwaterstanden uit het BRO Grondwaterstanden-
dossier (GLD). Twee verantwoordelijkheden:

  - discover_wells(bbox, ...): PDOK OGC API Features (gm_gld) → putten met
    locatie, GMW-koppeling, observatie-aantal, datumbereik. Eén bbox-call lost
    discovery + de GMW↔GLD-koppeling op. Gecached (dag-TTL).
  - fetch_series(broId, ...): broservices seriesAsCsv → daggemiddelde reeks
    grondwaterstand (m). Server-side (CORS-restrictie omzeild). Gecached (15 min).

Zie docs/WL-BRO-0_feasibility.md voor de feasibility en de endpoint-keuze.
"""
from __future__ import annotations

import csv
import io
import logging
import math
import time

import requests

logger = logging.getLogger(__name__)

PDOK_GLD_ITEMS = (
    "https://api.pdok.nl/bzk/bro-gminsamenhang-karakteristieken/ogc/v1"
    "/collections/gm_gld/items"
)
SERIES_CSV = "https://publiek.broservices.nl/gm/gld/v1/seriesAsCsv/{bro_id}"

# Veluwe-oostflank ↔ IJssel (Westervoort–Deventer–Kampen). minLon,minLat,maxLon,maxLat (CRS84).
DEFAULT_BBOX = (5.95, 52.25, 6.10, 52.55)

# Gecureerde fallback-putten (WL-BRO-0), gespreid S→N langs de Veluwe-oostflank.
CURATED_WELLS = [
    {"bro_id": "GLD000000044984", "lat": 52.2507, "lon": 5.9987},
    {"bro_id": "GLD000000008262", "lat": 52.3797, "lon": 6.0570},
    {"bro_id": "GLD000000048526", "lat": 52.4806, "lon": 6.0949},
    {"bro_id": "GLD000000044584", "lat": 52.5002, "lon": 6.0167},
    {"bro_id": "GLD000000053138", "lat": 52.5444, "lon": 6.0242},
]

_cache: dict = {}
_DISCOVERY_TTL = 86_400   # 1 dag
_SERIES_TTL    = 900      # 15 min — zelfde als de andere bronnen


def discover_wells(
    bbox: tuple = DEFAULT_BBOX,
    covers_start: str = "2018-06-01",
    covers_end: str = "2018-08-31",
    limit: int = 1000,
) -> list[dict]:
    """PDOK gm_gld bbox-query → putten met data die [covers_start, covers_end] dekken.

    Retourneert dicts: {bro_id, lat, lon, n_obs, first, last}. Lege lijst bij fout.
    """
    key = f"disc_{bbox}_{covers_start}_{covers_end}"
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _DISCOVERY_TTL:
        return hit[1]
    try:
        r = requests.get(
            PDOK_GLD_ITEMS,
            params={"bbox": ",".join(map(str, bbox)), "limit": limit, "f": "json"},
            timeout=30,
        )
        r.raise_for_status()
        feats = r.json().get("features", [])
        wells = []
        for f in feats:
            p = f.get("properties", {})
            g = (f.get("geometry") or {}).get("coordinates") or [None, None]
            fd, ld = p.get("research_first_date"), p.get("research_last_date")
            nobs = p.get("number_of_observations") or 0
            if not (fd and ld) or nobs <= 0:
                continue
            if fd <= covers_start and ld >= covers_end:
                wells.append({
                    "bro_id": p.get("bro_id"),
                    "lat": round(g[1], 4) if g[1] is not None else None,
                    "lon": round(g[0], 4) if g[0] is not None else None,
                    "n_obs": nobs, "first": fd[:10], "last": ld[:10],
                })
        wells.sort(key=lambda w: (w["lat"] is None, w["lat"]))
        logger.info("BRO discovery: %d wells cover %s–%s in bbox", len(wells), covers_start, covers_end)
        _cache[key] = (time.monotonic(), wells)
        return wells
    except Exception as e:
        logger.warning("BRO discovery faalde: %s", e)
        return []


def _pick_value(row: list[str]) -> float | None:
    """Eerste gevulde waardekolom: Voorlopig(1) / Beoordeeld(3) / Controle(5) / Onbekend(7)."""
    for i in (3, 1, 5, 7):  # beoordeeld heeft voorrang op voorlopig
        if i < len(row) and row[i].strip():
            try:
                return float(row[i])
            except ValueError:
                continue
    return None


def fetch_series(bro_id: str, start: str | None = None, end: str | None = None) -> list[dict]:
    """seriesAsCsv → daggemiddelde grondwaterstand (m). [{date, value}], geclipt op [start, end]."""
    key = f"ser_{bro_id}"
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _SERIES_TTL:
        rows = hit[1]
    else:
        try:
            r = requests.get(SERIES_CSV.format(bro_id=bro_id),
                             params={"asISO8601": "true"}, timeout=90)
            r.raise_for_status()
            reader = csv.reader(io.StringIO(r.text))
            next(reader, None)  # header
            daily: dict[str, list[float]] = {}
            for row in reader:
                if not row or not row[0]:
                    continue
                val = _pick_value(row)
                if val is None:
                    continue
                day = row[0][:10]
                daily.setdefault(day, []).append(val)
            rows = [{"date": d, "value": round(sum(v) / len(v), 4)}
                    for d, v in sorted(daily.items())]
            _cache[key] = (time.monotonic(), rows)
        except Exception as e:
            logger.warning("BRO series %s faalde: %s", bro_id, e)
            if hit:
                rows = hit[1]
            else:
                return []
    if start or end:
        lo, hi = start or "0000", end or "9999"
        rows = [e for e in rows if lo <= e["date"] <= hi]
    return rows


# ── WL-GQL-2: ruimtelijke query (putten nabij een station) ───────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def wells_near(lat: float, lon: float, radius_km: float = 15.0, limit: int = 5,
               covers_start: str = "2018-06-01", covers_end: str = "2018-08-31") -> list[dict]:
    """BRO GLD-putten binnen radius_km van (lat, lon) met data die [covers_start,
    covers_end] dekken. Bbox-query → haversine-afstand → dedup per locatie →
    gesorteerd op afstand. Elke put: {bro_id, lat, lon, n_obs, first, last, distance_km}."""
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.01))
    bbox = (round(lon - dlon, 4), round(lat - dlat, 4),
            round(lon + dlon, 4), round(lat + dlat, 4))
    seen: dict = {}
    for w in discover_wells(bbox=bbox, covers_start=covers_start, covers_end=covers_end):
        if w["lat"] is None or w["lon"] is None:
            continue
        d = _haversine_km(lat, lon, w["lat"], w["lon"])
        if d > radius_km:
            continue
        loc = (w["lat"], w["lon"])
        cand = {**w, "distance_km": round(d, 1)}
        if loc not in seen or cand["n_obs"] > seen[loc]["n_obs"]:
            seen[loc] = cand
    return sorted(seen.values(), key=lambda w: w["distance_km"])[:limit]

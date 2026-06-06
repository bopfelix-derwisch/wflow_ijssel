from __future__ import annotations
import json
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent

PERIOD_DIRS: dict[str, Path] = {
    "1995": ROOT / "data" / "output",
    "2018": ROOT / "data" / "output_2018",
    "2021": ROOT / "data" / "output_2021_real",
}

_STATION_FILES: dict[str, str] = {
    "KAMPEN":      "kampen",
    "WESTERVOORT": "westervoort",
}

_cache: dict = {}
_CACHE_TTL = 900


def get_wflow_timeseries(location_id: str, parameter_id: str, period: str) -> list[dict]:
    """Leest wflow JSON output en geeft PI REST event-dicts terug."""
    if period not in PERIOD_DIRS or location_id not in _STATION_FILES:
        return []
    if parameter_id != "Q.sim":
        return []

    station = _STATION_FILES[location_id]
    path = PERIOD_DIRS[period] / f"timeseries_{station}.json"
    if not path.exists():
        return []

    data = json.loads(path.read_text())
    values = data.get("q", [])

    events = []
    for date, val in zip(data.get("dates", []), values):
        if val is not None and float(val) > 0.001:
            events.append({
                "date": str(date),
                "time": "12:00:00",
                "value": f"{float(val):.3f}",
                "flag": "0",
            })
    return events


def get_waterinfo_timeseries(location_id: str, parameter_id: str, days: int = 30) -> list[dict]:
    """Haalt live data op via rws_waterinfo en geeft PI REST event-dicts terug."""
    cache_key = f"wi_{location_id}_{parameter_id}_{days}"
    if cache_key in _cache:
        ts, events = _cache[cache_key]
        if time.monotonic() - ts < _CACHE_TTL:
            return events

    try:
        import rws_waterinfo as rw
        import pandas as pd
        from datetime import date, timedelta

        end   = date.today()
        start = end - timedelta(days=days)

        if parameter_id == "H.meting" and location_id == "KAMPEN":
            locatie, grootheid, eenheid, scale = "kampen.ijssel", "WATHTE", "cm", 0.01
        elif parameter_id == "Q.meting" and location_id == "WESTERVOORT":
            locatie, grootheid, eenheid, scale = "westervoort", "Q", "m3/s", 1.0
        else:
            return []

        df = rw.get_data(
            [{"locatie_code": locatie, "compartiment_code": "OW",
              "grootheid_code": grootheid, "eenheid_code": eenheid,
              "start_date": str(start), "end_date": str(end),
              "proces_type": "meting"}],
            return_df=True, parallel=False,
        )
        if df is None or len(df) == 0:
            return []

        df2 = df[["Tijdstip", "Meetwaarde.Waarde_Numeriek"]].copy()
        df2["Tijdstip"] = pd.to_datetime(df2["Tijdstip"].str[:19])
        df2 = df2.set_index("Tijdstip").sort_index().dropna()

        events = []
        for ts_idx, row in df2.iterrows():
            val = float(row["Meetwaarde.Waarde_Numeriek"]) * scale
            events.append({
                "date": ts_idx.strftime("%Y-%m-%d"),
                "time": ts_idx.strftime("%H:%M:%S"),
                "value": f"{val:.3f}",
                "flag": "0",
            })

        _cache[cache_key] = (time.monotonic(), events)
        return events
    except Exception:
        return []

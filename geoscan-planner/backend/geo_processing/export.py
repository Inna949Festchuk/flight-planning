"""Экспорт полётного задания в GeoJSON (FeatureCollection).

Структура описана в README: маршруты (LineString), галсы (LineString),
площадки ВПП (Point), сводка (Feature «metadata»).
"""

from __future__ import annotations

TYPE_LABELS = {
    "visible": "Видимый диапазон",
    "thermal": "Тепловизионный",
    "multispectral": "Мультиспектральный",
}


def build_flight_task_geojson(result: dict, vpps: list[dict]) -> dict:
    """result — полный результат run_planning (status=success)."""
    features = []
    for mode, variant in result["variants"].items():
        for s in variant["sorties"]:
            features.append({
                "type": "Feature",
                "properties": {
                    "kind": "route",
                    "variant": mode,
                    "uav": s["uav"],
                    "model": s["model"],
                    "zone": s["zone"],
                    "survey_type": s["survey_type"],
                    "payload": s["payload"],
                    "vpp": s["vpp"],
                    "start_min": s["start_min"],
                    "duration_min": s["duration_min"],
                    "altitude_m": s["altitude_m"],
                    "speed_kmh": s["speed_kmh"],
                    "battery_used_pct": s["battery_used_pct"],
                    "distance_km": s["distance_km"],
                },
                "geometry": {"type": "LineString", "coordinates": s["route"]},
            })

    for v in vpps:
        features.append({
            "type": "Feature",
            "properties": {"kind": "vpp", "name": v["name"]},
            "geometry": {"type": "Point", "coordinates": [v["lon"], v["lat"]]},
        })

    summary = {
        "criterion": result.get("criterion", "all_variants"),
        "variants": {
            m: v["metrics"] for m, v in result["variants"].items()
        },
        "common": result.get("common", {}),
    }
    features.append({
        "type": "Feature",
        "properties": {"kind": "metadata", "summary": summary},
        "geometry": {"type": "Point", "coordinates": [0, 0]},
    })

    return {"type": "FeatureCollection", "features": features}

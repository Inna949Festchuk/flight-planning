"""Локальный тест ядра планирования (внутри контейнера backend).

Запуск:
  docker compose -f docker-compose.dev.yml exec backend \
    python /app/geo_processing/_local_test.py
Не требует БД — только pandas/pulp/shapely.
"""
import json
import sys

sys.path.insert(0, "/app")

import pulp  # noqa: E402

from geo_processing import planning  # noqa: E402

DATA = "/app/geo_processing/data"


def fc_zones(path):
    fc = json.load(open(path, encoding="utf-8"))
    out = []
    for f in fc["features"]:
        geom = f["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        out.append(
            {
                "name": f["properties"]["name"],
                "survey_type": f["properties"].get("survey_type"),
                "rings": polys,
            }
        )
    return out


def fc_vpps(path):
    fc = json.load(open(path, encoding="utf-8"))
    return [
        {
            "name": f["properties"]["name"],
            "lon": f["geometry"]["coordinates"][0],
            "lat": f["geometry"]["coordinates"][1],
        }
        for f in fc["features"]
    ]


zones = fc_zones(f"{DATA}/polygons.geojson")
survey = [z for z in zones if z["survey_type"]]
forbidden = [z for z in zones if not z["survey_type"]]
vpps = fc_vpps(f"{DATA}/vpp.geojson")

print(f"pulp {pulp.__version__} | зон {len(survey)} | запретов {len(forbidden)} | ВПП {len(vpps)}")

result = planning.run_planning(
    survey_zones=survey, forbidden_zones=forbidden, vpps=vpps,
    gsd=1.0, wind_kmh=5.0, side_overlap=0.5, front_overlap=0.6,
)
print("\nСТАТУС:", result["status"])
if result["status"] != "success":
    for r in result["reasons"]:
        print("  причина:", r)
    sys.exit(1)

ok = True
for mode, v in result["variants"].items():
    m = v["metrics"]
    print(f"\n=== {v['title']} ({mode}): makespan {m['total_time_min']} мин, налёт {m['total_flight_min']}, БВС {m['uavs_used']}, вылетов {m['sorties']}")
    for s in v["sorties"]:
        print(f"  {s['uav']:16s} -> {s['zone']:9s} [{s['survey_type']:13s}] {s['payload']:16s} старт {s['start_min']:>5} мин, dur {s['duration_min']:>5} мин, H {s['altitude_m']:>5} м, бат {s['battery_used_pct']}%")
        if s["battery_used_pct"] > 80.5:
            print("    !! Батарея > 80%")
            ok = False
        if s["survey_type"] == "thermal" and not s["model"].startswith("Геоскан 801"):
            print("    !! thermal на не-Геоскан 801")
            ok = False

print("\n" + ("ВСЕ ПРОВЕРКИ OK" if ok else "ЕСТЬ ОШИБКИ"))
sys.exit(0 if ok else 1)

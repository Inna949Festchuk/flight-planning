"""Оркестратор планирования: входные данные → валидация → галсы → MILP → план.

Вход — обычные словари (без привязки к модели БД), чтобы ядро работало и в
Celery-задаче, и в чат-агенте, и в тестах.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings

from . import gals, milp
from .checks import build_forbidden_prepared, resolve_conflicts, route_crosses_forbidden

TYPE_LABELS = {
    "visible": "Видимый диапазон",
    "thermal": "Тепловизионный",
    "multispectral": "Мультиспектральный",
}


def _load_data_file(name: str):
    path = Path(settings.DATA_DIR) / name
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_fleet(active_ids: list[int] | None = None) -> list[dict]:
    fleet = _load_data_file("fleet.json")
    if active_ids:
        fleet = [u for u in fleet if u["id"] in active_ids]
    return fleet


def get_payloads() -> list[gals.PayloadSpec]:
    raw = _load_data_file("ttx_payload.json")
    return [gals.PayloadSpec(**p) for p in raw]


def run_planning(
    survey_zones: list[dict],
    forbidden_zones: list[dict],
    vpps: list[dict],
    gsd: float,
    wind_kmh: float,
    side_overlap: float,
    front_overlap: float,
    survey_types: list[str] | None = None,
    active_uav_ids: list[int] | None = None,
) -> dict:
    """Выполняет расчёт. Возвращает dict со статусом success/infeasible."""
    P = settings.PLANNING
    reserve = P["ENERGY_RESERVE"]
    max_sorties = P["MAX_SORTIES_PER_UAV"]
    recharge = P["RECHARGE_MIN"]

    fleet = get_fleet(active_uav_ids)
    if not fleet:
        return {"status": "infeasible", "reasons": ["Нет доступных БВС в парке"]}

    payloads = get_payloads()

    # Фильтр по типам съёмки
    if survey_types:
        survey_zones = [z for z in survey_zones if z.get("survey_type") in survey_types]
    if not survey_zones:
        return {"status": "infeasible", "reasons": ["Нет зон съёмки выбранного типа"]}
    if not vpps:
        return {"status": "infeasible", "reasons": ["Не заданы площадки ВПП (старт/посадка)"]}

    forbidden_prepared = build_forbidden_prepared([z["rings"] for z in forbidden_zones])

    # --- Предварительный расчёт допустимых пар (БВС, зона) ---
    feasible: dict[tuple[str, str], float] = {}
    pair_info: dict[tuple[str, str], dict] = {}
    zone_problems: dict[str, list[str]] = {z["name"]: [] for z in survey_zones}

    for u in fleet:
        usable = (1 - reserve) * u["time_fly_min"] * u["battery_pct"] / 100.0
        v_ms = u["speed_kmh"] / 3.6
        for z in survey_zones:
            payload = gals.select_payload(payloads, u["model"], z["survey_type"])
            if payload is None:
                zone_problems[z["name"]].append(f"{u['name']}: нет совместимой ПН для типа «{TYPE_LABELS.get(z['survey_type'], z['survey_type'])}»")
                continue
            if wind_kmh > u["max_wind_kmh"]:
                zone_problems[z["name"]].append(f"{u['name']}: ветер {wind_kmh} км/ч > предела {u['max_wind_kmh']} км/ч")
                continue
            plan = gals.plan_zone(
                z["name"], z["survey_type"], z["rings"][0][0], gsd, side_overlap,
                u["model"], u["speed_kmh"], payload, P["TURN_TIME_S"], P["MAX_ALTITUDE_M"],
            )
            if plan is None:
                zone_problems[z["name"]].append(f"{u['name']}: зона вырождена")
                continue

            best = None
            for v in vpps:
                vpt = (v["lon"], v["lat"])
                if route_crosses_forbidden(vpt, plan.centroid, forbidden_prepared):
                    zone_problems[z["name"]].append(f"{u['name']}: коридор от {v['name']} пересекает запретную зону")
                    continue
                d_go = gals.haversine_m(vpt, plan.entry) * P["ROUTE_CORRIDOR_FACTOR"]
                d_back = gals.haversine_m(plan.exit, vpt) * P["ROUTE_CORRIDOR_FACTOR"]
                t_loop = (d_go + d_back) / v_ms / 60.0 + plan.t_survey_min + P["CLIMB_TIME_MIN"]
                if best is None or t_loop < best["t_loop"]:
                    best = {"t_loop": t_loop, "vpp": v, "d_go": d_go, "d_back": d_back}
            if best is None:
                zone_problems[z["name"]].append(f"{u['name']}: нет ВПП без пересечения запретных зон")
                continue
            if best["t_loop"] > usable:
                zone_problems[z["name"]].append(
                    f"{u['name']}: батарея {best['t_loop']:.0f} мин > доступных {usable:.0f} мин (запас {reserve:.0%})"
                )
                continue
            key = (str(u["id"]), z["name"])
            feasible[key] = round(best["t_loop"], 3)
            pair_info[key] = {"plan": plan, "vpp": best["vpp"], "uav": u}

    uncovered = [z for z in survey_zones if not any(k[1] == z["name"] for k in feasible)]
    if uncovered:
        reasons = []
        for z in uncovered:
            details = "; ".join(dict.fromkeys(zone_problems[z["name"]])) or "нет вариантов"
            reasons.append(f"Зона «{z['name']}» не может быть выполнена: {details}")
        return {"status": "infeasible", "reasons": reasons}

    # --- MILP: три варианта ---
    uav_ids = [str(u["id"]) for u in fleet]
    zone_names = [z["name"] for z in survey_zones]
    variants = {}
    for mode in (milp.MODE_RECOMMENDED, milp.MODE_TIME, milp.MODE_RESOURCE):
        solved = milp.solve(mode, feasible, uav_ids, zone_names, max_sorties, recharge)
        if solved is None:
            continue
        variants[mode] = _build_variant(mode, solved["assignment"], pair_info, gsd, wind_kmh)

    if not variants:
        return {"status": "infeasible", "reasons": ["MILP не нашёл выполнения (Infeasible)"]}

    return {
        "status": "success",
        "variants": variants,
        "common": {
            "gsd_m_px": gsd,
            "wind_kmh": wind_kmh,
            "side_overlap": side_overlap,
            "front_overlap": front_overlap,
            "energy_reserve": reserve,
            "zones": [{"name": z["name"], "type": z["survey_type"]} for z in survey_zones],
            "uavs": [
                {"id": u["id"], "name": u["name"], "model": u["model"]} for u in fleet
            ],
        },
    }


def _build_variant(mode: str, assignment: dict[str, str], pair_info: dict, gsd: float, wind_kmh: float) -> dict:
    P = settings.PLANNING
    reserve = P["ENERGY_RESERVE"]
    recharge = P["RECHARGE_MIN"]

    sorties: list[dict] = []
    # Очередность вылетов: по БВС, зоны в порядке задания
    zones_by_uav: dict[str, list[str]] = {}
    for zone, uav in assignment.items():
        zones_by_uav.setdefault(uav, []).append(zone)

    for uav, zones in zones_by_uav.items():
        t_cursor = 0.0
        for zone in zones:
            info = pair_info[(uav, zone)]
            u = info["uav"]
            plan = info["plan"]
            vpp = info["vpp"]
            v_ms = u["speed_kmh"] / 3.6
            d_go = gals.haversine_m((vpp["lon"], vpp["lat"]), plan.entry) * P["ROUTE_CORRIDOR_FACTOR"]
            d_back = gals.haversine_m(plan.exit, (vpp["lon"], vpp["lat"])) * P["ROUTE_CORRIDOR_FACTOR"]
            t_transit = (d_go + d_back) / v_ms / 60.0
            t_loop = t_transit + plan.t_survey_min + P["CLIMB_TIME_MIN"]
            # Доля от общего заряда батареи (мин. безопасный остаток 20%)
            total_battery_min = u["time_fly_min"] * u["battery_pct"] / 100.0
            route = [(vpp["lon"], vpp["lat"])] + [[c[0], c[1]] for c in plan.serpentine] + [(vpp["lon"], vpp["lat"])]
            sorties.append({
                "uav_id": int(uav),
                "uav": u["name"],
                "model": u["model"],
                "zone": zone,
                "survey_type": plan.survey_type,
                "payload": plan.payload_name,
                "vpp": vpp["name"],
                "start_min": round(t_cursor, 1),
                "duration_min": round(t_loop, 1),
                "t_transit_min": round(t_transit, 1),
                "t_survey_min": plan.t_survey_min,
                "altitude_m": plan.altitude_m,
                "speed_kmh": u["speed_kmh"],
                "battery_used_pct": round(t_loop / total_battery_min * 100.0, 1),
                "n_lawns": plan.n_lawns,
                "distance_km": round((d_go + plan.survey_distance_m + d_back) / 1000.0, 2),
                "stages": ["takeoff", "transit_to_zone", "survey", "return", "landing"],
                "route": [[c[0], c[1]] for c in route],
                "v_ms": v_ms,
                "_route": route,
            })
            t_cursor += t_loop + recharge

    # Проверка опасных сближений и сдвиг стартов (FR-17)
    conflict_input = [
        {"start_min": s["start_min"], "duration_min": s["duration_min"],
         "route": s["_route"], "v_ms": s["v_ms"]}
        for s in sorties
    ]
    resolve_conflicts(conflict_input, P["MIN_SEPARATION_M"], P["CONFLICT_TIME_STEP_S"])
    for s, ci in zip(sorties, conflict_input):
        s["start_min"] = ci["start_min"]
        del s["_route"]
        del s["v_ms"]

    total_flight = round(sum(s["duration_min"] for s in sorties), 1)
    makespan = round(max(s["start_min"] + s["duration_min"] for s in sorties), 1)
    return {
        "criterion": mode,
        "title": milp.MODE_TITLES[mode],
        "metrics": {
            "total_time_min": makespan,
            "total_flight_min": total_flight,
            "uavs_used": len(zones_by_uav),
            "sorties": len(sorties),
        },
        "sorties": sorties,
    }

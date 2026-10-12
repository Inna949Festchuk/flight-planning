"""Точка входа."""

import os
import json

from models import Unit
from uavs import UAVS
from payloads import (
    PAYLOADS, SURVEY_ORDER, default_payload, gsd_cm_from_m,
    payload_for_survey,
)
from geojson_loader import GeoJSONLoader
from bases import BaseLoader
from multi_zone import MultiZoneSolver
from pareto import Pareto
from report import Reporter


OVERLAP_X = 50.0

# Сколько бортов каждого типа стоит на каждой базе.
COUNTS_PER_BASE = {
    "Геоскан 201": 4,
    "Геоскан 801": 2,
    "Genimi": 2,
}

PAYLOAD_OVERRIDES = {}


def get_payload(uav_name):
    if uav_name in PAYLOAD_OVERRIDES:
        return PAYLOADS[PAYLOAD_OVERRIDES[uav_name]]
    return default_payload(uav_name)


def get_count(uav_name):
    return COUNTS_PER_BASE.get(uav_name, UAVS[uav_name].count)


def _split_count(count, survey_types):
    """Делит число бортов по типам съёмки, не создавая лишних копий."""
    if count <= 0 or not survey_types:
        return []
    base, extra = divmod(count, len(survey_types))
    parts = []
    for index, survey_type in enumerate(survey_types):
        share = base + (1 if index < extra else 0)
        if share:
            parts.append((survey_type, share))
    return parts


def make_units(bases, zones=None):
    """На каждой базе свой парк: один борт — одна камера и своя ВПП.

    Если районы заданы, камеры делятся только по тем типам съёмки,
    которые борт умеет и которые есть среди районов.
    """
    if zones is None:
        needed = ["visible"]
    else:
        present = {getattr(zone, "survey_type", "visible") for zone in zones}
        needed = [survey_type for survey_type in SURVEY_ORDER if survey_type in present]
        if not needed:
            needed = ["visible"]

    units = []
    for base in bases:
        for uav_name, uav in UAVS.items():
            count = get_count(uav_name)
            capable = [survey_type for survey_type in needed
                       if payload_for_survey(uav_name, survey_type) is not None]
            if not capable:
                capable = ["visible"]
            seq = 0
            for survey_type, share in _split_count(count, capable):
                payload = payload_for_survey(uav_name, survey_type)
                if payload is None:
                    payload = get_payload(uav_name)
                    survey_type = "visible"
                for _ in range(share):
                    seq += 1
                    units.append(Unit(
                        name=f"{uav_name}/{payload.pn_name}/{base.name} #{seq}",
                        uav=uav,
                        payload=payload,
                        base=base,
                        survey_type=survey_type,
                    ))
    return units


def ask_gsd_m():
    """Разрешение с консоли, м/пиксель."""
    while True:
        raw = input("Требуемое разрешение, м/пиксель: ").strip().replace(",", ".")
        try:
            gsd_m = float(raw)
        except ValueError:
            print("Введите число, например 5")
            continue
        if gsd_m <= 0:
            print("Разрешение должно быть больше нуля")
            continue
        return gsd_m


def save_assignment(best, zones, gsd_m, filepath="assignment.json"):
    """Сохраняет назначение бортов по зонам в JSON."""
    assignments = []
    for zone, zr in zip(zones, best.zones):
        for row in zr.rows:
            if row.area > 1e-9:
                assignments.append({
                    "zone": zone.name,
                    "unit": row.unit_name,
                    "area": round(row.area, 4),
                })

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump({
            "gsd_m": gsd_m,
            "overlap_x": OVERLAP_X,
            "assignments": assignments,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n>>> Назначение сохранено в {filepath} "
          f"({len(assignments)} записей)")
    for a in assignments:
        print(f"    {a['zone']}: {a['unit']}, {a['area']} км²")


def main():
    if not os.path.exists("zones.geojson"):
        print("Нет zones.geojson")
        return
    if not os.path.exists("bases.geojson"):
        print("Нет bases.geojson")
        return

    zones = GeoJSONLoader().load("zones.geojson")
    print(f"Зон: {len(zones)}")
    for z in zones:
        print(f"  {z.name}: {z.area:.3f} км², центр ({z.lat:.4f}, {z.lon:.4f})")

    bases = BaseLoader().load("bases.geojson")
    print(f"Баз: {len(bases)}")
    for b in bases:
        print(f"  {b.name}: ({b.lat:.4f}, {b.lon:.4f})")

    units = make_units(bases)
    print(f"\nВсего бортов: {len(units)}")
    for u in units:
        print(f"  {u.name}")

    gsd_m = ask_gsd_m()
    gsd_cm = gsd_cm_from_m(gsd_m)
    print(f"\nПараметры: GSD={gsd_m} м/пиксель "
          f"({gsd_cm:g} см/пиксель), перекрытие={OVERLAP_X}%")

    solver = MultiZoneSolver(gsd_cm, OVERLAP_X, step=0.5,
                             allow_partial_planes=True)
    assignment = solver.solve(units, zones, bases, use_local_opt=True)

    # ── ДИАГНОСТИКА ──
    print("\n── НАЗНАЧЕНИЕ ПО ЗОНАМ ──")
    for j, (units_j, zone) in enumerate(zip(assignment, zones)):
        print(f"  {zone.name} (S={zone.area:.3f}): {len(units_j)} бортов")
        for u in units_j:
            ac, base = solver.single._aircraft_for(
                u, zone, solver.gsd_cm, solver.overlap_x, bases)
            print(f"    {u.name} → {base.name}, "
                  f"S_вылет={ac.area_per_flight:.4f} км², "
                  f"t={ac.flight_time_h:.3f} ч, "
                  f"max_flights={ac.max_flights}")

    print("\n── ПРОВЕРКА SINGLE_ZONE ──")
    for j, (units_j, zone) in enumerate(zip(assignment, zones)):
        if not units_j:
            print(f"  {zone.name}: НЕТ БОРТОВ")
            continue
        results = solver.single.solve(units_j, zone, solver.gsd_cm,
                                      solver.overlap_x, bases)
        print(f"  {zone.name}: {len(results)} решений")
        if results:
            best = min(results, key=lambda r: (r.T, r.R))
            print(f"    лучший: T={best.T}, R={best.R}, "
                  f"S_actual={best.S_actual}")

    front = solver.build_front(assignment, zones, bases, max_combos=1000)

    if not front:
        print("Pareto-фронт пуст")
        return

    Reporter.print_front(front)

    # ── Три режима + сохранение ──
    best_by_mode = {}
    for mode in ["time", "resource", "balanced"]:
        print(f"\n{'=' * 88}")
        print(f"РЕЖИМ: {mode.upper()}")
        print(f"{'=' * 88}")
        best = Pareto.pick_best(front, mode=mode)
        Reporter.print_result(best, zones)
        best_by_mode[mode] = best

    # Сохраняем назначение для режима "time"
    save_assignment(best_by_mode["time"], zones, gsd_m, "assignment.json")


if __name__ == "__main__":
    main()
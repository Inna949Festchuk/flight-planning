"""Построение маршрутов для назначенных бортов + визуализация."""

import json
from shapely.geometry import shape
from geojson_loader import GeoJSONLoader
from bases import BaseLoader
from payloads import default_payload, gsd_cm_from_m, payload_from_unit_name
from uavs import UAVS
from coverage import Coverage
from paths import ForbiddenRouter, PathBuilder
from visualize import plot_all
from factory import best_base_for_zone


OVERLAP_X = 50.0


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


def load_assignments(filepath="assignment.json"):
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    rows = [(item["zone"], item["unit"], item["area"])
            for item in data["assignments"]]
    overlap_x = data.get("overlap_x", OVERLAP_X)
    return rows, overlap_x


def load_polygons(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    result = {}
    for feat in data.get("features", []):
        name = feat["properties"].get("name", "?")
        geom = shape(feat["geometry"])
        result[name] = geom
    return result


def get_uav_and_payload(unit_name):
    payload = payload_from_unit_name(unit_name)
    for uav_name, uav in UAVS.items():
        if uav_name in unit_name:
            if payload is None or payload.uav != uav_name:
                payload = default_payload(uav_name)
            return uav, payload
    raise ValueError(f"Не найден UAV для {unit_name}")


def build_route_paths(zones, bases, assignments, gsd_cm, overlap_x, forbidden=None):
    """Галсы по назначению. У каждой зоны должен быть shapely-полигон в .polygon."""
    router = ForbiddenRouter(forbidden) if forbidden else None
    if router is not None and not router.obstacles:
        router = None
    if router is not None:
        for base in bases:
            router.assert_outside(base)

    paths = []
    by_zone = {}
    for zone_name, unit_name, area in assignments:
        by_zone.setdefault(zone_name, []).append((unit_name, area))

    for zone_name, units_areas in by_zone.items():
        zone = next(z for z in zones if z.name == zone_name)
        polygon = zone.polygon
        if polygon is None:
            continue
        if router is not None:
            polygon = router.clip(polygon, zone_name)

        builders = []
        for unit_name, area in units_areas:
            uav, payload = get_uav_and_payload(unit_name)
            cov = Coverage(uav, payload, gsd_cm, overlap_x)
            base = next((b for b in bases if b.name in unit_name), None)
            if base is None:
                base = best_base_for_zone(uav, payload, gsd_cm, overlap_x,
                                          bases, zone)
            builder = PathBuilder(
                line_spacing_m=cov.D_x_km * 1000,
                speed_kmh=uav.speed_kmh,
                angle_step=5,
                router=router,
                route_label=f"от {base.name} к району {zone_name}",
            )
            builders.append((unit_name, area, builder, base, cov))

        ref_builder = builders[0][2]
        ref_base = builders[0][3]
        ref_area = builders[0][1]
        ref_path = ref_builder.best_for_zone(polygon, ref_base, ref_area)
        if ref_path is None:
            continue

        best_angle = ref_path.angle_deg
        best_entry = ref_path.entry_corner
        all_lines = ref_builder._snake_order(
            ref_builder.build_lines(polygon, best_angle),
            best_entry,
            best_angle,
        )
        total_area_zone = sum(area for _, area in units_areas)
        total_lines = len(all_lines)
        start_idx = 0
        n_units = len(builders)
        slices = []

        for i, (unit_name, area, builder, base, cov) in enumerate(builders):
            remaining_units = n_units - i
            remaining_lines = total_lines - start_idx
            if remaining_units == 1:
                end_idx = total_lines
            else:
                share = area / total_area_zone if total_area_zone else 0
                count = int(round(total_lines * share))
                max_count = remaining_lines - (remaining_units - 1)
                count = min(count, max_count)
                count = max(1, count) if remaining_lines else 0
                end_idx = start_idx + count
            slices.append((unit_name, area, builder, base, cov,
                           all_lines[start_idx:end_idx]))
            start_idx = end_idx

        for unit_name, area, builder, base, cov, lines in slices:
            if not lines:
                continue
            path = builder.evaluate(lines, best_entry, base, area,
                                    already_sorted=True, angle_deg=best_angle)
            path.unit_name = unit_name
            path.zone_name = zone_name
            path.angle_deg = best_angle
            path.altitude_m = cov.H_m
            paths.append(path)
    return paths


def main():
    print(">>> main() запущен")
    gsd_m = ask_gsd_m()
    gsd_cm = gsd_cm_from_m(gsd_m)

    zones = GeoJSONLoader().load("zones.geojson")
    bases = BaseLoader().load("bases.geojson")
    polygons = load_polygons("zones.geojson")

    for z in zones:
        if z.name in polygons:
            z.polygon = polygons[z.name]

    ASSIGNMENTS, overlap_x = load_assignments("assignment.json")
    print(f">>> Назначений: {len(ASSIGNMENTS)}")
    print(f">>> GSD={gsd_m} м/пиксель ({gsd_cm:g} см/пиксель), "
          f"перекрытие={overlap_x}%")
    for z_name, u_name, a in ASSIGNMENTS:
        print(f"    {z_name}: {u_name}, {a:.4f} км²")

    paths = []

    by_zone = {}
    for zone_name, unit_name, area in ASSIGNMENTS:
        by_zone.setdefault(zone_name, []).append((unit_name, area))

    for zone_name, units_areas in by_zone.items():
        zone = next(z for z in zones if z.name == zone_name)
        polygon = polygons[zone_name]

        builders = []
        for unit_name, area in units_areas:
            uav, payload = get_uav_and_payload(unit_name)
            cov = Coverage(uav, payload, gsd_cm, overlap_x)
            base = next((b for b in bases if b.name in unit_name), None)
            if base is None:
                base = best_base_for_zone(uav, payload, gsd_cm, overlap_x,
                                          bases, zone)
            builder = PathBuilder(
                line_spacing_m=cov.D_x_km * 1000,
                speed_kmh=uav.speed_kmh,
                angle_step=5,
            )
            builders.append((unit_name, area, builder, base, cov))

        ref_unit, ref_area, ref_builder, ref_base, ref_cov = builders[0]
        ref_path = ref_builder.best_for_zone(polygon, ref_base, ref_area)

        if ref_path is None:
            print(f"Не удалось построить маршрут для {zone_name}")
            continue

        best_angle = ref_path.angle_deg
        best_entry = ref_path.entry_corner

        print(f"\n{zone_name}: угол={best_angle}°, вход={best_entry}")

        all_lines_raw = ref_builder.build_lines(polygon, best_angle)
        all_lines = ref_builder._snake_order(all_lines_raw, best_entry,
                                             best_angle)

        total_area_zone = sum(a for _, a in units_areas)
        total_lines = len(all_lines)

        # Список, а не словарь: у двух бортов одного типа имя совпадает,
        # и запись по имени затирала бы уже нарезанные галсы.
        assigned = []
        start_idx = 0
        n_units = len(builders)

        for i, (unit_name, area, builder, base, cov) in enumerate(builders):
            remaining_units = n_units - i
            remaining_lines = total_lines - start_idx

            if remaining_units == 1:
                end_idx = total_lines
            else:
                share = area / total_area_zone
                count = int(round(total_lines * share))
                max_count = remaining_lines - (remaining_units - 1)
                count = min(count, max_count)
                count = max(1, count)
                end_idx = start_idx + count

            lines = all_lines[start_idx:end_idx]
            assigned.append((unit_name, area, builder, base, cov, lines))
            print(f"  {unit_name}: галсов [{start_idx}:{end_idx}] = {len(lines)}")
            start_idx = end_idx

        for unit_name, area, builder, base, cov, lines in assigned:
            if not lines:
                continue

            path = builder.evaluate(lines, best_entry, base, area,
                                    already_sorted=True, angle_deg=best_angle)
            path.unit_name = unit_name
            path.zone_name = zone_name
            path.angle_deg = best_angle
            path.altitude_m = cov.H_m
            paths.append(path)

            print(f"  {unit_name}: "
                  f"H={cov.H_m:.0f} м, "
                  f"галсов={path.n_lines}, "
                  f"длина={path.total_length_m/1000:.2f} км, "
                  f"время={path.total_time_h:.3f} ч "
                  f"(перелёт={path.transfer_time_h:.3f})")

    print(f"\n>>> Всего маршрутов: {len(paths)}")

    plot_all(zones, bases, paths, "paths.png")
    print(">>> Готово")


if __name__ == "__main__":
    main()
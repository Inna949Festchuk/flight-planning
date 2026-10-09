"""Проверки безопасности маршрутов: запретные зоны, опасные сближения, посадка."""

from __future__ import annotations

from shapely.geometry import LineString, Point
from shapely.prepared import prep

from .gals import haversine_m


def route_crosses_forbidden(
    vpp_lonlat: tuple[float, float],
    target_lonlat: tuple[float, float],
    forbidden_prepared: list,
) -> bool:
    """Пересекает ли прямой коридор ВПП→зона запретные области (FR-16)."""
    if not forbidden_prepared:
        return False
    line = LineString([vpp_lonlat, target_lonlat])
    return any(f.intersects(line) for f in forbidden_prepared)


def build_forbidden_prepared(forbidden_zone_rings: list[list[list[list[float]]]]) -> list:
    """forbidden_zone_rings: список зон; зона = [полигон...]; полигон = [кольцо...]."""
    from shapely.geometry import Polygon

    polys = []
    for rings in forbidden_zone_rings:
        for polygon_rings in rings:
            if not polygon_rings:
                continue
            poly = Polygon(polygon_rings[0], polygon_rings[1:])
            if poly.is_valid and not poly.is_empty:
                polys.append(prep(poly))
    return polys


def _position_on_route(route: list[list[float]], v_ms: float, t_s: float) -> tuple[float, float]:
    """Позиция (lon, lat) на маршруте в момент t_s после старта (однородная скорость)."""
    if t_s <= 0:
        return route[0]
    dist = t_s * v_ms
    total = 0.0
    for i in range(len(route) - 1):
        seg = haversine_m(tuple(route[i]), tuple(route[i + 1]))
        if total + seg >= dist:
            frac = (dist - total) / seg if seg > 0 else 0.0
            a, b = route[i], route[i + 1]
            return (a[0] + (b[0] - a[0]) * frac, a[1] + (b[1] - a[1]) * frac)
        total += seg
    return route[-1]


def resolve_conflicts(
    sorties: list[dict],
    min_separation_m: float,
    time_step_s: float,
    max_iterations: int = 6,
) -> list[dict]:
    """Дискретная проверка опасных сближений (FR-17) и сдвиг стартов.

    sorties: [{"start_min", "duration_min", "route": [[lon, lat], ...], "v_ms"}]
    Возвращает те же словари с обновлёнными start_min (минутах).
    """
    delays = {i: 0.0 for i in range(len(sorties))}
    for _ in range(max_iterations):
        conflict_found = False
        for i in range(len(sorties)):
            for j in range(i + 1, len(sorties)):
                a, b = sorties[i], sorties[j]
                start_a = (a["start_min"] + delays[i]) * 60.0
                end_a = start_a + a["duration_min"] * 60.0
                start_b = (b["start_min"] + delays[j]) * 60.0
                end_b = start_b + b["duration_min"] * 60.0
                t_from = max(start_a, start_b)
                t_to = min(end_a, end_b)
                if t_from >= t_to:
                    continue
                t = t_from
                conflict_until = None
                while t <= t_to:
                    pa = _position_on_route(a["route"], a["v_ms"], t - start_a)
                    pb = _position_on_route(b["route"], b["v_ms"], t - start_b)
                    if haversine_m(pa, pb) < min_separation_m:
                        conflict_until = t
                    t += time_step_s
                if conflict_until is not None:
                    # Сдвинем более поздний старт на время пересечения + минуту
                    delay_needed = (conflict_until - t_from) / 60.0 + 1.0
                    if start_b >= start_a:
                        delays[j] = max(delays[j], delay_needed)
                    else:
                        delays[i] = max(delays[i], delay_needed)
                    conflict_found = True
        if not conflict_found:
            break
    for i, s in enumerate(sorties):
        s["start_min"] = round(s["start_min"] + delays[i], 1)
    return sorties

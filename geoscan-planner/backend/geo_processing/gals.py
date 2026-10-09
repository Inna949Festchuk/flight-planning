"""Построение покрытия зоны галсами и расчёт времени съёмки.

Все расстояния в метрах, времена в минутах. Система координат — WGS 84 (EPSG:4326);
для локальных расчётов используется плоская проекция (эquirectangular) вокруг
центральной точки зоны.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.geometry import LineString, Point, Polygon as ShapelyPolygon

M_PER_DEG_LAT = 110_540.0
MIN_ALT_M = 20.0  # минимальная высота над поверхностью (учёт рельефа упрощённо)


def m_per_deg_lon(lat_deg: float) -> float:
    return 111_320.0 * math.cos(math.radians(lat_deg))


@dataclass
class PayloadSpec:
    uav_model: str
    type: str  # visible | thermal | multispectral
    name: str
    ly_mm: float
    lx_mm: float
    f_mm: float
    ny_px: int
    nx_px: int
    r_um: float


@dataclass
class ZonePlan:
    """Результат расчёта плана съёмки одной зоны одним БВС."""

    zone_name: str
    survey_type: str
    payload_name: str
    altitude_m: float
    frame_w_m: float
    frame_l_m: float
    n_lawns: int
    side_step_m: float
    lawn_len_m: float
    survey_distance_m: float
    t_survey_min: float
    centroid: tuple[float, float]  # (lon, lat)
    bbox_m: tuple[float, float]  # (w, h) в метрах
    # Координаты (lon, lat): точка входа в зону, серпантин галсов, точка выхода
    entry: list[float]
    serpentine: list[float]
    exit: list[float]


def select_payload(payloads: list[PayloadSpec], uav_model: str, survey_type: str) -> PayloadSpec | None:
    """Лучшая совместимая ПН: максимальная ширина кадра при заданном GSD (Ly*lx/r)."""
    candidates = [
        p for p in payloads if p.uav_model == uav_model and p.type == survey_type
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.ly_mm * p.lx_mm / p.r_um)


def _local_m(lon: float, lat: float, origin: tuple[float, float]) -> tuple[float, float]:
    o_lon, o_lat = origin
    return ((lon - o_lon) * m_per_deg_lon(o_lat), (lat - o_lat) * M_PER_DEG_LAT)


def _global_m(x: float, y: float, origin: tuple[float, float]) -> tuple[float, float]:
    o_lon, o_lat = origin
    return (o_lon + x / m_per_deg_lon(o_lat), o_lat + y / M_PER_DEG_LAT)


def plan_zone(
    zone_name: str,
    survey_type: str,
    ring_coords: list[list[float]],
    gsd: float,
    side_overlap: float,
    uav_model: str,
    speed_kmh: float,
    payload: PayloadSpec,
    turn_time_s: float,
    max_altitude_m: float = 3000.0,
) -> ZonePlan | None:
    """Строит галсы для зоны и считает время полезной съёмки.

    ring_coords — внешнее кольцо полигона [[lon, lat], ...] (замкнутое).
    Высота: H = GSD · 1000 · f / r (H — м, r — мкм, f — мм). Если целевой GSD
    требует высоты выше max_altitude_m, GSD автоматически увеличивается до
    достижимого на предельной высоте (для малоразмерных ПН типа тепловизора).
    Возвращает None, если зона вырождена.
    """
    if len(ring_coords) < 4:
        return None

    xs = [p[0] for p in ring_coords]
    ys = [p[1] for p in ring_coords]
    min_lon, max_lon = min(xs), max(xs)
    min_lat, max_lat = min(ys), max(ys)
    origin = ((min_lon + max_lon) / 2, (min_lat + max_lat) / 2)

    w_m = (max_lon - min_lon) * m_per_deg_lon(origin[1])
    h_m = (max_lat - min_lat) * M_PER_DEG_LAT
    if w_m < 5 or h_m < 5:
        return None

    altitude = min(max(gsd * 1000.0 * payload.f_mm / payload.r_um, MIN_ALT_M), max_altitude_m)
    # Фактический GSD на достигнутой высоте (рассчитан заново — он может быть
    # выше целевого, если высота уперлась в предел)
    gsd_eff = altitude * payload.r_um / (1000.0 * payload.f_mm)
    # Размеры кадра (м): по ly — ny пикселей, по lx — nx пикселей
    frame_y = gsd_eff * payload.ny_px
    frame_x = gsd_eff * payload.nx_px

    # Галсы вдоль большей стороны bbox
    if w_m >= h_m:
        lawn_len = w_m
        width_perp = h_m
        frame_perp = frame_y
        along_x = True
    else:
        lawn_len = h_m
        width_perp = w_m
        frame_perp = frame_x
        along_x = False

    if width_perp <= frame_perp:
        n_lawns = 1
        side_step = 0.0
    else:
        side_step = frame_perp * (1 - side_overlap)
        n_lawns = math.ceil((width_perp - frame_perp) / side_step) + 1
        # Равномерно раскладываем галсы на всю ширину зоны
        side_step = (width_perp - frame_perp) / (n_lawns - 1)

    min_x = _local_m(min_lon, min_lat, origin)
    x0, y0 = min_x

    # Полигон зоны в локальных метрических координатах (для клиппинга галсов)
    ring_local = [_local_m(p[0], p[1], origin) for p in ring_coords]
    zone_poly = ShapelyPolygon(ring_local)

    # Серпантин: каждый галс — линия перпендикулярно боковому смещению,
    # обрезанная по полигону (entry/exit оказываются на границе зоны).
    # Для вогнутых полигонов галс может разрезаться на сегменты —
    # соединяем их прямыми перелётами (документированное упрощение).
    def clip_lawn(off: float):
        """Секции галса со смещением off внутри полигона или None."""
        if along_x:  # горизонтальные галсы: длина по X, смещение по Y
            a = (x0, y0 + off)
            b = (x0 + lawn_len, y0 + off)
        else:  # вертикальные галсы: длина по Y, смещение по X
            a = (x0 + off, y0)
            b = (x0 + off, y0 + lawn_len)
        clipped = LineString([a, b]).intersection(zone_poly)
        if clipped.is_empty or clipped.geom_type in ("Point", "GeometryCollection"):
            return None
        parts = clipped.geoms if clipped.geom_type == "MultiLineString" else [clipped]
        pts = []
        for part in parts:
            for pt in part.coords:
                pts.append((pt[0], pt[1]))
        return pts if len(pts) >= 2 else None

    # Смещения: равномерная раскладка; одиночный галс — средней линией
    # (через центр bbox), иначе он может лишь касаться неровного полигона
    if n_lawns == 1:
        offsets = [width_perp / 2]
    else:
        offsets = [i * side_step for i in range(n_lawns)]

    serp_local: list[list[float]] = []
    total_dist = 0.0
    prev_pt: tuple[float, float] | None = None
    active_lawns = 0
    for i, off in enumerate(offsets):
        pts = clip_lawn(off)
        if pts is None:
            continue
        if i % 2 == 1:  # змейка: направление галсов чередуется
            pts = list(reversed(pts))
        for p in pts:
            if prev_pt is not None:
                d = math.hypot(p[0] - prev_pt[0], p[1] - prev_pt[1])
                if d > 0.01:
                    total_dist += d
                    serp_local.append(list(p))
            else:
                serp_local.append(list(p))
            prev_pt = p
        active_lawns += 1

    if active_lawns == 0:
        # Фолбэк: пробуем несколько позиций (центр, quartили, края)
        for frac in (0.5, 0.25, 0.75, 0.1, 0.9):
            pts = clip_lawn(width_perp * frac)
            if pts is None:
                continue
            for p in pts:
                if prev_pt is not None:
                    d = math.hypot(p[0] - prev_pt[0], p[1] - prev_pt[1])
                    if d > 0.01:
                        total_dist += d
                        serp_local.append(list(p))
                else:
                    serp_local.append(list(p))
                prev_pt = p
            active_lawns = 1
            break

    if active_lawns == 0 or len(serp_local) < 2:
        return None

    serp_dist = total_dist
    v_ms = speed_kmh / 3.6
    t_survey = (serp_dist / v_ms) / 60.0 + (active_lawns - 1) * turn_time_s / 60.0

    serp = [_global_m(x, y, origin) for x, y in serp_local]
    entry = serp[0]
    exit_pt = serp[-1]
    centroid = origin

    return ZonePlan(
        zone_name=zone_name,
        survey_type=survey_type,
        payload_name=payload.name,
        altitude_m=round(altitude, 1),
        frame_w_m=round(frame_perp, 1),
        frame_l_m=round(frame_perp, 1),
        n_lawns=active_lawns,
        side_step_m=round(side_step, 1),
        lawn_len_m=round(lawn_len, 1),
        survey_distance_m=round(serp_dist, 1),
        t_survey_min=round(t_survey, 2),
        centroid=centroid,
        bbox_m=(round(w_m, 1), round(h_m, 1)),
        entry=entry,
        serpentine=serp,
        exit=exit_pt,
    )


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1 = a
    lon2, lat2 = b
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))

"""Сборка Aircraft под конкретную зону и базу."""

from models import Aircraft, Base, Zone
from uavs import UAV
from payloads import Payload
from coverage import Coverage
from bases import haversine_km


def make_aircraft(uav, payload, gsd_cm, overlap_x, base, zone):
    """Собирает Aircraft для пары (база, зона)."""
    cov = Coverage(uav, payload, gsd_cm, overlap_x)
    dist = haversine_km(base.lat, base.lon, zone.lat, zone.lon)

    area = cov.area_per_flight_km2(dist)
    t = cov.flight_time_h(dist)

    if uav.is_plane and uav.resource_flights > 0:
        max_flights = uav.resource_flights
        resource_flights = uav.resource_flights
    else:
        max_flights = 0
        resource_flights = 0

    name = f"{uav.name}/{payload.pn_name}/{base.name}"

    return Aircraft(
        name=name,
        flight_time_h=t,
        area_per_flight=area,
        resource_h=uav.resource_h,
        partial_proportional=not uav.is_plane,
        max_flights=max_flights,
        resource_flights=resource_flights,
    )


def best_base_for_zone(uav, payload, gsd_cm, overlap_x, bases, zone):
    """Выбирает базу с максимальной площадью за вылет."""
    best, best_area = None, -1.0
    for b in bases:
        cov = Coverage(uav, payload, gsd_cm, overlap_x)
        dist = haversine_km(b.lat, b.lon, zone.lat, zone.lon)
        area = cov.area_per_flight_km2(dist)
        if area > best_area:
            best_area, best = area, b
    return best
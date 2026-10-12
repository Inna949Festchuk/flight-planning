"""Модель БВС."""

from dataclasses import dataclass


@dataclass
class UAV:
    name: str
    speed_kmh: float
    max_time_min: float
    return_reserve_pct: float
    count: int = 1
    resource_h: float = 240
    resource_flights: int = 0    # паспортный ресурс в полётах (для самолётов)
    is_plane: bool = False


UAVS = {
    "Геоскан 201": UAV(
        name="Геоскан 201",
        speed_kmh=100,
        max_time_min=180,
        return_reserve_pct=20,
        count=4,
        resource_h=240,
        resource_flights=80,
        is_plane=True,
    ),
    "Геоскан 801": UAV(
        name="Геоскан 801",
        speed_kmh=30,
        max_time_min=40,
        return_reserve_pct=20,
        count=2,
        resource_h=100,
        resource_flights=0,
        is_plane=False,
    ),
    "Genimi": UAV(
        name="Genimi",
        speed_kmh=30,
        max_time_min=40,
        return_reserve_pct=20,
        count=2,
        resource_h=100,
        resource_flights=0,
        is_plane=False,
    ),
}
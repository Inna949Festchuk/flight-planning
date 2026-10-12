"""Модели данных."""

from dataclasses import dataclass, field


@dataclass
class Zone:
    """Зона съёмки."""
    name: str
    area: float          # км²
    lat: float = 0.0
    lon: float = 0.0
    priority: float = 1.0
    survey_type: str = "visible"


@dataclass
class Base:
    """Точка взлёта/посадки."""
    name: str
    lat: float
    lon: float


@dataclass
class Aircraft:
    """Собранный борт под конкретную зону и базу."""
    name: str
    flight_time_h: float
    area_per_flight: float
    resource_h: float
    partial_proportional: bool
    max_flights: int = 0
    resource_flights: int = 0

    @property
    def productivity(self):
        return self.area_per_flight / self.flight_time_h

    @property
    def wear_per_unit(self):
        return self.flight_time_h / self.area_per_flight

    @property
    def flight_cost_pct(self):
        if self.resource_flights > 0:
            return 100.0 / self.resource_flights
        if self.max_flights > 0:
            return 100.0 / self.max_flights
        return self.flight_time_h / self.resource_h * 100


@dataclass
class Unit:
    """Физический борт: тип (UAV + Payload) и база, с которой он взлетает."""
    name: str
    uav: object           # UAV
    payload: object       # Payload
    base: object = None   # Base; None — базу выбирает алгоритм
    survey_type: str = "visible"


@dataclass
class FlightResult:
    unit_name: str
    flights: float
    flights_str: str
    area: float
    hours: float
    pct: float
    wear: float


@dataclass
class ZoneResult:
    zone_name: str
    T: float
    R: float
    H: float
    S_actual: float
    rows: list = field(default_factory=list)


@dataclass
class GlobalResult:
    T: float
    R: float
    H: float
    S_total: float
    wear: float
    zones: list = field(default_factory=list)
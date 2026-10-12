"""Стоимость полёта."""

from models import Aircraft, FlightResult


class CostCalculator:

    @staticmethod
    def flight_cost(a: Aircraft, area: float):
        if area <= 1e-9:
            return 0.0, 0.0
        if a.area_per_flight <= 1e-12:
            raise ValueError("Борт не достаёт до района: не хватает запаса хода")

        full = int(area // a.area_per_flight)
        rem = area - full * a.area_per_flight
        hours = full * a.flight_time_h

        if rem > 1e-9:
            hours += (rem / a.area_per_flight) * a.flight_time_h

        if a.partial_proportional:
            pct = hours / a.resource_h * 100
        else:
            flights_used = full + (1 if rem > 1e-9 else 0)
            pct = flights_used * a.flight_cost_pct

        return hours, pct

    @staticmethod
    def count_flights(a: Aircraft, area: float):
        if area <= 1e-9 or a.area_per_flight <= 1e-12:
            return 0, 0.0
        full = int(area // a.area_per_flight)
        rem = area - full * a.area_per_flight
        if rem > 1e-9:
            if a.partial_proportional:
                return full, rem / a.area_per_flight
            else:
                return full, 1.0
        return full, 0.0

    @staticmethod
    def flights_str(a: Aircraft, area: float):
        full, frac = CostCalculator.count_flights(a, area)
        if frac > 1e-9:
            return f"{full}+{frac:.2f}"
        return f"{full}"

    @staticmethod
    def make_row(unit_name, a: Aircraft, area: float) -> FlightResult:
        h, pct = CostCalculator.flight_cost(a, area)
        full, frac = CostCalculator.count_flights(a, area)
        return FlightResult(
            unit_name=unit_name,
            flights=round(full + frac, 3),
            flights_str=CostCalculator.flights_str(a, area),
            area=round(area, 4),
            hours=round(h, 4),
            pct=round(pct, 4),
            wear=round(h / area, 4) if area > 1e-9 else 0.0,
        )
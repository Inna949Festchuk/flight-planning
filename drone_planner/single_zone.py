"""Решатель для одной зоны."""

from itertools import product
from models import Unit, ZoneResult
from cost import CostCalculator
from factory import make_aircraft, best_base_for_zone


class SingleZoneSolver:

    def __init__(self, step=0.5, allow_partial_planes=True):
        self.step = step
        self.allow_partial_planes = allow_partial_planes
        self._cache = {}

    def _split_remainder(self, n, total):
        if n == 1:
            yield (total,)
            return
        for first in range(total + 1):
            for rest in self._split_remainder(n - 1, total - first):
                yield (first,) + rest

    def _aircraft_for(self, unit, zone, gsd_cm, overlap_x, bases):
        if unit.base is not None:
            base = unit.base
        else:
            base = best_base_for_zone(unit.uav, unit.payload, gsd_cm,
                                      overlap_x, bases, zone)
        aircraft = make_aircraft(unit.uav, unit.payload, gsd_cm, overlap_x,
                                 base, zone)
        aircraft.name = unit.name
        return aircraft, base

    def _plane_options(self, a, S):
        """
        Возможные площади для самолёта: 0, полные полёты,
        и последний неполный (дробный).
        """
        opts = set()
        opts.add(0.0)
        if a.area_per_flight <= 1e-12:
            return [0.0]

        max_full = min(a.max_flights, int(S / a.area_per_flight) + 1)
        for f in range(max_full + 1):
            full_area = f * a.area_per_flight
            if full_area <= S + 1e-9:
                opts.add(round(full_area, 4))
            if f < a.max_flights:
                start = full_area + self.step
                end = full_area + a.area_per_flight
                cur = start
                while cur <= end + 1e-9:
                    if cur <= S + 1e-9:
                        opts.add(round(cur, 4))
                    cur += self.step

        return sorted(opts)

    def generate_allocations(self, aircrafts, S):
        n = len(aircrafts)
        planes = [(i, a) for i, a in enumerate(aircrafts)
                  if not a.partial_proportional and a.area_per_flight > 1e-12]
        copters = [(i, a) for i, a in enumerate(aircrafts)
                   if a.partial_proportional and a.area_per_flight > 1e-12]

        plane_options = [self._plane_options(a, S) for _, a in planes]

        for combo in product(*plane_options):
            base = [0.0] * n
            used = 0.0
            for (idx, _), area in zip(planes, combo):
                base[idx] = area
                used += area
            if used > S + 1e-9:
                continue

            rem = S - used
            if rem <= 1e-9:
                yield base[:]
                continue

            # A. Коптеры: последний берёт точный остаток
            if copters:
                n_cop = len(copters)
                rem_steps = int(rem / self.step)
                if n_cop == 1:
                    areas = base[:]
                    areas[copters[0][0]] = rem
                    yield areas
                else:
                    for c in self._split_remainder(n_cop - 1, rem_steps):
                        areas = base[:]
                        total_used = 0.0
                        for (idx, _), k in zip(copters[:-1], c):
                            areas[idx] = k * self.step
                            total_used += k * self.step
                        last_idx, _ = copters[-1]
                        areas[last_idx] = rem - total_used
                        yield areas

            # B. Один самолёт берёт весь остаток (неполный полёт)
            if self.allow_partial_planes and planes:
                for idx, a in planes:
                    if a.area_per_flight <= 1e-12:
                        continue
                    if base[idx] / a.area_per_flight + 1 > a.max_flights:
                        continue
                    areas = base[:]
                    areas[idx] = base[idx] + rem
                    yield areas

    def evaluate(self, aircrafts, areas, zone_name):
        rows = []
        per_h = []
        total_pct = total_h = total_area = 0.0
        for a, area in zip(aircrafts, areas):
            row = CostCalculator.make_row(a.name, a, area)
            rows.append(row)
            per_h.append(row.hours)
            total_pct += row.pct
            total_h += row.hours
            total_area += row.area
        return ZoneResult(
            zone_name=zone_name,
            T=max(per_h) if per_h else 0.0,
            R=total_pct, H=total_h, S_actual=total_area, rows=rows,
        )

    def solve(self, units, zone, gsd_cm, overlap_x, bases):
        key = (tuple(u.name for u in units), round(zone.area, 4),
               gsd_cm, overlap_x, tuple(b.name for b in bases), self.step)
        if key in self._cache:
            return self._cache[key]

        aircrafts = []
        for u in units:
            ac, _ = self._aircraft_for(u, zone, gsd_cm, overlap_x, bases)
            aircrafts.append(ac)

        results = []
        for areas in self.generate_allocations(aircrafts, zone.area):
            if sum(areas) < zone.area - 1e-9:
                continue
            results.append(self.evaluate(aircrafts, areas, zone.name))

        self._cache[key] = results
        return results

    def solve_use_all(self, units, zone, gsd_cm, overlap_x, bases):
        """
        Возвращает решения, в которых используются ВСЕ борта зоны.
        Если таких нет — возвращает все решения.
        """
        results = self.solve(units, zone, gsd_cm, overlap_x, bases)
        if not results:
            return results

        full_use = []
        for r in results:
            used = sum(1 for row in r.rows if row.area > 1e-9)
            if used == len(units):
                full_use.append(r)

        return full_use if full_use else results
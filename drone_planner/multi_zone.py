"""Многозонная задача."""

from itertools import product
from models import GlobalResult
from single_zone import SingleZoneSolver
from pareto import Pareto


class MultiZoneSolver:

    def __init__(self, gsd_cm, overlap_x, step=0.5, allow_partial_planes=True):
        self.gsd_cm = gsd_cm
        self.overlap_x = overlap_x
        self.step = step
        self.allow_partial_planes = allow_partial_planes
        self.single = SingleZoneSolver(step, allow_partial_planes)

    # ── Вспомогательное ──

    def _prod(self, unit, zone, bases):
        ac, _ = self.single._aircraft_for(unit, zone, self.gsd_cm,
                                          self.overlap_x, bases)
        return ac.productivity

    @staticmethod
    def _compatible(unit, zone):
        """Борт снимает только район своего типа камеры."""
        return getattr(unit, "survey_type", "visible") == getattr(
            zone, "survey_type", "visible")

    def _reachable(self, unit, zone, bases):
        """Подходящая камера и ненулевая площадь за вылет с своей ВПП."""
        if not self._compatible(unit, zone):
            return False
        return self._prod(unit, zone, bases) > 1e-12

    # ── Жадное назначение ──

    def greedy_assign(self, units, zones, bases):
        """
        Каждый борт идёт в зону, где после его добавления
        оценочное время зоны будет наибольшим (самая «голодная» зона).
        """
        assignment = [[] for _ in zones]
        zone_prod = [0.0] * len(zones)

        for unit in units:
            best_j, best_t = None, None
            for j in range(len(zones)):
                if not self._reachable(unit, zones[j], bases):
                    continue
                p = self._prod(unit, zones[j], bases)
                total_prod = zone_prod[j] + p
                t_est = zones[j].area / total_prod if total_prod > 0 else float("inf")
                if best_t is None or t_est > best_t:
                    best_t, best_j = t_est, j
            if best_j is None:
                continue
            assignment[best_j].append(unit)
            zone_prod[best_j] += self._prod(unit, zones[best_j], bases)

        return assignment

    # ── Оценка назначения ──

    def evaluate(self, assignment, zones, bases):
        zrs = []
        T = R = H = S = 0.0
        for units_j, zone in zip(assignment, zones):
            if not units_j:
                return GlobalResult(float("inf"), float("inf"), 0, 0, 0, [])
            results = self.single.solve_use_all(units_j, zone, self.gsd_cm,
                                                self.overlap_x, bases)
            if not results:
                return GlobalResult(float("inf"), float("inf"), 0, 0, 0, [])
            best = min(results, key=lambda r: (r.T, r.R))
            zrs.append(best)
            T = max(T, best.T)
            R += best.R
            H += best.H
            S += zone.area
        return GlobalResult(round(T, 4), round(R, 4), round(H, 4),
                            round(S, 4), round(H / S, 4) if S else 0.0, zrs)

    def _better(self, a, b):
        if a.T < b.T - 1e-9:
            return True
        if abs(a.T - b.T) < 1e-9 and a.R < b.R - 1e-9:
            return True
        return False

    # ── Локальная оптимизация ──

    def local_optimize(self, assignment, zones, bases, max_iter=50):
        cur = [list(a) for a in assignment]
        score = self.evaluate(cur, zones, bases)
        it = 0
        while it < max_iter:
            it += 1
            improved = False

            # Перекидывание
            for jf in range(len(zones)):
                for i in range(len(cur[jf])):
                    unit = cur[jf][i]
                    for jt in range(len(zones)):
                        if jt == jf or not self._reachable(unit, zones[jt], bases):
                            continue
                        trial = [list(a) for a in cur]
                        trial[jf].pop(i)
                        trial[jt].append(unit)
                        s = self.evaluate(trial, zones, bases)
                        if self._better(s, score):
                            cur, score = trial, s
                            improved = True
                            break
                    if improved:
                        break
                if improved:
                    break
            if improved:
                continue

            # Обмен
            for j1 in range(len(zones)):
                for j2 in range(j1 + 1, len(zones)):
                    for i1 in range(len(cur[j1])):
                        for i2 in range(len(cur[j2])):
                            if (not self._reachable(cur[j1][i1], zones[j2], bases) or
                                    not self._reachable(cur[j2][i2], zones[j1], bases)):
                                continue
                            trial = [list(a) for a in cur]
                            trial[j1][i1], trial[j2][i2] = trial[j2][i2], trial[j1][i1]
                            s = self.evaluate(trial, zones, bases)
                            if self._better(s, score):
                                cur, score = trial, s
                                improved = True
                                break
                        if improved:
                            break
                    if improved:
                        break
                if improved:
                    break
            if not improved:
                break
        return cur, score

    # ── Pareto по комбинациям зон ──

    def build_front(self, assignment, zones, bases, max_combos=1000):
        zone_fronts = []
        for units_j, zone in zip(assignment, zones):
            if not units_j:
                return []
            results = self.single.solve_use_all(units_j, zone, self.gsd_cm,
                                                self.overlap_x, bases)
            if not results:
                return []
            front_j = Pareto.filter(results)
            front_j = Pareto.reduce_front(front_j, 10)
            zone_fronts.append(front_j)

        combos = product(*zone_fronts)
        results, count = [], 0
        for combo in combos:
            count += 1
            if count > max_combos:
                break
            T = max(r.T for r in combo)
            R = sum(r.R for r in combo)
            H = sum(r.H for r in combo)
            S = sum(r.S_actual for r in combo)
            results.append(GlobalResult(
                round(T, 4), round(R, 4), round(H, 4), round(S, 4),
                round(H / S, 4) if S else 0.0, list(combo),
            ))
        return Pareto.filter(results)

    # ── Главный вызов ──

    def solve(self, units, zones, bases, use_local_opt=True):
        a = self.greedy_assign(units, zones, bases)
        if use_local_opt:
            a, _ = self.local_optimize(a, zones, bases)
        return a
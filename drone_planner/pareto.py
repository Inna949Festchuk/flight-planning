"""Pareto-фильтр."""


class Pareto:

    @staticmethod
    def dominates(a, b):
        return (a.T <= b.T + 1e-9 and a.R <= b.R + 1e-9 and
                (a.T < b.T - 1e-9 or a.R < b.R - 1e-9))

    @staticmethod
    def filter(results):
        front = []
        for r in results:
            if not any(Pareto.dominates(o, r) for o in results if o is not r):
                front.append(r)
        seen, unique = set(), []
        for r in front:
            k = (round(r.T, 4), round(r.R, 4))
            if k not in seen:
                seen.add(k)
                unique.append(r)
        return sorted(unique, key=lambda x: (x.T, x.R))

    @staticmethod
    def pick_best(front, mode="balanced", w_time=0.5, w_res=0.5, time_limit=None):
        if not front:
            raise ValueError("Pareto-фронт пуст")
        if mode == "time":
            return min(front, key=lambda x: (x.T, x.R))
        if mode == "resource":
            return min(front, key=lambda x: (x.R, x.T))
        if mode in ("balanced", "weighted"):
            T_min = min(r.T for r in front) or 1.0
            R_min = min(r.R for r in front) or 1.0
            best, bs = None, None
            for r in front:
                s = w_time * (r.T / T_min) + w_res * (r.R / R_min)
                if bs is None or s < bs:
                    bs, best = s, r
            return best
        if mode == "limit":
            cand = [r for r in front if r.T <= time_limit + 1e-9]
            if not cand:
                raise ValueError(f"Нет решений с T ≤ {time_limit}")
            return min(cand, key=lambda x: (x.R, x.T))
        raise ValueError(f"Неизвестный режим: {mode}")

    @staticmethod
    def reduce_front(front, max_points=20):
        if len(front) <= max_points:
            return front
        idx = [int(i * (len(front) - 1) / (max_points - 1)) for i in range(max_points)]
        return [front[i] for i in sorted(set(idx))]
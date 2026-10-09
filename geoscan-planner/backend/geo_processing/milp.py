"""MILP-модель назначения зон на БВС (pulp + CBC).

Переменные: x[u, z] ∈ {0,1} — БВС u выполняет зону z (один полигон = один вылет).

Ограничения:
  * каждая зона — ровно одним БВС;
  * несовместимые пары (ПН, батарея, запретные зоны, ветер) исключены заранее;
  * не более MAX_SORTIES_PER_UAV вылетов на БВС.

Целевые функции (два критерия ТЗ + сбалансированный вариант):
  * time      — min T_makespan (время до посадки последнего БВС);
  * resource  — min суммарного налёта Σ t_loop;
  * recommended — min (T_makespan + 0.15 · Σ t_loop + 8 мин · число БВС).
    Штраф за задействованные БВС делает вариант отличимым от "time":
    он жертвует частью времени, чтобы задействовать меньше техники.
"""

from __future__ import annotations

import pulp

MODE_TIME = "time"
MODE_RESOURCE = "resource"
MODE_RECOMMENDED = "recommended"

MODE_TITLES = {
    MODE_TIME: "Лучший по времени",
    MODE_RESOURCE: "Лучший по ресурсу",
    MODE_RECOMMENDED: "Рекомендованный",
}

REC_WEIGHT = 0.15
REC_UAV_PENALTY_MIN = 8.0  # "цена" одного задействованного БВС в recommended


def solve(
    mode: str,
    feasible: dict[tuple[str, str], float],
    uav_ids: list[str],
    zone_names: list[str],
    max_sorties: int,
    recharge_min: float,
) -> dict | None:
    """Решает одну MILP-модель.

    feasible: {(uav_id, zone_name): t_loop_min} — только допустимые пары.
    Возвращает {"assignment": {zone: uav}, "objective": float} или None (Infeasible/Unbounded).
    """
    if not feasible or not zone_names:
        return None

    model = pulp.LpProblem(f"drone_assignment_{mode}", pulp.LpMinimize)
    X = {
        (uav_key, zone_key): pulp.LpVariable(f"x_{uav_key}_{zone_key}", cat="Binary")
        for (uav_key, zone_key) in feasible
    }

    # Каждый полигон — ровно один дрон
    for zone in zone_names:
        pairs = [(u, z) for (u, z) in feasible if z == zone]
        if not pairs:
            return None  # зона не покрыта никем
        model += pulp.lpSum(X[pair] for pair in pairs) == 1, f"cover_{zone}"

    # Не более K вылетов на БВС
    for uav in uav_ids:
        pairs = [(u, z) for (u, z) in feasible if u == uav]
        if pairs:
            model += pulp.lpSum(X[pair] for pair in pairs) <= max_sorties, f"sorties_{uav}"

    makespan = None
    if mode in (MODE_TIME, MODE_RECOMMENDED):
        makespan = pulp.LpVariable("makespan", lowBound=0)
        # T >= sum_z x*(t + R) - R  (оценка очереди вылетов с заменой АКБ)
        for uav in uav_ids:
            pairs = [(u, z) for (u, z) in feasible if u == uav]
            if pairs:
                model += makespan >= (
                    pulp.lpSum(X[pair] * (feasible[pair] + recharge_min) for pair in pairs)
                    - recharge_min
                ), f"makespan_{uav}"

    total = None
    if mode in (MODE_RESOURCE, MODE_RECOMMENDED):
        total = pulp.lpSum(X[pair] * t for pair, t in feasible.items())

    uav_count = None
    if mode == MODE_RECOMMENDED:
        # y[u] = 1, если БВС задействовано; штраф за число задействованных БВС
        used = {uav: pulp.LpVariable(f"used_{uav}", cat="Binary") for uav in uav_ids}
        for uav in uav_ids:
            pairs = [(u, z) for (u, z) in feasible if u == uav]
            if pairs:
                model += used[uav] <= pulp.lpSum(X[p] for p in pairs)
                for p in pairs:
                    model += used[uav] >= X[p]
        uav_count = pulp.lpSum(used.values())

    if mode == MODE_TIME:
        model += makespan
    elif mode == MODE_RESOURCE:
        model += total
    else:
        model += makespan + REC_WEIGHT * total + REC_UAV_PENALTY_MIN * uav_count

    status = model.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[model.status] != "Optimal":
        return None

    assignment: dict[str, str] = {}
    for (uav, zone), var in X.items():
        value = pulp.value(var)
        if value is not None and value > 0.5:
            assignment[zone] = uav
    if set(assignment) != set(zone_names):
        return None

    objective = pulp.value(model.objective)
    return {"assignment": assignment, "objective": float(objective) if objective is not None else 0.0}

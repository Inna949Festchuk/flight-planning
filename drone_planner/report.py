"""Вывод."""


class Reporter:

    @staticmethod
    def print_result(result, zones):
        print(f"\n{'=' * 88}")
        print("ЛУЧШЕЕ РЕШЕНИЕ")
        print(f"{'=' * 88}")
        print(f"T_общ  : {result.T} ч")
        print(f"R_общ  : {result.R} %")
        print(f"Σ налёт: {result.H} ч")
        print(f"Износ  : {result.wear} ч/ед")

        if result.zones:
            print("\n── РАСКЛАДКА ПО ЗОНАМ ──")
            for zone, zr in zip(zones, result.zones):
                print(f"\n  Зона {zone.name} (S={zone.area:.3f} км²):")
                print(f"    T_j = {zr.T} ч | R_j = {zr.R} %")
                print(f"    {'Борт':<28}{'Полётов':<12}{'Площадь':<12}"
                      f"{'Часов':<10}{'%рес':<10}{'ч/ед':<10}")
                print("    " + "-" * 80)
                for row in zr.rows:
                    if row.area > 1e-9:
                        print(f"    {row.unit_name:<28}{row.flights_str:<12}"
                              f"{row.area:<12}{row.hours:<10}"
                              f"{row.pct:<10}{row.wear:<10}")

    @staticmethod
    def print_front(front):
        print(f"\nPareto-фронт ({len(front)} точек):")
        print(f"{'#':<4}{'T_общ, ч':<12}{'R_общ, %':<12}{'Σ налёт':<12}{'износ':<12}")
        for i, r in enumerate(front):
            print(f"{i:<4}{r.T:<12}{r.R:<12}{r.H:<12}{r.wear:<12}")
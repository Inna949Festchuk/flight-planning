"""Расчёт полезной площади за вылет через галсы."""

from payloads import Payload
from uavs import UAV


class Coverage:
    STRIP_LENGTH_KM = 3.0
    TIME_PENALTY = 0.20

    def __init__(self, uav: UAV, payload: Payload, gsd_cm: float, overlap_x: float):
        self.uav = uav
        self.payload = payload
        self.gsd_cm = gsd_cm
        self.overlap_x = overlap_x

        self.H_m = payload.height_for_gsd(gsd_cm)
        self.D_x_km = payload.line_spacing(gsd_cm, overlap_x) / 1000

    def working_time_h(self):
        base = self.uav.max_time_min / 60
        base *= (1 - self.uav.return_reserve_pct / 100)
        base *= (1 - self.TIME_PENALTY)
        return base

    def flight_overhead_h(self, dist_km):
        return 2 * dist_km / self.uav.speed_kmh

    def area_per_flight_km2(self, dist_km=0.0):
        T_work = self.working_time_h()
        T_over = self.flight_overhead_h(dist_km)
        T_lines = T_work - T_over
        if T_lines <= 0:
            return 0.0
        t_line = self.STRIP_LENGTH_KM / self.uav.speed_kmh
        n_lines = T_lines / t_line
        return self.STRIP_LENGTH_KM * self.D_x_km * n_lines

    def flight_time_h(self, dist_km=0.0):
        return self.working_time_h() + self.flight_overhead_h(dist_km)
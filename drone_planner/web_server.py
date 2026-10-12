#!/usr/bin/env python3
"""Локальная карта: ВПП и районы из GeoJSON, расчёт текущим планировщиком."""

import json
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from shapely.geometry import Polygon
from shapely.validation import make_valid

from geojson_loader import _centroid, polygon_area_km2
from main import OVERLAP_X, make_units, save_assignment
from main_paths import build_route_paths
from models import Base, Zone
from multi_zone import MultiZoneSolver
from pareto import Pareto
from payloads import gsd_cm_from_m
from visualize import COLORS

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
HOST = "127.0.0.1"
PORT = 8765

_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
}

MODE_TITLE = {
    "time": "Минимальное время",
    "resource": "Минимальный ресурс",
    "balanced": "Время и ресурс",
}


def _bases_from_vpps(vpps):
    bases = []
    seen = set()
    for item in vpps:
        index = int(item["index"])
        if index < 1 or index > 6 or index in seen:
            continue
        seen.add(index)
        bases.append(Base(
            name=f"ВПП-{index}",
            lat=float(item["lat"]),
            lon=float(item["lon"]),
        ))
    bases.sort(key=lambda base: int(base.name.split("-")[1]))
    return bases


def _zones_from_polygons(polygons):
    zones = []
    for index, item in enumerate(polygons, start=1):
        ring = [(float(pair[0]), float(pair[1])) for pair in item["ring"]]
        if len(ring) < 3:
            continue
        survey_type = item.get("survey_type") or "visible"
        if survey_type not in ("visible", "multispectral", "thermal"):
            survey_type = "visible"
        area = polygon_area_km2(ring)
        lat, lon = _centroid(ring)
        zone = Zone(
            name=f"Район {index}",
            area=area,
            lat=lat,
            lon=lon,
            survey_type=survey_type,
        )
        zone.polygon = Polygon(ring)
        zones.append(zone)
    return zones


def _forbidden_from_payload(items):
    """Части запретных зон. В площадь районов не входят."""
    result = []
    for item in items or []:
        ring = [(float(pair[0]), float(pair[1])) for pair in item.get("ring") or []]
        if len(ring) < 3:
            continue
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        polygon = Polygon(ring)
        if not polygon.is_valid:
            polygon = make_valid(polygon)
        name = item.get("name") or "Запрет"
        parts = [polygon] if polygon.geom_type == "Polygon" else [
            part for part in getattr(polygon, "geoms", [])
            if part.geom_type == "Polygon" and not part.is_empty
        ]
        for part in parts:
            result.append((name, part))
    return result


def _rows(result, zones):
    rows = []
    for zone, zone_result in zip(zones, result.zones):
        for row in zone_result.rows:
            if row.area > 1e-9:
                rows.append({
                    "zone": zone.name,
                    "unit": row.unit_name,
                    "area": row.area,
                })
    return rows


def _serialize_paths(route_paths, bases, colors):
    paths = []
    for path in route_paths:
        if path.unit_name not in colors:
            colors[path.unit_name] = COLORS[len(colors) % len(COLORS)]
        base = next((item for item in bases if item.name == path.base_name), None)
        transit = []
        if base and path.transit_out:
            transit.append([[point[0], point[1]] for point in path.transit_out])
        elif base and path.entry_point:
            transit.append([
                [base.lon, base.lat],
                [path.entry_point[0], path.entry_point[1]],
            ])
        if base and path.transit_back:
            transit.append([[point[0], point[1]] for point in path.transit_back])
        elif base and path.exit_point:
            transit.append([
                [path.exit_point[0], path.exit_point[1]],
                [base.lon, base.lat],
            ])
        paths.append({
            "unit": path.unit_name,
            "zone": path.zone_name,
            "color": colors[path.unit_name],
            "lines": [
                [[line.start[0], line.start[1]], [line.end[0], line.end[1]]]
                for line in path.lines
            ],
            "transfers": [
                [[point[0], point[1]] for point in segment]
                for segment in path.transfer_segments
            ],
            "transit": transit,
        })
    return paths


def plan_mission(payload):
    gsd_m = float(payload.get("resolution"))
    if gsd_m <= 0:
        raise ValueError("Разрешение должно быть больше нуля, в м/пиксель")
    bases = _bases_from_vpps(payload.get("vpps") or [])
    zones = _zones_from_polygons(payload.get("polygons") or [])
    forbidden = _forbidden_from_payload(payload.get("forbidden") or [])
    if not bases:
        raise ValueError("Нужна хотя бы одна ВПП")
    if not zones:
        raise ValueError("Нужен хотя бы один район съёмки")

    gsd_cm = gsd_cm_from_m(gsd_m)
    units = make_units(bases, zones)
    solver = MultiZoneSolver(gsd_cm, OVERLAP_X, step=0.5,
                             allow_partial_planes=True)
    assignment = solver.solve(units, zones, bases, use_local_opt=True)
    missing = [zone.name for zone, units_j in zip(zones, assignment) if not units_j]
    if missing:
        raise ValueError(
            "Не удалось покрыть: " + ", ".join(missing)
            + ". Нет камеры нужного типа или с ВПП не хватает запаса хода до района.")

    front = solver.build_front(assignment, zones, bases, max_combos=1000)
    if not front:
        raise ValueError("Pareto-фронт пуст")

    modes = []
    best_by_mode = {}
    for mode in ("time", "resource", "balanced"):
        best = Pareto.pick_best(front, mode=mode)
        best_by_mode[mode] = best
        modes.append({
            "id": mode,
            "title": MODE_TITLE[mode],
            "T": best.T,
            "R": best.R,
            "rows": _rows(best, zones),
        })

    save_assignment(best_by_mode["time"], zones, gsd_m, "assignment.json")
    colors = {}
    for mode in modes:
        rows = [(row["zone"], row["unit"], row["area"]) for row in mode["rows"]]
        mode["paths"] = _serialize_paths(
            build_route_paths(zones, bases, rows, gsd_cm, OVERLAP_X, forbidden),
            bases,
            colors,
        )
    return {"modes": modes}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == "/api/config":
            self._json({"resolution": 0.05})
            return
        if path == "/":
            path = "/index.html"
        file_path = (WEB_DIR / path.lstrip("/")).resolve()
        if not str(file_path).startswith(str(WEB_DIR.resolve())) or not file_path.is_file():
            self.send_error(404)
            return
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", _MIME.get(file_path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        path = unquote(urlparse(self.path).path)
        if path != "/api/solve":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
            result = plan_mission(payload)
        except Exception as error:
            traceback.print_exc()
            self._json({"error": str(error)}, status=400)
            return
        self._json(result)

    def _json(self, body, status=200):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        print(fmt % args)


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Карта: http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()

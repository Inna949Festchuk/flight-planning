"""Построение галсов и маршрутов с перебором угла."""

import heapq
import math
from dataclasses import dataclass, field
from shapely.geometry import Polygon, LineString, Point, MultiLineString, MultiPolygon
from shapely.affinity import rotate
from shapely.ops import transform, unary_union
from shapely.prepared import prep
from shapely.validation import make_valid
import pyproj


@dataclass
class Line:
    start: tuple
    end: tuple
    length_m: float
    index: int = 0
    direction: str = ""


@dataclass
class Path:
    unit_name: str
    zone_name: str
    base_name: str
    angle_deg: float
    entry_corner: str
    exit_corner: str
    altitude_m: float
    line_spacing_m: float
    speed_kmh: float
    lines: list = field(default_factory=list)
    total_length_m: float = 0.0
    total_time_h: float = 0.0
    n_lines: int = 0
    area_km2: float = 0.0
    entry_point: tuple = None
    exit_point: tuple = None
    transfer_time_h: float = 0.0
    transfer_segments: list = field(default_factory=list)
    transit_out: list = None
    transit_back: list = None


class ForbiddenRouter:
    """Обход запретных зон: галсы снаружи буфера, перелёты по графу видимости."""

    MARGIN_M = 15.0

    def __init__(self, obstacles):
        self.obstacles = []
        for name, poly in obstacles or []:
            if poly is None or poly.is_empty:
                continue
            if not poly.is_valid:
                poly = make_valid(poly)
            if poly.geom_type == "Polygon":
                self.obstacles.append((name, poly))
            elif poly.geom_type == "MultiPolygon":
                for part in poly.geoms:
                    self.obstacles.append((name, part))
            elif poly.geom_type == "GeometryCollection":
                for part in poly.geoms:
                    if part.geom_type == "Polygon" and not part.is_empty:
                        self.obstacles.append((name, part))
        self._ready = False
        self._cache = {}

    def assert_outside(self, base):
        point = Point(base.lon, base.lat)
        for name, poly in self.obstacles:
            if poly.intersects(point):
                raise ValueError(
                    f"ВПП {base.name} находится в запретной зоне «{name}»"
                )

    def clip(self, polygon, zone_name):
        """Район без запретных зон и без полосы в несколько метров вокруг них."""
        self._ensure(polygon.centroid.x, polygon.centroid.y)
        zone_utm = self._project(polygon, self._to_utm)
        if not zone_utm.is_valid:
            zone_utm = make_valid(zone_utm)
        flyable = zone_utm.difference(self._buffer)
        flyable = _polygonal(flyable)
        if flyable.is_empty or flyable.area < 1:
            names = _unique(name for name, poly in self.obstacles if polygon.intersects(poly))
            if names:
                raise ValueError(
                    f"Район {zone_name} полностью закрыт запретными зонами: "
                    + ", ".join(f"«{name}»" for name in names)
                )
            return polygon
        return self._project(flyable, self._to_wgs)

    def route(self, start, end, context):
        """Ломаная (lon, lat) снаружи запретов. start/end — (lon, lat)."""
        if not self.obstacles:
            return [start, end]
        anchor = start if self._ready else end
        self._ensure(anchor[0], anchor[1])
        key = (
            round(start[0], 6), round(start[1], 6),
            round(end[0], 6), round(end[1], 6),
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        start_xy = self._xy(start)
        end_xy = self._xy(end)
        straight = LineString([start_xy, end_xy])
        if not self._original_prep.intersects(straight):
            self._cache[key] = [start, end]
            return [start, end]
        self._raise_if_inside(start_xy, context)
        self._raise_if_inside(end_xy, context)
        path_xy = self._detour(start_xy, end_xy)
        if path_xy is None:
            names = _unique(
                name for name, poly in self._named_utm
                if poly.intersects(straight)
            )
            listed = ", ".join(f"«{name}»" for name in names) or "запретную зону"
            raise ValueError(f"Не удалось обойти запретную зону {listed}: {context}")
        path = [self._lonlat(point) for point in path_xy]
        path = _dedupe_points(path)
        self._cache[key] = path
        return path

    def _ensure(self, lon, lat):
        if self._ready or not self.obstacles:
            return
        zone_num = int((lon + 180) / 6) + 1
        epsg = 32600 + zone_num if lat >= 0 else 32700 + zone_num
        utm = pyproj.CRS(f"EPSG:{epsg}")
        self._to_utm = pyproj.Transformer.from_crs(
            "EPSG:4326", utm, always_xy=True).transform
        self._to_wgs = pyproj.Transformer.from_crs(
            utm, "EPSG:4326", always_xy=True).transform
        named = []
        for name, poly in self.obstacles:
            projected = self._project(poly, self._to_utm)
            if not projected.is_valid:
                projected = make_valid(projected)
            named.append((name, projected))
        self._named_utm = named
        original = unary_union([poly for _, poly in named])
        if not original.is_valid:
            original = make_valid(original)
        self._buffer = original.buffer(self.MARGIN_M)
        if not self._buffer.is_valid:
            self._buffer = make_valid(self._buffer)
        interior = self._buffer.buffer(-0.5)
        if interior.is_empty:
            interior = original
        self._original_prep = prep(original)
        self._interior_prep = prep(interior)
        self._nodes = []
        seen = set()
        parts = [self._buffer] if self._buffer.geom_type == "Polygon" else [
            part for part in getattr(self._buffer, "geoms", [])
            if part.geom_type == "Polygon"
        ]
        for part in parts:
            for x, y in list(part.exterior.coords)[:-1]:
                key = (round(x, 2), round(y, 2))
                if key in seen:
                    continue
                seen.add(key)
                self._nodes.append(key)
        count = len(self._nodes)
        self._adj = [[] for _ in range(count)]
        for i in range(count):
            for j in range(i + 1, count):
                if not self._free(self._nodes[i], self._nodes[j]):
                    continue
                weight = math.hypot(
                    self._nodes[i][0] - self._nodes[j][0],
                    self._nodes[i][1] - self._nodes[j][1],
                )
                self._adj[i].append((j, weight))
                self._adj[j].append((i, weight))
        self._ready = True

    def _project(self, geom, transform_fn):
        return transform(transform_fn, geom)

    def _xy(self, lonlat):
        x, y = self._to_utm(lonlat[0], lonlat[1])
        return (x, y)

    def _lonlat(self, xy):
        lon, lat = self._to_wgs(xy[0], xy[1])
        return (lon, lat)

    def _free(self, a, b):
        if math.hypot(a[0] - b[0], a[1] - b[1]) < 0.05:
            return False
        return not self._interior_prep.intersects(LineString([a, b]))

    def _raise_if_inside(self, xy, context):
        point = Point(xy)
        for name, poly in self._named_utm:
            if poly.intersects(point):
                raise ValueError(
                    f"{context}: точка внутри запретной зоны «{name}»"
                )

    def _escape(self, xy):
        point = Point(xy)
        if not self._buffer.covers(point):
            return xy
        boundary = self._buffer.boundary
        nearest = boundary.interpolate(boundary.project(point))
        return (nearest.x, nearest.y)

    def _near_node(self, xy):
        for index, node in enumerate(self._nodes):
            if math.hypot(node[0] - xy[0], node[1] - xy[1]) < 0.3:
                return index
        return None

    def _detour(self, start_xy, end_xy):
        start = self._escape(start_xy)
        end = self._escape(end_xy)
        nodes = self._nodes
        if not nodes:
            return None
        if not self._original_prep.intersects(LineString([start, end])):
            return _dedupe_xy([start_xy, start, end, end_xy])

        count = len(nodes)
        start_id = self._near_node(start)
        end_id = self._near_node(end)
        virtual_start = count
        dist = [float("inf")] * (count + 1)
        prev = [None] * (count + 1)
        if start_id is None:
            dist[virtual_start] = 0.0
            heap = [(0.0, virtual_start)]
            start_links = [
                (index, math.hypot(start[0] - node[0], start[1] - node[1]))
                for index, node in enumerate(nodes)
                if self._free(start, node)
            ]
        else:
            dist[start_id] = 0.0
            heap = [(0.0, start_id)]
            start_links = []
        end_links = {}
        if end_id is None:
            for index, node in enumerate(nodes):
                if self._free(end, node):
                    end_links[index] = math.hypot(end[0] - node[0], end[1] - node[1])
        else:
            end_links[end_id] = 0.0

        best = float("inf")
        best_via = None
        while heap:
            weight, node_id = heapq.heappop(heap)
            if weight != dist[node_id]:
                continue
            if node_id != virtual_start and node_id in end_links:
                candidate = weight + end_links[node_id]
                if candidate < best:
                    best = candidate
                    best_via = node_id
            neighbors = start_links if node_id == virtual_start else self._adj[node_id]
            for nxt, step in neighbors:
                proposed = weight + step
                if proposed < dist[nxt]:
                    dist[nxt] = proposed
                    prev[nxt] = node_id
                    heapq.heappush(heap, (proposed, nxt))
        if best_via is None:
            return None
        chain = []
        cursor = best_via
        while cursor is not None and cursor != virtual_start:
            chain.append(nodes[cursor])
            cursor = prev[cursor]
        chain.reverse()
        return _dedupe_xy([start_xy, start, *chain, end, end_xy])


def _polygonal(geom):
    if geom is None or geom.is_empty:
        return Polygon()
    if geom.geom_type == "Polygon":
        return geom if geom.area >= 1 else Polygon()
    if geom.geom_type == "MultiPolygon":
        parts = [part for part in geom.geoms if part.area >= 1]
        if not parts:
            return Polygon()
        return parts[0] if len(parts) == 1 else MultiPolygon(parts)
    parts = [
        part for part in getattr(geom, "geoms", [])
        if part.geom_type == "Polygon" and part.area >= 1
    ]
    if not parts:
        return Polygon()
    return parts[0] if len(parts) == 1 else MultiPolygon(parts)


def _unique(names):
    result = []
    for name in names:
        if name not in result:
            result.append(name)
    return result


def _dedupe_points(points):
    result = []
    for point in points:
        if result and abs(result[-1][0] - point[0]) < 1e-9 and abs(result[-1][1] - point[1]) < 1e-9:
            continue
        result.append(point)
    return result


def _dedupe_xy(points):
    result = []
    for point in points:
        if result and math.hypot(result[-1][0] - point[0], result[-1][1] - point[1]) < 0.05:
            continue
        result.append(point)
    return result


class PathBuilder:

    CORNERS = ["NW", "NE", "SW", "SE"]

    def __init__(self, line_spacing_m, speed_kmh,
                 angle_step=5, turn_time_s=0, router=None, route_label=""):
        self.line_spacing_m = line_spacing_m
        self.speed_kmh = speed_kmh
        self.angle_step = angle_step
        self.turn_time_s = turn_time_s
        self.router = router
        self.route_label = route_label

    def _utm_crs(self, polygon_wgs84):
        c = polygon_wgs84.centroid
        zone_num = int((c.x + 180) / 6) + 1
        epsg = 32600 + zone_num if c.y >= 0 else 32700 + zone_num
        return pyproj.CRS(f"EPSG:{epsg}")

    def _to_utm(self, polygon_wgs84):
        utm = self._utm_crs(polygon_wgs84)
        proj = pyproj.Transformer.from_crs("EPSG:4326", utm, always_xy=True)
        return transform(proj.transform, polygon_wgs84), utm

    def _to_wgs(self, geom_utm, utm):
        proj = pyproj.Transformer.from_crs(utm, "EPSG:4326", always_xy=True)
        return transform(proj.transform, geom_utm)

    def build_lines(self, polygon_wgs84, angle_deg):
        poly_utm, utm = self._to_utm(polygon_wgs84)
        rotated = rotate(poly_utm, -angle_deg, origin='centroid')
        minx, miny, maxx, maxy = rotated.bounds

        lines_utm = []
        y = miny
        while y <= maxy + 1e-9:
            scan = LineString([(minx - 1000, y), (maxx + 1000, y)])
            inter = rotated.intersection(scan)
            if inter.is_empty:
                y += self.line_spacing_m
                continue
            for seg in self._extract_segments(inter):
                min_length = 1.0 if self.router else 1e-3
                if seg.length < min_length:
                    continue
                seg_rot = rotate(seg, angle_deg, origin=rotated.centroid)
                lines_utm.append(seg_rot)
            y += self.line_spacing_m

        result = []
        for seg in lines_utm:
            coords = list(seg.coords)
            s = self._to_wgs(Point(coords[0]), utm)
            e = self._to_wgs(Point(coords[-1]), utm)
            result.append(Line(
                start=(s.x, s.y),
                end=(e.x, e.y),
                length_m=seg.length,
            ))
        return result

    def _extract_segments(self, geom):
        if geom.is_empty:
            return []
        if isinstance(geom, LineString):
            return [geom]
        if isinstance(geom, MultiLineString):
            return list(geom.geoms)
        if hasattr(geom, "geoms"):
            segs = []
            for g in geom.geoms:
                segs.extend(self._extract_segments(g))
            return segs
        return []

    def _snake_order(self, lines, entry_corner, angle_deg=0):
        if not lines:
            return []

        theta = math.radians(angle_deg)
        nx = -math.sin(theta)
        ny = math.cos(theta)
        ax = math.cos(theta)
        ay = math.sin(theta)

        def perp_key(l):
            cx = (l.start[0] + l.end[0]) / 2
            cy = (l.start[1] + l.end[1]) / 2
            perp = cx * nx + cy * ny
            along = cx * ax + cy * ay
            return (round(perp, 5), round(along, 5))

        sorted_lines = sorted(lines, key=perp_key)

        if entry_corner not in ("NW", "NE"):
            sorted_lines = list(reversed(sorted_lines))

        start_left = entry_corner in ("NW", "SW")

        result = []
        for i, l in enumerate(sorted_lines):
            if (i % 2 == 0 and start_left) or (i % 2 == 1 and not start_left):
                result.append(l)
            else:
                result.append(Line(start=l.end, end=l.start, length_m=l.length_m))
        return result

    def _direction_label(self, line):
        dx = line.end[0] - line.start[0]
        dy = line.end[1] - line.start[1]
        if abs(dx) >= abs(dy):
            return "→" if dx > 0 else "←"
        else:
            return "↑" if dy > 0 else "↓"

    def _haversine_km(self, lat1, lon1, lat2, lon2):
        R = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlon / 2) ** 2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def evaluate(self, lines, entry_corner, base, area_km2,
                 already_sorted=False, angle_deg=0):
        if not lines:
            return None

        if already_sorted:
            sorted_lines = list(lines)
        else:
            sorted_lines = self._snake_order(lines, entry_corner, angle_deg)

        for i, l in enumerate(sorted_lines):
            l.index = i + 1
            l.direction = self._direction_label(l)

        total_length_m = sum(l.length_m for l in sorted_lines)

        transfer_segments = []
        detour_km = 0.0
        for i in range(len(sorted_lines) - 1):
            end_i = sorted_lines[i].end
            start_next = sorted_lines[i + 1].start
            if self.router:
                polyline = self.router.route(
                    end_i, start_next,
                    f"на перегоне {self.route_label}",
                )
            else:
                polyline = [end_i, start_next]
            transfer_segments.append(polyline)
            if len(polyline) > 2:
                detour_km += self._polyline_km(polyline)

        entry_point = sorted_lines[0].start
        exit_point = sorted_lines[-1].end

        d1 = self._haversine_km(base.lat, base.lon,
                                entry_point[1], entry_point[0])
        d2 = self._haversine_km(exit_point[1], exit_point[0],
                                base.lat, base.lon)
        transit_out = None
        transit_back = None
        if self.router:
            transit_out = self.router.route(
                (base.lon, base.lat), entry_point, self.route_label)
            transit_back = self.router.route(
                exit_point, (base.lon, base.lat), self.route_label)
            if len(transit_out) > 2:
                d1 = self._polyline_km(transit_out)
            if len(transit_back) > 2:
                d2 = self._polyline_km(transit_back)
        transfer_h = (d1 + d2) / self.speed_kmh

        lines_h = total_length_m / 1000 / self.speed_kmh
        total_h = transfer_h + lines_h + detour_km / self.speed_kmh
        if detour_km > 0 or (transit_out and len(transit_out) > 2) or (transit_back and len(transit_back) > 2):
            total_length_m += detour_km * 1000
            if transit_out and len(transit_out) > 2:
                total_length_m += self._polyline_km(transit_out) * 1000
            if transit_back and len(transit_back) > 2:
                total_length_m += self._polyline_km(transit_back) * 1000

        return Path(
            unit_name="",
            zone_name="",
            base_name=base.name,
            angle_deg=angle_deg,
            entry_corner=entry_corner,
            exit_corner=entry_corner,
            altitude_m=0,
            line_spacing_m=self.line_spacing_m,
            speed_kmh=self.speed_kmh,
            lines=sorted_lines,
            total_length_m=total_length_m,
            total_time_h=total_h,
            n_lines=len(sorted_lines),
            area_km2=area_km2,
            entry_point=entry_point,
            exit_point=exit_point,
            transfer_time_h=transfer_h,
            transfer_segments=transfer_segments,
            transit_out=transit_out,
            transit_back=transit_back,
        )

    def _polyline_km(self, points):
        total = 0.0
        for index in range(len(points) - 1):
            lon1, lat1 = points[index]
            lon2, lat2 = points[index + 1]
            total += self._haversine_km(lat1, lon1, lat2, lon2)
        return total

    def best_for_zone(self, polygon_wgs84, base, area_km2):
        best_path = None
        best_time = None
        route_error = None

        for angle in range(0, 180, self.angle_step):
            lines = self.build_lines(polygon_wgs84, angle)
            if not lines:
                continue
            for entry in self.CORNERS:
                try:
                    p = self.evaluate(lines, entry, base, area_km2,
                                      angle_deg=angle)
                except ValueError as error:
                    route_error = error
                    continue
                if p is None:
                    continue
                if best_time is None or p.total_time_h < best_time:
                    best_time = p.total_time_h
                    best_path = p
        if best_path is None and route_error is not None:
            raise route_error
        return best_path
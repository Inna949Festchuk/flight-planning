"""Загрузка зон из GeoJSON."""

import json
import math
from models import Zone


def _spherical_area_m2(coords):
    R = 6371000
    area = 0.0
    n = len(coords)
    for i in range(n):
        x1, y1 = coords[i]
        x2, y2 = coords[(i + 1) % n]
        area += math.radians(x2 - x1) * (
            2 + math.sin(math.radians(y1)) + math.sin(math.radians(y2))
        )
    return abs(area * R * R / 2)


def _shapely_area_m2(coords):
    try:
        from shapely.geometry import Polygon
        from shapely.ops import transform
        import pyproj
    except ImportError:
        return None
    geom = Polygon(coords)
    c = geom.centroid
    zone_num = int((c.x + 180) / 6) + 1
    epsg = 32600 + zone_num if c.y >= 0 else 32700 + zone_num
    utm = pyproj.CRS(f"EPSG:{epsg}")
    proj = pyproj.Transformer.from_crs("EPSG:4326", utm, always_xy=True).transform
    return transform(proj, geom).area


def _centroid(coords):
    """Центроид полигона (lat, lon)."""
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return sum(lats) / len(lats), sum(lons) / len(lons)


def polygon_area_km2(coords):
    a = _shapely_area_m2(coords)
    if a is None:
        a = _spherical_area_m2(coords)
    return a / 1e6


class GeoJSONLoader:
    def load(self, filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return self._parse(data)

    def _parse(self, data):
        zones = []
        if data.get("type") == "FeatureCollection":
            for i, feat in enumerate(data.get("features", [])):
                z = self._parse_feature(feat, i)
                if z:
                    zones.append(z)
        elif data.get("type") == "Feature":
            z = self._parse_feature(data, 0)
            if z:
                zones.append(z)
        return zones

    def _parse_feature(self, feat, idx):
        geom = feat.get("geometry", {})
        if geom.get("type") != "Polygon":
            return None
        coords = geom["coordinates"][0]
        props = feat.get("properties", {})
        name = props.get("name", f"Z_{idx+1}")
        priority = float(props.get("priority", 1.0))
        survey_type = props.get("survey_type", "visible")
        if survey_type not in ("visible", "multispectral", "thermal"):
            survey_type = "visible"
        area = polygon_area_km2(coords)
        lat, lon = _centroid(coords)
        return Zone(name=name, area=area, lat=lat, lon=lon,
                    priority=priority, survey_type=survey_type)
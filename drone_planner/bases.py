"""Загрузка точек взлёта/посадки."""

import json
import math
from models import Base


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class BaseLoader:
    def load(self, filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return self._parse(data)

    def _parse(self, data):
        bases = []
        if data.get("type") == "FeatureCollection":
            for i, feat in enumerate(data.get("features", [])):
                b = self._parse_feature(feat, i)
                if b:
                    bases.append(b)
        elif data.get("type") == "Feature":
            b = self._parse_feature(data, 0)
            if b:
                bases.append(b)
        return bases

    def _parse_feature(self, feat, idx):
        geom = feat.get("geometry", {})
        if geom.get("type") != "Point":
            return None
        lon, lat = geom["coordinates"]
        props = feat.get("properties", {})
        name = props.get("name", f"B_{idx+1}")
        return Base(name=name, lat=lat, lon=lon)
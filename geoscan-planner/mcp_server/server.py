"""FastMCP-сервер GeoScan Planner.

Инструменты дублируют инструментарий приложения (тот же набор, что в
function calling) и вызывают REST API backend через httpx с внутренним
токеном (заголовок X-Internal-Token).

Запуск: python server.py  (transport: streamable-http, порт 8001)
"""

import os

import httpx
from fastmcp import FastMCP

BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000")
INTERNAL_TOKEN = os.environ.get("INTERNAL_API_TOKEN", "geoscan-internal-mcp-token")

mcp = FastMCP(
    "geoscan-planner",
    instructions=(
        "GeoScan Planner: планирование и распределение беспилотных авиационных работ. "
        "MILP-оптимизация с двумя критериями (мин. время / мин. суммарный налёт). "
        "Все координаты — WGS84 (EPSG:4326). "
        "Типы съёмки: visible, thermal, multispectral."
    ),
)


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=BACKEND_URL,
        timeout=120,
        headers={"X-Internal-Token": INTERNAL_TOKEN},
    )


@mcp.tool()
def get_project_context(project_id: int) -> dict:
    """Контекст проекта: зоны съёмки, запретные зоны, ВПП, парк БВС."""
    with _client() as c:
        r = c.get(f"/api/projects/{project_id}/")
        r.raise_for_status()
        return r.json()


@mcp.tool()
def list_uavs(active_uav_ids: list[int] | None = None) -> dict:
    """Парк БВС: модель, время полёта, скорость, батарея, ПН, предел по ветру."""
    params = {"active_ids": ",".join(str(i) for i in active_uav_ids)} if active_uav_ids else {}
    with _client() as c:
        r = c.get("/api/fleet/", params=params)
        r.raise_for_status()
        return r.json()


@mcp.tool()
def list_zones(project_id: int) -> dict:
    """Зоны проекта: название, тип (съёмка/запрет), тип съёмки, площадь."""
    with _client() as c:
        r = c.get(f"/api/projects/{project_id}/data/")
        r.raise_for_status()
        data = r.json()
        return {
            "zones": data.get("zones", []),
            "vpps": data.get("vpps", []),
        }


@mcp.tool()
def load_demo_data(project_id: int) -> dict:
    """Загружает демо-сценарий (6 зон, 2 запрета, 6 ВПП) в проект."""
    with _client() as c:
        r = c.post(f"/api/projects/{project_id}/load_demo/")
        r.raise_for_status()
        return r.json()


@mcp.tool()
def start_planning(
    project_id: int,
    gsd: float,
    wind_kmh: float = 0,
    survey_types: list[str] | None = None,
    active_uav_ids: list[int] | None = None,
) -> dict:
    """Запускает MILP-расчёт миссии (Celery). Возвращает id миссии; результат — через get_planning_result."""
    body = {"gsd": gsd, "wind_kmh": wind_kmh}
    if survey_types:
        body["survey_types"] = survey_types
    if active_uav_ids:
        body["active_uav_ids"] = active_uav_ids
    with _client() as c:
        r = c.post(f"/api/projects/{project_id}/missions/", json=body)
        r.raise_for_status()
        return r.json()


@mcp.tool()
def get_planning_result(mission_id: int) -> dict:
    """Статус и результат миссии (3 варианта: recommended/time/resource, назначения, метрики)."""
    with _client() as c:
        r = c.get(f"/api/missions/{mission_id}/")
        r.raise_for_status()
        return r.json()


@mcp.tool()
def export_plan(mission_id: int) -> dict:
    """Экспорт полётного задания в GeoJSON (маршруты, ВПП, сводка)."""
    with _client() as c:
        r = c.get(f"/api/missions/{mission_id}/export/")
        r.raise_for_status()
        return r.json()


@mcp.tool()
def get_map_data(mission_id: int) -> dict:
    """GeoJSON маршрутов для отображения на карте (то же, что export_plan)."""
    return export_plan(mission_id)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8001)

import json

from django.conf import settings
from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from geo_processing import export, planning
from .models import Mission, Project, SurveyZone, VPP
from .serializers import LoadDataSerializer, MissionCreateSerializer, ProjectCreateSerializer
from .serializers_geo import MissionSerializer, SurveyZoneSerializer, VPPSerializer


def _fc_to_zones(fc: dict, project, kind: str) -> int:
    """Разбирает GeoJSON FeatureCollection и создаёт зоны проекта."""
    created = 0
    from geo_processing.gals import M_PER_DEG_LAT, m_per_deg_lon

    for f in fc.get("features", []):
        geom = f.get("geometry") or {}
        props = f.get("properties") or {}
        name = props.get("name") or f"Зона {created + 1}"
        kind_val = props.get("kind", kind)
        survey_type = props.get("survey_type")
        if kind_val == "survey" and survey_type not in ("visible", "thermal", "multispectral"):
            survey_type = "visible"

        gtype = geom.get("type")
        coords = geom.get("coordinates")
        if gtype == "Polygon":
            polys = [coords]  # coords = [внешнее кольцо, отверстия...]
        elif gtype == "MultiPolygon":
            polys = coords  # [[кольца полигона 1...], [кольца полигона 2...]]
        else:
            continue
        mp = MultiPolygon([Polygon(p[0], *p[1:]) for p in polys])
        min_x, min_y, max_x, max_y = mp.envelope.extent
        lat0 = (min_y + max_y) / 2
        area_ha = round(mp.area * M_PER_DEG_LAT * m_per_deg_lon(lat0) / 10_000.0, 2)
        SurveyZone.objects.create(
            project=project, name=name, kind=kind_val,
            survey_type=survey_type if kind_val == "survey" else None,
            geom=mp, area_ha=area_ha,
        )
        created += 1
    return created


def _fc_to_vpps(fc: dict, project) -> int:
    created = 0
    for f in fc.get("features", []):
        geom = f.get("geometry") or {}
        props = f.get("properties") or {}
        if geom.get("type") != "Point":
            continue
        lon, lat = geom["coordinates"][0], geom["coordinates"][1]
        name = props.get("name") or f"ВПП {created + 1}"
        VPP.objects.create(project=project, name=name, geom=Point(lon, lat))
        created += 1
    return created


def _project_to_dicts(project: Project) -> tuple[list[dict], list[dict], list[dict]]:
    survey_zones, forbidden, vpps = [], [], []
    for z in project.zones.all():
        rings = _rings_of(z.geom)
        item = {"name": z.name, "survey_type": z.survey_type, "rings": rings}
        if z.kind == SurveyZone.KIND_FORBIDDEN:
            forbidden.append(item)
        else:
            survey_zones.append(item)
    for v in project.vpps.all():
        vpps.append({"name": v.name, "lon": float(v.geom.x), "lat": float(v.geom.y)})
    return survey_zones, forbidden, vpps


def _rings_of(geom) -> list[list[list[float]]]:
    """GEOS-геометрия → [полигон...]; полигон = [внешнее кольцо, отверстия...].

    Выход через WKT + shapely (стабильный API, не зависит от версии django.contrib.gis).
    """
    from shapely import get_parts, wkt as shapely_wkt

    shp = shapely_wkt.loads(geom.wkt)
    polys = [shp] if shp.geom_type == "Polygon" else list(get_parts(shp))
    out = []
    for poly in polys:
        rings = [list(poly.exterior.coords)]
        rings.extend(list(hole.coords) for hole in poly.interiors)
        out.append(rings)
    return out


class ProjectViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.all()
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        return Project.objects.filter(created_by=self.request.user)

    def create(self, request, *args, **kwargs):
        ser = ProjectCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        project = Project.objects.create(name=ser.validated_data["name"], created_by=request.user)
        return Response({"id": project.id, "name": project.name}, status=status.HTTP_201_CREATED)

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        data = [
            {"id": p.id, "name": p.name,
             "zone_count": p.zones.count(), "vpp_count": p.vpps.count(),
             "created_at": p.created_at.isoformat()}
            for p in qs
        ]
        return Response(data)

    def retrieve(self, request, pk=None):
        project = self.get_object()
        return Response({
            "id": project.id, "name": project.name,
            "zone_count": project.zones.count(), "vpp_count": project.vpps.count(),
            "created_at": project.created_at.isoformat(),
        })

    @action(detail=True, methods=["post"])
    def load_demo(self, request, pk=None):
        """Загружает встроенный демо-сценарий (polygons.geojson + vpp.geojson)."""
        project = self.get_object()
        project.zones.all().delete()
        project.vpps.all().delete()
        data_dir = settings.DATA_DIR
        with open(data_dir / "polygons.geojson", encoding="utf-8") as f:
            zones_fc = json.load(f)
        with open(data_dir / "vpp.geojson", encoding="utf-8") as f:
            vpps_fc = json.load(f)
        n_zones = _fc_to_zones(zones_fc, project, "survey")
        n_vpps = _fc_to_vpps(vpps_fc, project)
        return Response({"zones": n_zones, "vpps": n_vpps}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], serializer_class=LoadDataSerializer)
    def load_data(self, request, pk=None):
        """Загружает собственные зоны/ВПП из GeoJSON FeatureCollection."""
        project = self.get_object()
        ser = LoadDataSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        project.zones.all().delete()
        project.vpps.all().delete()
        n_zones = _fc_to_zones(ser.validated_data["zones"], project, "survey")
        n_vpps = _fc_to_vpps(ser.validated_data["vpps"], project)
        return Response({"zones": n_zones, "vpps": n_vpps}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def data(self, request, pk=None):
        """Текущие зоны и ВПП проекта (для карты)."""
        project = self.get_object()
        zones = SurveyZoneSerializer(project.zones.all(), many=True).data
        vpps = VPPSerializer(project.vpps.all(), many=True).data
        return Response({"zones": zones, "vpps": vpps})

    @action(detail=True, methods=["get"])
    def fleet(self, request, pk=None):
        """Парк БВС (демо-флот из ТТХ)."""
        active = request.query_params.get("active_ids")
        ids = [int(x) for x in active.split(",") if x.strip().isdigit()] if active else None
        return Response(planning.get_fleet(ids))


class MissionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Mission.objects.all()
    serializer_class = MissionSerializer
    http_method_names = ["get", "head", "options"]

    def get_queryset(self):
        return Mission.objects.filter(project__created_by=self.request.user)

    @action(detail=True, methods=["get"], url_path="export")
    def export(self, request, pk=None):
        """Экспорт полётного задания в GeoJSON."""
        mission = self.get_object()
        if mission.status != Mission.STATUS_SUCCESS or not mission.result:
            return Response({"detail": "Нет успешного результата для экспорта"}, status=409)
        vpps = [
            {"name": v.name, "lon": float(v.geom.x), "lat": float(v.geom.y)}
            for v in mission.project.vpps.all()
        ]
        fc = export.build_flight_task_geojson(mission.result, vpps)
        return Response(fc)


class FleetListView(APIView):
    """GET /api/fleet/ — демо-флот БВС (из ТТХ, не зависит от проекта)."""

    def get(self, request):
        active = request.query_params.get("active_ids")
        ids = [int(x) for x in active.split(",") if x.strip().isdigit()] if active else None
        return Response(planning.get_fleet(ids))


class ChatView(APIView):
    def post(self, request):
        from geo_processing.chat_handler import handle_chat_message

        message = (request.data.get("message") or "").strip()
        if not message:
            return Response({"detail": "Пустое сообщение"}, status=400)
        history = request.data.get("history") or []
        project_id = request.data.get("project_id")
        result = handle_chat_message(message, history, project_id, user=request.user)
        return Response(result)


class MissionCreateView(APIView):
    """POST /api/projects/{id}/missions/ — запуск расчёта (Celery)."""

    def post(self, request, pk=None):
        from .tasks import run_planning_task

        try:
            project = Project.objects.get(pk=pk, created_by=request.user)
        except Project.DoesNotExist:
            return Response({"detail": "Проект не найден"}, status=404)
        ser = MissionCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        if project.zones.filter(kind=SurveyZone.KIND_SURVEY).count() == 0:
            return Response({"detail": "В проекте нет зон съёмки"}, status=400)
        if project.vpps.count() == 0:
            return Response({"detail": "В проекте нет площадок ВПП"}, status=400)

        mission = Mission.objects.create(
            project=project, created_by=request.user,
            gsd=ser.validated_data["gsd"],
            side_overlap=ser.validated_data["side_overlap"],
            front_overlap=ser.validated_data["front_overlap"],
            wind_kmh=ser.validated_data["wind_kmh"],
            active_uav_ids=ser.validated_data.get("active_uav_ids") or [],
            survey_types=ser.validated_data.get("survey_types") or [],
        )
        run_planning_task.delay(mission.id)
        return Response({"id": mission.id, "status": mission.status}, status=status.HTTP_202_ACCEPTED)

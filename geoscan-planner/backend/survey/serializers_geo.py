from django.contrib.gis.geos import GEOSGeometry
from rest_framework import serializers
from rest_framework_gis.serializers import GeoFeatureModelSerializer

from .models import Mission, Project, SurveyZone, VPP


class ProjectSerializer(serializers.ModelSerializer):
    zone_count = serializers.IntegerField(source="zones.count", read_only=True)
    vpp_count = serializers.IntegerField(source="vpps.count", read_only=True)

    class Meta:
        model = Project
        fields = ["id", "name", "zone_count", "vpp_count", "created_at"]


class SurveyZoneSerializer(GeoFeatureModelSerializer):
    class Meta:
        model = SurveyZone
        geo_field = "geom"
        fields = ["id", "name", "kind", "survey_type", "area_ha"]


class VPPSerializer(GeoFeatureModelSerializer):
    class Meta:
        model = VPP
        geo_field = "geom"
        fields = ["id", "name"]


class MissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Mission
        fields = ["id", "status", "created_at", "gsd", "wind_kmh", "result"]

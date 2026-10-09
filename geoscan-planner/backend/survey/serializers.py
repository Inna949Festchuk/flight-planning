from rest_framework import serializers


class ProjectCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)


class LoadDataSerializer(serializers.Serializer):
    zones = serializers.JSONField(help_text="GeoJSON FeatureCollection зон (Polygon/MultiPolygon)")
    vpps = serializers.JSONField(help_text="GeoJSON FeatureCollection площадок (Point)")


class MissionCreateSerializer(serializers.Serializer):
    gsd = serializers.FloatField(help_text="Целевое разрешение, м/пиксель", min_value=0.1, max_value=100)
    wind_kmh = serializers.FloatField(help_text="Скорость ветра, км/ч", min_value=0, max_value=100, default=0)
    side_overlap = serializers.FloatField(help_text="Боковое перекрытие галсов (0..0.9)", min_value=0.0, max_value=0.9, default=0.5)
    front_overlap = serializers.FloatField(help_text="Продольное перекрытие (0..0.9)", min_value=0.0, max_value=0.9, default=0.6)
    active_uav_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_null=True, required=False,
        help_text="Идентификаторы БВС, участвующих в расчёте (null/пусто — весь парк)",
    )
    survey_types = serializers.ListField(
        child=serializers.ChoiceField(choices=["visible", "thermal", "multispectral"]),
        allow_null=True, required=False,
        help_text="Типы съёмки, включаемые в задачу (null/пусто — все зоны)",
    )

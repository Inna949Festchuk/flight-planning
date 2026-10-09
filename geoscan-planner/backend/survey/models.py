"""Модели предметной области GeoScan Planner."""

from django.conf import settings
from django.contrib.gis.db import models


class Project(models.Model):
    name = models.CharField("название", max_length=200)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="projects")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Проект"
        verbose_name_plural = "Проекты"

    def __str__(self):
        return self.name


class SurveyZone(models.Model):
    KIND_SURVEY = "survey"
    KIND_FORBIDDEN = "forbidden"
    KIND_CHOICES = [(KIND_SURVEY, "Зона съёмки"), (KIND_FORBIDDEN, "Запретная зона")]

    TYPE_VISIBLE = "visible"
    TYPE_THERMAL = "thermal"
    TYPE_MULTISPECTRAL = "multispectral"
    TYPE_CHOICES = [
        (TYPE_VISIBLE, "Видимый диапазон"),
        (TYPE_THERMAL, "Тепловизионный"),
        (TYPE_MULTISPECTRAL, "Мультиспектральный"),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="zones")
    name = models.CharField("название", max_length=200)
    kind = models.CharField("вид", max_length=16, choices=KIND_CHOICES, default=KIND_SURVEY)
    survey_type = models.CharField("тип съёмки", max_length=16, choices=TYPE_CHOICES, null=True, blank=True)
    geom = models.MultiPolygonField("геометрия", srid=4326)
    area_ha = models.FloatField("площадь, га", null=True, blank=True)

    class Meta:
        verbose_name = "Зона"
        verbose_name_plural = "Зоны"

    def __str__(self):
        return f"{self.name} ({self.kind})"


class VPP(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="vpps")
    name = models.CharField("название", max_length=200)
    geom = models.PointField("координаты", srid=4326)

    class Meta:
        verbose_name = "ВПП"
        verbose_name_plural = "ВПП"

    def __str__(self):
        return self.name


class Mission(models.Model):
    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_SUCCESS = "success"
    STATUS_INFEASIBLE = "infeasible"
    STATUS_ERROR = "error"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Ожидает"),
        (STATUS_RUNNING, "Вычисляется"),
        (STATUS_SUCCESS, "Выполнено"),
        (STATUS_INFEASIBLE, "Невыполнимо"),
        (STATUS_ERROR, "Ошибка"),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="missions")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    gsd = models.FloatField("целевой GSD, м/пикс")
    side_overlap = models.FloatField("боковое перекрытие", default=0.5)
    front_overlap = models.FloatField("продольное перекрытие", default=0.6)
    wind_kmh = models.FloatField("ветер, км/ч", default=0)
    active_uav_ids = models.JSONField("активные БВС", default=list)
    survey_types = models.JSONField("типы съёмки", default=list)
    status = models.CharField("статус", max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    result = models.JSONField("результат", null=True, blank=True)

    class Meta:
        verbose_name = "Миссия"
        verbose_name_plural = "Миссии"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Миссия {self.pk} ({self.status})"

from django.contrib import admin

from .models import Mission, Project, SurveyZone, VPP


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "created_by", "created_at")


@admin.register(SurveyZone)
class SurveyZoneAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "project", "kind", "survey_type", "area_ha")
    list_filter = ("kind", "survey_type")


@admin.register(VPP)
class VPPAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "project")


@admin.register(Mission)
class MissionAdmin(admin.ModelAdmin):
    list_display = ("id", "project", "status", "gsd", "wind_kmh", "created_at")
    list_filter = ("status",)

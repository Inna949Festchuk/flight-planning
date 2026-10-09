from celery import shared_task


@shared_task(bind=True, max_retries=1)
def run_planning_task(self, mission_id: int):
    """Выполняет MILP-расчёт миссии в Celery-воркере."""
    from geo_processing import planning

    from .models import Mission, SurveyZone

    mission = Mission.objects.get(id=mission_id)
    Mission.objects.filter(id=mission_id).update(status=Mission.STATUS_RUNNING)

    try:
        survey_zones, forbidden, vpps = _load_project_data(mission.project)
        result = planning.run_planning(
            survey_zones=survey_zones,
            forbidden_zones=forbidden,
            vpps=vpps,
            gsd=mission.gsd,
            wind_kmh=mission.wind_kmh,
            side_overlap=mission.side_overlap,
            front_overlap=mission.front_overlap,
            survey_types=mission.survey_types or None,
            active_uav_ids=mission.active_uav_ids or None,
        )
        if result["status"] == "success":
            Mission.objects.filter(id=mission_id).update(status=Mission.STATUS_SUCCESS, result=result)
        else:
            Mission.objects.filter(id=mission_id).update(
                status=Mission.STATUS_INFEASIBLE,
                result={"status": "infeasible", "reasons": result["reasons"]},
            )
    except Exception as exc:  # noqa: BLE001 — фиксируем любую ошибку в статусе миссии
        Mission.objects.filter(id=mission_id).update(
            status=Mission.STATUS_ERROR,
            result={"status": "error", "reasons": [f"Ошибка расчёта: {exc}"]},
        )
    return mission_id


def _load_project_data(project):
    from survey.views import _project_to_dicts

    return _project_to_dicts(project)

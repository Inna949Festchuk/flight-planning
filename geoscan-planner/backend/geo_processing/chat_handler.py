"""ИИ-агент GeoScan Planner: Qwen + function calling (OpenAI-совместимый API).

Инструменты дублируют инструментарий приложения: контекст проекта, парк БВС,
зоны, запуск расчёта, результат, объяснение, экспорт, данные для карты.
"""

from __future__ import annotations

import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — «СТРЕЛА», ИИ-ассистент сервиса планирования беспилотных авиационных работ.

Твоя задача — помогать оператору планировать авиационную съёмку:
- объяснять загруженные данные (зоны, ВПП, парк БВС);
- запускать расчёт миссии и интерпретировать результат;
- объяснять, почему назначены именно эти БВС (совместимость полезной нагрузки, батарея, запретные зоны);
- сравнивать три варианта плана (рекомендованный, лучший по времени, лучший по ресурсу).

Правила:
1. Для любых фактов о данных (зоны, БВС, результаты) используй инструменты, а не угадывай.
2. Перед запуском расчёта убедись, что в проекте есть зоны и ВПП (инструмент get_project_context).
3. Расчёт выполняется синхронно и быстро (MILP, до нескольких секунд).
4. Если расчёт невозможен — честно сообщи причину из reasons.
5. Отвечай на русском, кратко и по делу.
6. Метрики: total_time_min — время до посадки последнего БВС; total_flight_min — суммарный налёт.
7. Безопасный остаток батареи 20%: вылет должен укладываться в 80% паспортного времени полёта.

Форматирование (ответ рендерится как Markdown):
- Пиши ответы в формате Markdown: заголовки (##), маркированные/нумерованные списки, **жирный** для ключевых значений, таблицы для сравнения вариантов и списков объектов (БВС, зоны, вылеты).
- Таблица: заголовок с колонками через |, строка-разделитель после заголовка; не шире 4–5 колонок.
- Встроенный код (`gsd`, `mission_id` и т.п.) — в обратных кавычках; блоки кода ``` только при необходимости.
- Не используй HTML-теги, эмодзи-разметку и горизонтальные линии без надобности.
- Если ответ короткий (1–2 предложения) — без заголовков и таблиц.

Критерии оптимизации:
- "recommended" — баланс времени и ресурса (по умолчанию);
- "time" — минимальное общее время выполнения (makespan);
- "resource" — минимальный суммарный налёт всех БВС.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_project_context",
            "description": "Контекст проекта: зоны съёмки, запретные зоны, ВПП и доступный парк БВС. Вызывай первым, чтобы понять задачу.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "ID проекта"}
                },
                "required": ["project_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_uavs",
            "description": "Подробный список БВС парка: модель, время полёта, скорость, заряд батареи, полезная нагрузка, предел по ветру.",
            "parameters": {
                "type": "object",
                "properties": {
                    "active_uav_ids": {"type": "array", "items": {"type": "integer"}, "description": "Ограничить список ID (опционально)"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_zones",
            "description": "Список зон проекта: название, тип (съёмка/запрет), тип съёмки, площадь.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "ID проекта"}
                },
                "required": ["project_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_planning",
            "description": "Запускает MILP-расчёт миссии: распределяет зоны между БВС, строит маршруты и расписание. Возвращает сводку по трём вариантам.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "ID проекта"},
                    "gsd": {"type": "number", "description": "Целевое разрешение, м/пиксель (например 3)"},
                    "wind_kmh": {"type": "number", "description": "Ветер, км/ч", "default": 0},
                    "survey_types": {"type": "array", "items": {"type": "string", "enum": ["visible", "thermal", "multispectral"]}, "description": "Типы съёмки (опционально)"},
                },
                "required": ["project_id", "gsd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_planning_result",
            "description": "Подробный результат миссии: варианты, назначения, метрики.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mission_id": {"type": "integer", "description": "ID миссии из start_planning"}
                },
                "required": ["mission_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_plan",
            "description": "Объяснение плана: почему такие назначения (ПН, батарея, расстояние) и сравнение вариантов.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mission_id": {"type": "integer", "description": "ID миссии"}
                },
                "required": ["mission_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_plan",
            "description": "URL для скачивания полётного задания в GeoJSON по миссии.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mission_id": {"type": "integer", "description": "ID миссии"}
                },
                "required": ["mission_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_map_data",
            "description": "GeoJSON-данные маршрутов для отображения на карте (используй, когда нужно показать результат на карте).",
            "parameters": {
                "type": "object",
                "properties": {
                    "mission_id": {"type": "integer", "description": "ID миссии"}
                },
                "required": ["mission_id"],
            },
        },
    },
]


def _get_project(user, project_id: int | None):
    from survey.models import Project

    if not project_id:
        return None
    try:
        return Project.objects.get(pk=project_id, created_by=user)
    except (Project.DoesNotExist, ValueError, TypeError):
        return None


def _tool_get_project_context(args, user, project_id):
    from survey.views import _project_to_dicts

    project = _get_project(user, args.get("project_id", project_id))
    if project is None:
        return {"error": "Проект не найден. Сообщите пользователю, что нужно выбрать проект."}
    survey_zones, forbidden, vpps = _project_to_dicts(project)
    return {
        "project_id": project.id,
        "name": project.name,
        "survey_zones": [
            {"name": z["name"], "type": z["survey_type"]} for z in survey_zones
        ],
        "forbidden_zones": [z["name"] for z in forbidden],
        "vpps": [v["name"] for v in vpps],
    }


def _tool_list_uavs(args, user, project_id):
    from geo_processing import planning

    fleet = planning.get_fleet(args.get("active_uav_ids"))
    payloads = planning.get_payloads()
    return {
        "uavs": [
            {
                **u,
                "payloads_detail": [
                    f"{p.name} ({p.type})" for p in payloads if p.uav_model == u["model"]
                ],
                "usable_time_min": round(0.8 * u["time_fly_min"] * u["battery_pct"] / 100.0, 1),
            }
            for u in fleet
        ]
    }


def _tool_list_zones(args, user, project_id):
    from survey.models import SurveyZone
    from survey.views import _project_to_dicts

    project = _get_project(user, args.get("project_id", project_id))
    if project is None:
        return {"error": "Проект не найден."}
    _survey_zones, _forbidden, _vpps = _project_to_dicts(project)
    return {
        "survey_zones": [
            {"name": z.name, "type": z.survey_type, "area_ha": z.area_ha}
            for z in project.zones.filter(kind=SurveyZone.KIND_SURVEY)
        ],
        "forbidden_zones": [z.name for z in project.zones.filter(kind=SurveyZone.KIND_FORBIDDEN)],
    }


def _tool_start_planning(args, user, project_id):
    from geo_processing import planning as planning_mod
    from survey.models import Mission, SurveyZone
    from survey.views import _project_to_dicts

    project = _get_project(user, args.get("project_id", project_id))
    if project is None:
        return {"error": "Проект не найден."}
    survey_zones, forbidden, vpps = _project_to_dicts(project)
    if not survey_zones:
        return {"error": "В проекте нет зон съёмки. Сначала загрузите данные (load_demo/load_data)."}
    if not vpps:
        return {"error": "В проекте нет площадок ВПП."}

    result = planning_mod.run_planning(
        survey_zones=survey_zones,
        forbidden_zones=forbidden,
        vpps=vpps,
        gsd=float(args.get("gsd", 3)),
        wind_kmh=float(args.get("wind_kmh", 0)),
        side_overlap=0.5,
        front_overlap=0.6,
        survey_types=args.get("survey_types") or None,
    )
    if result["status"] != "success":
        return {"status": "infeasible", "reasons": result["reasons"]}

    mission = Mission.objects.create(
        project=project, created_by=user,
        gsd=float(args.get("gsd", 3)), wind_kmh=float(args.get("wind_kmh", 0)),
        status=Mission.STATUS_SUCCESS, result=result,
    )
    summary = {
        "mission_id": mission.id,
        "status": "success",
        "variants": {
            m: {"title": v["title"], "metrics": v["metrics"]} for m, v in result["variants"].items()
        },
    }
    return summary


def _tool_get_planning_result(args, user, project_id):
    from survey.models import Mission

    mission = _get_mission(user, args.get("mission_id"))
    if mission is None or not mission.result:
        return {"error": "Миссия не найдена или ещё не завершена."}
    result = mission.result
    if result.get("status") != "success":
        return {"status": result.get("status"), "reasons": result.get("reasons", [])}
    out = {"mission_id": mission.id, "variants": {}}
    for m, v in result["variants"].items():
        out["variants"][m] = {
            "title": v["title"],
            "metrics": v["metrics"],
            "assignments": [
                {"uav": s["uav"], "zone": s["zone"], "type": s["survey_type"],
                 "payload": s["payload"], "vpp": s["vpp"],
                 "start_min": s["start_min"], "duration_min": s["duration_min"],
                 "battery_used_pct": s["battery_used_pct"]}
                for s in v["sorties"]
            ],
        }
    return out


def _tool_explain_plan(args, user, project_id):
    from geo_processing import planning
    from survey.models import Mission

    mission = _get_mission(user, args.get("mission_id"))
    if mission is None or not mission.result:
        return {"error": "Миссия не найдена."}
    result = mission.result
    if result.get("status") != "success":
        return {"status": result.get("status"), "reasons": result.get("reasons", [])}
    fleet = {u["id"]: u for u in planning.get_fleet()}
    lines = []
    for m, v in result["variants"].items():
        lines.append(f"Вариант «{v['title']}» ({m}): налёт {v['metrics']['total_flight_min']} мин, "
                     f"готовность за {v['metrics']['total_time_min']} мин, {v['metrics']['uavs_used']} БВС, "
                     f"{v['metrics']['sorties']} вылета.")
        for s in v["sorties"]:
            u = fleet.get(s["uav_id"], {})
            lines.append(
                f"  • {s['uav']} ({u.get('model', '?')}, батарея {u.get('battery_pct', '?')}%) → "
                f"«{s['zone']}» [{s['survey_type']}]: ПН {s['payload']}, старт {s['vpp']}, "
                f"высота {s['altitude_m']} м, {s['duration_min']} мин, батарея {s['battery_used_pct']}%."
            )
    return {"explanation": "\n".join(lines)}


def _tool_export_plan(args, user, project_id):
    from survey.models import Mission

    mission = _get_mission(user, args.get("mission_id"))
    if mission is None or mission.status != Mission.STATUS_SUCCESS:
        return {"error": "Нет успешной миссии для экспорта."}
    return {"export_url": f"/api/missions/{mission.id}/export/"}


def _tool_get_map_data(args, user, project_id):
    from geo_processing import export
    from survey.models import Mission

    mission = _get_mission(user, args.get("mission_id"))
    if mission is None or not mission.result:
        return {"error": "Миссия не найдена."}
    result = mission.result
    if result.get("status") != "success":
        return {"error": "Нет результата для карты."}
    vpps = [
        {"name": v.name, "lon": float(v.geom.x), "lat": float(v.geom.y)}
        for v in mission.project.vpps.all()
    ]
    fc = export.build_flight_task_geojson(result, vpps)
    return {"geojson": fc}


def _get_mission(user, mission_id):
    from survey.models import Mission

    try:
        return Mission.objects.get(id=mission_id, project__created_by=user)
    except (Mission.DoesNotExist, ValueError, TypeError):
        return None


def execute_tool(name: str, args: dict, user, project_id: int | None) -> dict:
    try:
        if name == "get_project_context":
            return _tool_get_project_context(args, user, project_id)
        if name == "list_uavs":
            return _tool_list_uavs(args, user, project_id)
        if name == "list_zones":
            return _tool_list_zones(args, user, project_id)
        if name == "start_planning":
            return _tool_start_planning(args, user, project_id)
        if name == "get_planning_result":
            return _tool_get_planning_result(args, user, project_id)
        if name == "explain_plan":
            return _tool_explain_plan(args, user, project_id)
        if name == "export_plan":
            return _tool_export_plan(args, user, project_id)
        if name == "get_map_data":
            return _tool_get_map_data(args, user, project_id)
        return {"error": f"Неизвестный инструмент: {name}"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ошибка инструмента %s", name)
        return {"error": f"Ошибка инструмента {name}: {exc}"}


def handle_chat_message(message: str, history: list[dict], project_id: int | None, user) -> dict:
    """Главная точка входа чата. Возвращает {response, map_data_list, actions}."""
    if not settings.LLM_API_KEY:
        return {
            "response": (
                "ИИ-ассистент не настроен: в .env не задан LLM_API_KEY. "
                "Проверьте переменную LLM_API_KEY (OpenAI-совместимый API)."
            ),
            "map_data_list": [],
            "actions": [],
        }

    from openai import OpenAI

    client = OpenAI(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_API_BASE_URL,
        timeout=settings.LLM_REQUEST_TIMEOUT,
        max_retries=1,
    )

    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in (history or [])[-10:]:
        role = h.get("role")
        content = h.get("content")
        if role in ("user", "assistant") and content:
            msgs.append({"role": role, "content": content})
    suffix = f"\n\n[Текущий проект: id={project_id}]" if project_id else ""
    msgs.append({"role": "user", "content": message + suffix})

    map_data_list: list[dict] = []
    actions: list[dict] = []

    try:
        for _iteration in range(10):
            response = client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=msgs,
                tools=TOOLS,
                tool_choice="auto",
            )
            assistant_message = response.choices[0].message
            if not assistant_message.tool_calls:
                return {
                    "response": assistant_message.content or "",
                    "map_data_list": map_data_list,
                    "actions": actions,
                }
            msgs.append({
                "role": "assistant",
                "content": assistant_message.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in assistant_message.tool_calls
                ],
            })
            for tc in assistant_message.tool_calls:
                try:
                    func_args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    func_args = {}
                result = execute_tool(tc.function.name, func_args, user, project_id)
                if tc.function.name == "get_map_data" and isinstance(result, dict) and "geojson" in result:
                    map_data_list.append({"data": result["geojson"], "type": "routes"})
                actions.append({
                    "tool": tc.function.name,
                    "result_summary": _summarize(result),
                })
                msgs.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str)[:8000],
                })
        return {
            "response": "Не удалось завершить ответ за отведённое число итераций.",
            "map_data_list": map_data_list,
            "actions": actions,
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ошибка LLM-запроса")
        return {
            "response": f"Ошибка обращения к ИИ-модели: {exc}",
            "map_data_list": map_data_list,
            "actions": actions,
        }


def _summarize(result: dict) -> str:
    if isinstance(result, dict):
        if "error" in result:
            return str(result["error"])
        if "reasons" in result:
            return "; ".join(result["reasons"][:3])
        if "variants" in result:
            return f"Вариантов: {', '.join(result['variants'])}"
    return "OK"

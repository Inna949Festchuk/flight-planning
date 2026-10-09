#!/usr/bin/env bash
# E2E-проверка GeoScan Planner: JWT → проект → демо-данные → MILP → варианты → экспорт
set -euo pipefail

API="${API:-http://localhost:8000/api}"
JQ="${JQ:-jq}"

step() { echo; echo "==> $1"; }

step "Регистрация тестового пользователя"
REG_USER="test_$(date +%s)"
curl -sf -X POST "$API/auth/register/" -H 'Content-Type: application/json' \
  -d "{\"username\":\"$REG_USER\",\"password\":\"testpass123\",\"email\":\"$REG_USER@test.local\"}" > /dev/null
echo "OK: пользователь $REG_USER"

step "Логин (JWT)"
TOKEN=$(curl -sf -X POST "$API/auth/login/" -H 'Content-Type: application/json' \
  -d "{\"username\":\"$REG_USER\",\"password\":\"testpass123\"}" | $JQ -r .access)
[ -n "$TOKEN" ] && [ "$TOKEN" != "null" ]
AUTH="Authorization: Bearer $TOKEN"
echo "OK: токен получен"

step "Создание проекта"
PROJECT_ID=$(curl -sf -X POST "$API/projects/" -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"name":"E2E тест"}' | $JQ -r .id)
echo "OK: проект $PROJECT_ID"

step "Загрузка демо-данных"
curl -sf -X POST "$API/projects/$PROJECT_ID/load_demo/" -H "$AUTH" | $JQ .
echo "OK"

step "Запуск MILP-расчёта (GSD=1, ветер=5)"
MISSION_ID=$(curl -sf -X POST "$API/projects/$PROJECT_ID/missions/" -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"gsd":1,"wind_kmh":5}' | $JQ -r .id)
echo "Миссия $MISSION_ID, ожидаю..."

for i in $(seq 1 60); do
  STATUS=$(curl -sf "$API/missions/$MISSION_ID/" -H "$AUTH" | $JQ -r .status)
  [ "$STATUS" = "success" ] || [ "$STATUS" = "infeasible" ] || [ "$STATUS" = "error" ] && break
  sleep 2
done
echo "Статус: $STATUS"
[ "$STATUS" = "success" ] || { echo "FAIL: расчёт не удался"; curl -sf "$API/missions/$MISSION_ID/" -H "$AUTH" | $JQ .; exit 1; }

step "Проверка результатов"
curl -sf "$API/missions/$MISSION_ID/" -H "$AUTH" > /tmp/mission.json
$JQ -r '.result.variants | to_entries[] | "  \(.key): \(.value.metrics.total_time_min) мин, \(.value.metrics.uavs_used) БВС, \(.value.metrics.sorties) вылетов, налёт \(.value.metrics.total_flight_min) мин"' /tmp/mission.json

# Проверка 1: батареи не превышают 80%
VIOLATIONS=$(curl -sf "$API/missions/$MISSION_ID/" -H "$AUTH" | $JQ -r \
  '[.result.variants[] | .sorties[] | select(.battery_used_pct > 80.5)] | length')
[ "$VIOLATIONS" = "0" ] && echo "OK: все вылеты в пределах 80% батареи" || { echo "FAIL: $VIOLATIONS вылетов превышают 80% батареи"; exit 1; }

# Проверка 2: совместимость ПН (thermal → Геоскан 801)
THERMAL_OK=$(curl -sf "$API/missions/$MISSION_ID/" -H "$AUTH" | $JQ -r \
  '[.result.variants[] | .sorties[] | select(.survey_type=="thermal" and (.model | startswith("Геоскан 801")==false))] | length')
[ "$THERMAL_OK" = "0" ] && echo "OK: тепловизионные зоны — только Геоскан 801" || { echo "FAIL: несовместимая ПН на thermal-зоне"; exit 1; }

# Проверка 3: все зоны покрыты (recommended)
ZONES=$(curl -sf "$API/projects/$PROJECT_ID/data/" -H "$AUTH" | $JQ -r '[.zones.features[] | select(.properties.kind=="survey") | .properties.name] | length')
COVERED=$(curl -sf "$API/missions/$MISSION_ID/" -H "$AUTH" | $JQ -r \
  '[.result.variants.recommended.sorties[].zone] | unique | length')
[ "$ZONES" = "$COVERED" ] && echo "OK: покрыто зон $COVERED из $ZONES" || { echo "FAIL: покрыто $COVERED из $ZONES"; exit 1; }

step "Экспорт GeoJSON"
curl -sf "$API/missions/$MISSION_ID/export/" -H "$AUTH" > /tmp/flight-task.geojson
python3 -m json.tool /tmp/flight-task.geojson > /dev/null && echo "OK: валидный GeoJSON ($(wc -c < /tmp/flight-task.geojson) байт)"
$JQ -r '[.features[] | select(.properties.kind=="route")] | length' /tmp/flight-task.geojson | xargs echo "  маршрутов в экспорте:"

step "Проверка Infeasible-сценария (ветер 30 км/ч > пределов БВС)"
BADM_ID=$(curl -sf -X POST "$API/projects/$PROJECT_ID/missions/" -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"gsd":1,"wind_kmh":30}' | $JQ -r .id)
BADSTATUS=""
for i in $(seq 1 30); do
  BADSTATUS=$(curl -sf "$API/missions/$BADM_ID/" -H "$AUTH" | $JQ -r .status)
  [ "$BADSTATUS" = "infeasible" ] || [ "$BADSTATUS" = "error" ] || [ "$BADSTATUS" = "success" ] && break
  sleep 2
done
if [ "$BADSTATUS" = "infeasible" ]; then
  curl -sf "$API/missions/$BADM_ID/" -H "$AUTH" | $JQ -r '.result.reasons[0:1][]' | sed 's/^/  причина: /'
  echo "OK: невыполнимый сценарий возвращает infeasible с причиной"
else
  echo "FAIL: ожидался infeasible, получен $BADSTATUS"
  exit 1
fi

step "Swagger"
curl -sf "$API/schema/" > /dev/null && echo "OK: OpenAPI schema доступна"

echo
echo "=============================================="
echo "  ALL CHECKS PASSED ✓"
echo "  $API"
echo "=============================================="

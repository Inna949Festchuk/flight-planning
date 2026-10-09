import "maplibre-gl/dist/maplibre-gl.css";
import maplibregl from "maplibre-gl";
import { marked } from "marked";
import DOMPurify from "dompurify";

const root = document.querySelector("#prototype");
const toast = document.querySelector("#toast");

const TYPE_LABELS = { visible: "RGB", thermal: "ИК", multispectral: "Мультиспектр" };
const TYPE_COLORS = { visible: "#1976eb", thermal: "#ff4d0a", multispectral: "#21b878" };
const UAV_COLORS = ["#1976eb", "#21b878", "#ff4d0a", "#8b5cf6", "#eab308", "#06b6d4"];

const state = {
  screen: "login",
  registerMode: false,
  token: localStorage.getItem("gs_token") || null,
  user: null,
  project: null,
  resolution: 1,
  wind: 5,
  type: "all",
  dataLoaded: false,
  pointsLoaded: false,
  areaLoaded: false,
  fleetOpen: false,
  fleetMenu: null,
  excluded: new Set(),
  fleet: [],
  zonesData: null, // {zones: FC, vpps: FC}
  calculating: false,
  mission: null, // {id, status, result}
  expandedRoute: null, // recommended | time | resource
  selectedVariant: "recommended",
  completion: null,
  aiHistory: [],
  aiBusy: false,
  flight: { t: 0, playing: false, scale: 5 },
};
window.__state = state; // debug-хук

const icon = (name, size = 18) => {
  const paths = {
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    lock: '<rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    layers: '<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5M3 16l9 5 9-5"/>',
    target: '<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2"/><path d="M12 2v3m0 14v3M2 12h3m14 0h3"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    minus: '<path d="M5 12h14"/>',
    home: '<path d="m3 11 9-8 9 8"/><path d="M5 10v10h14V10"/>',
    spark: '<path d="m12 3 1.6 4.4L18 9l-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6L12 3Z"/><path d="m19 15 .8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8L19 15Z"/>',
    send: '<path d="m3 3 18 9-18 9 3-9-3-9Z"/><path d="M6 12h15"/>',
    chevron: '<path d="m8 10 4 4 4-4"/>',
    download: '<path d="M12 3v12m0 0 4-4m-4 4-4-4"/><path d="M5 19h14"/>',
    flag: '<path d="M5 21V4m0 1h11l-2 3 2 3H5"/>',
    chevronRight: '<path d="m9 18 6-6-6-6"/>',
  };
  return `<svg class="icon" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || ""}</svg>`;
};
const logo = (className = "logo") => `<img class="${className}" src="/assets/strela-logo.png" alt="СТРЕЛА">`;
let notifyTimer = null;
const notify = (message) => {
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(notifyTimer);
  notifyTimer = setTimeout(() => toast.classList.remove("visible"), 2600);
};

/* ---------------- API (JWT) ---------------- */

const api = async (path, opts = {}) => {
  const headers = { ...(opts.headers || {}) };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
  const res = await fetch(`/api${path}`, {
    method: opts.method || "GET",
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401) {
    logout();
    throw new Error("Сессия истекла, войдите заново");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const d = await res.json();
      detail = d.detail || JSON.stringify(d);
    } catch {
      /* не JSON */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
};

const logout = () => {
  state.token = null;
  state.user = null;
  localStorage.removeItem("gs_token");
  state.screen = "login";
  state.project = null;
  state.dataLoaded = false;
  state.pointsLoaded = false;
  state.areaLoaded = false;
  render();
};

/* ---------------- MapLibre (персистентный контейнер) ---------------- */

const mapEl = document.createElement("div");
mapEl.className = "map-canvas";
// Критично: inline-стили до создания Map — MapLibre определяет position из
// computed-стилей, а для отсоединённого элемента всё "static" и он ломает контейнер.
mapEl.style.position = "absolute";
mapEl.style.inset = "0";
mapEl.style.width = "100%";
mapEl.style.height = "100%";
let map = null;

const MAP_STYLE = {
  version: 8,
  attribution: "Esri, Maxar, Earthstar Geographics",
  glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
  sources: {
    esri: {
      type: "raster",
      tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
      tileSize: 256,
    },
  },
  layers: [{ id: "esri", type: "raster", source: "esri" }],
};

function initMap() {
  if (map) return;
  map = new maplibregl.Map({ container: mapEl, style: MAP_STYLE, center: [38.92, 56.49], zoom: 11.6 });
  window.__map = map; // debug-хук
  map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
  map.on("load", () => {
    for (const id of ["zones", "forbidden", "zone-labels", "vpps", "routes-transit", "routes-gals", "routes-labels", "flight-uavs"]) {
      map.addSource(id, { type: "geojson", data: emptyFC() });
    }
    map.addLayer({
      id: "zones-fill", type: "fill", source: "zones",
      paint: {
        "fill-color": [
          "match", ["get", "kind"], "forbidden", "#ef5d5d",
          ["match", ["get", "survey_type"], "thermal", "#ff4d0a", ["match", ["get", "survey_type"], "multispectral", "#21b878", "#1976eb"]],
        ],
        "fill-opacity": ["match", ["get", "kind"], "forbidden", 0.25, 0.3],
      },
    });
    map.addLayer({
      id: "zones-line-survey", type: "line", source: "zones",
      filter: ["!", ["==", ["get", "kind"], "forbidden"]],
      paint: {
        "line-color": [
          "match", ["get", "survey_type"], "thermal", "#ff4d0a", ["match", ["get", "survey_type"], "multispectral", "#21b878", "#1976eb"],
        ],
        "line-width": 1.5,
      },
    });
    map.addLayer({
      id: "zones-line-forbidden", type: "line", source: "zones",
      filter: ["==", ["get", "kind"], "forbidden"],
      paint: { "line-color": "#ef5d5d", "line-width": 1.5, "line-dasharray": [2, 2] },
    });
    map.addLayer({
      id: "zones-label", type: "symbol", source: "zone-labels",
      layout: { "text-field": ["get", "name"], "text-size": 13, "text-anchor": "center", "text-justify": "center", "text-allow-overlap": true },
      paint: { "text-color": ["match", ["get", "kind"], "forbidden", "#b03a2e", "#0b1537"], "text-halo-color": "#ffffff", "text-halo-width": 2 },
    });
    map.addLayer({
      id: "vpps-circle", type: "circle", source: "vpps",
      paint: { "circle-radius": 9, "circle-color": "#ff4d0a", "circle-stroke-width": 3, "circle-stroke-color": "#fff" },
    });
    map.addLayer({
      id: "vpps-label", type: "symbol", source: "vpps",
      layout: { "text-field": ["get", "name"], "text-size": 12, "text-offset": [0, 1.4] },
      paint: { "text-color": "#0b1537", "text-halo-color": "#ffffff", "text-halo-width": 1.8 },
    });
    map.addLayer({
      id: "routes-gals", type: "line", source: "routes-gals",
      paint: { "line-color": ["get", "color"], "line-width": 1.5, "line-opacity": 0.65 },
    });
    map.addLayer({
      id: "routes-transit", type: "line", source: "routes-transit",
      paint: { "line-color": ["get", "color"], "line-width": 4, "line-opacity": 0.95 },
    });
    map.addLayer({
      id: "routes-label", type: "symbol", source: "routes-labels",
      layout: { "text-field": ["get", "text"], "text-size": 10.5, "text-anchor": "center", "text-allow-overlap": true },
      paint: { "text-color": "#0b1537", "text-halo-color": "#ffffff", "text-halo-width": 1.8 },
    });
    map.addLayer({
      id: "flight-uavs-circle", type: "circle", source: "flight-uavs",
      paint: { "circle-radius": 9, "circle-color": ["get", "color"], "circle-stroke-width": 2.5, "circle-stroke-color": "#fff" },
    });
    map.addLayer({
      id: "flight-uavs-label", type: "symbol", source: "flight-uavs",
      layout: { "text-field": ["get", "name"], "text-size": 11, "text-anchor": "bottom", "text-offset": [0, -1.6] },
      paint: { "text-color": "#0b1537", "text-halo-color": "#ffffff", "text-halo-width": 1.8 },
    });
    // Попапы: зоны, маршруты, ВПП
    const popup = new maplibregl.Popup({ closeButton: true, closeOnClick: true, maxWidth: "320px", className: "gs-popup" });
    const typeRu = { visible: "RGB (видимый диапазон)", thermal: "ИК (тепловизионный)", multispectral: "мультиспектральный" };
    const zonePopupHtml = (p) => {
      const s = currentSortieForZone(p.name);
      let h = `<div class="popup-card"><strong>${p.name}</strong><span class="popup-kind ${p.kind === "forbidden" ? "forbidden" : ""}">${p.kind === "forbidden" ? "Запретная зона" : "Зона съёмки"}</span><table class="popup-table">`;
      if (p.kind === "forbidden") {
        h += "<tr><td>ограничение</td><td>полёты запрещены</td></tr>";
      } else {
        h += `<tr><td>съёмка</td><td>${typeRu[p.survey_type] || "—"}</td></tr>`;
        if (p.area_ha) h += `<tr><td>площадь</td><td>${p.area_ha} га</td></tr>`;
      }
      if (s) {
        h += `<tr><td>БВС</td><td>${s.uav} · ${s.model}</td></tr>
          <tr><td>старт</td><td>${Math.round(s.start_min)} мин</td></tr>
          <tr><td>время работы</td><td>${Math.round(s.duration_min)} мин</td></tr>
          <tr><td>ПН</td><td>${s.payload}</td></tr>
          <tr><td>высота</td><td>${s.altitude_m} м</td></tr>
          <tr><td>батарея</td><td>${s.battery_used_pct}%</td></tr>`;
      }
      return h + "</table></div>";
    };
    const routePopupHtml = (uav, zone) => {
      const s = currentSortieForUavZone(uav, zone);
      if (!s) return `<div class="popup-card"><strong>${uav}</strong><table class="popup-table"><tr><td>зона</td><td>${zone}</td></tr></table></div>`;
      return `<div class="popup-card"><strong>Вылет: ${s.uav}</strong><span class="popup-kind">${s.model}</span><table class="popup-table">
        <tr><td>зона</td><td>${s.zone}</td></tr>
        <tr><td>съёмка</td><td>${typeRu[s.survey_type] || s.survey_type}</td></tr>
        <tr><td>ПН</td><td>${s.payload}</td></tr>
        <tr><td>ВПП</td><td>${s.vpp}</td></tr>
        <tr><td>старт</td><td>${Math.round(s.start_min)} мин</td></tr>
        <tr><td>время работы</td><td>${Math.round(s.duration_min)} мин</td></tr>
        <tr><td>высота</td><td>${s.altitude_m} м</td></tr>
        <tr><td>скорость</td><td>${s.speed_kmh} км/ч</td></tr>
        <tr><td>батарея</td><td>${s.battery_used_pct}%</td></tr>
      </table></div>`;
    };
    const vppPopupHtml = (name) => {
      const used = currentVariantSorties().filter((s) => s.vpp === name);
      let h = `<div class="popup-card"><strong>${name}</strong><span class="popup-kind">Площадка старта / посадки</span><table class="popup-table">`;
      h += used.length
        ? `<tr><td>в выбранном варианте</td><td>${used.length} вылет(а)</td></tr>` + used.map((s) => `<tr><td>&nbsp;</td><td>${s.uav} → ${s.zone}</td></tr>`).join("")
        : `<tr><td>в выбранном варианте</td><td>не используется</td></tr>`;
      return h + "</table></div>";
    };
    map.on("click", "zones-fill", (e) => {
      const f = e.features && e.features[0];
      if (!f) return;
      popup.setLngLat(e.lngLat).setHTML(zonePopupHtml(f.properties)).addTo(map);
    });
    const routeClick = (e) => {
      const f = e.features && e.features[0];
      if (!f) return;
      popup.setLngLat(e.lngLat).setHTML(routePopupHtml(f.properties.uav, f.properties.zone)).addTo(map);
    };
    map.on("click", "routes-transit", routeClick);
    map.on("click", "routes-gals", routeClick);
    map.on("click", "vpps-circle", (e) => {
      const f = e.features && e.features[0];
      if (!f) return;
      popup.setLngLat(e.lngLat).setHTML(vppPopupHtml(f.properties.name)).addTo(map);
    });
    for (const layer of ["zones-fill", "routes-transit", "routes-gals", "vpps-circle"]) {
      map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
    }
    // Применим данные, накопленные до готовности стиля
    for (const [id, fc] of Object.entries(pendingMapData)) {
      if (map.getSource(id)) map.getSource(id).setData(fc);
      delete pendingMapData[id];
    }
  });
}

// Разбиваем полный маршрут вылета [vpp, s1...sn, vpp] на подлёт/возврат и галсы
function splitRoute(route, color, extra = {}) {
  const transit =
    route.length >= 4
      ? [
          { type: "Feature", properties: { color, ...extra }, geometry: { type: "LineString", coordinates: [route[0], route[1]] } },
          { type: "Feature", properties: { color, ...extra }, geometry: { type: "LineString", coordinates: [route[route.length - 2], route[route.length - 1]] } },
        ]
      : [];
  const gals =
    route.length >= 3
      ? [{ type: "Feature", properties: { color, ...extra }, geometry: { type: "LineString", coordinates: route.slice(1, -1) } }]
      : [];
  return { transit, gals };
}

const emptyFC = () => ({ type: "FeatureCollection", features: [] });

// Данные, пришедшие до готовности стиля карты (источники ещё не существуют)
const pendingMapData = {};
window.__pending = pendingMapData; // debug-хук

function setMapSource(id, fc) {
  if (map && map.getSource(id)) {
    map.getSource(id).setData(fc);
  } else {
    pendingMapData[id] = fc;
  }
}

function loadProjectMapData() {
  if (!state.zonesData) return;
  const zonesFC = {
    type: "FeatureCollection",
    features: state.zonesData.zones.features.map((f) => ({
      ...f,
      properties: { ...f.properties, kind: f.properties.kind === "forbidden" ? "forbidden" : "survey" },
    })),
  };
  setMapSource("zones", zonesFC);
  setMapSource("vpps", state.zonesData.vpps);
  // Подписи зон — в барицентре внешнего кольца (первая часть полигона)
  const labels = state.zonesData.zones.features.map((f) => {
    const g = f.geometry;
    const ring = g.type === "Polygon" ? g.coordinates[0] : g.coordinates[0][0];
    const pts = ring.slice(0, -1);
    const c = [pts.reduce((s, p) => s + p[0], 0) / pts.length, pts.reduce((s, p) => s + p[1], 0) / pts.length];
    return {
      type: "Feature",
      properties: { name: f.properties.name, kind: f.properties.kind === "forbidden" ? "forbidden" : "survey" },
      geometry: { type: "Point", coordinates: c },
    };
  });
  setMapSource("zone-labels", { type: "FeatureCollection", features: labels });
  const feats = [...state.zonesData.zones.features, ...state.zonesData.vpps.features];
  if (feats.length && map) {
    const b = new maplibregl.LngLatBounds();
    const extendGeom = (g) => {
      if (g.type === "Point") b.extend(g.coordinates);
      if (g.type === "Polygon") g.coordinates.flat().forEach((c) => b.extend(c));
      if (g.type === "MultiPolygon") g.coordinates.flat(1).forEach((c) => b.extend(c));
    };
    feats.forEach((f) => extendGeom(f.geometry));
    map.fitBounds(b, { padding: 50, duration: 800 });
    requestAnimationFrame(() => map.resize());
  }
}

function currentVariantSorties() {
  const m = state.mission;
  if (!m || !m.result || m.result.status !== "success") return [];
  const v = m.result.variants[state.selectedVariant];
  return v ? v.sorties : [];
}

function currentSortieForZone(zoneName) {
  return currentVariantSorties().find((s) => s.zone === zoneName) || null;
}

function currentSortieForUavZone(uav, zone) {
  return currentVariantSorties().find((s) => s.uav === uav && s.zone === zone) || null;
}

function zoneCenter(name) {
  const f = state.zonesData?.zones?.features.find((z) => z.properties.name === name);
  if (!f) return null;
  const g = f.geometry;
  const ring = g.type === "Polygon" ? g.coordinates[0] : g.coordinates[0][0];
  const pts = ring.slice(0, -1);
  return [pts.reduce((s, p) => s + p[0], 0) / pts.length, pts.reduce((s, p) => s + p[1], 0) / pts.length];
}

function loadRoutesOnMap() {
  if (!map) return;
  const info = document.getElementById("map-info");
  const mission = state.mission;
  if (!mission || !mission.result || mission.result.status !== "success") {
    setMapSource("routes-transit", emptyFC());
    setMapSource("routes-gals", emptyFC());
    setMapSource("routes-labels", emptyFC());
    if (info) info.innerHTML = "";
    return;
  }
  const variant = mission.result.variants[state.selectedVariant];
  if (!variant) {
    setMapSource("routes-transit", emptyFC());
    setMapSource("routes-gals", emptyFC());
    setMapSource("routes-labels", emptyFC());
    if (info) info.innerHTML = "";
    return;
  }
  if (info) {
    info.innerHTML = `<strong>${variant.title}</strong><span>готовность ${fmtMin(variant.metrics.total_time_min)} · налёт ${fmtMin(variant.metrics.total_flight_min)} · ${variant.metrics.uavs_used} БВС · ${variant.metrics.sorties} вылетов</span>`;
  }
  const uavs = [...new Set(variant.sorties.map((s) => s.uav))];
  const colorOf = (name) => UAV_COLORS[uavs.indexOf(name) % UAV_COLORS.length];
  const transit = [];
  const gals = [];
  const labels = [];
  for (const s of variant.sorties) {
    const { transit: t, gals: g } = splitRoute(s.route, colorOf(s.uav), { uav: s.uav, zone: s.zone });
    transit.push(...t);
    gals.push(...g);
    const c = zoneCenter(s.zone);
    if (c) labels.push({ type: "Feature", properties: { text: `${s.uav} · ${Math.round(s.duration_min)} мин` }, geometry: { type: "Point", coordinates: c } });
  }
  setMapSource("routes-transit", { type: "FeatureCollection", features: transit });
  setMapSource("routes-gals", { type: "FeatureCollection", features: gals });
  setMapSource("routes-labels", { type: "FeatureCollection", features: labels });
}

function attachMap() {
  const surface = root.querySelector(".map-surface");
  if (!surface) return;
  surface.appendChild(mapEl);
  // Карта создаётся лениво: только когда контейнер реально в DOM
  if (!map) initMap();
  // Размер canvas должен совпадать с контейнером: наблюдаем изменения layout
  if (map && !attachMap.observed) {
    attachMap.observed = true;
    const ro = new ResizeObserver(() => map && map.resize());
    ro.observe(mapEl);
  }
  if (map) requestAnimationFrame(() => map.resize());
}

/* ---------------- Экраны ---------------- */

function header(active = 1) {
  const steps = ["Настройка", "Результаты", "Полёт"];
  const name = state.user ? state.user.username : "Оператор";
  return `<header class="topbar"><div class="top-logo">${logo()}</div><nav class="steps" aria-label="Этапы сценария">
    ${steps.map((label, index) => { const n = index + 1; return `<button class="step ${n === active ? "active" : ""}" data-screen="${n === 1 ? "setup" : n === 2 ? "results" : "flight"}"><span>${n}</span>${label}</button>${n < 3 ? "<i></i>" : ""}`; }).join("")}
  </nav><div class="profile"><span class="avatar">${name.slice(0, 2).toUpperCase()}</span><span><strong>${name}</strong><small>Оператор</small></span><button class="btn-logout" data-action="logout">Выйти</button></div></header>`;
}

function loginScreen() {
  const reg = state.registerMode;
  return `<main class="login-screen"><div class="login-stack">${logo("login-logo")}<form class="login-card" id="login-form">
    <h1>${reg ? "Создание аккаунта" : "Вход в систему"}</h1><p>Планирование беспилотных авиационных работ</p>
    <label>Имя<div class="input-wrap">${icon("user")}<input id="nickname" value="demo" autocomplete="username" aria-label="Имя"></div></label>
    ${reg ? '<label>Email<div class="input-wrap"><input id="email" type="email" value="demo@geoscan.local" aria-label="Email"></div></label>' : ""}
    <label>Пароль<div class="input-wrap">${icon("lock")}<input id="password" type="password" value="demo" placeholder="Введите пароль" autocomplete="current-password" aria-label="Пароль"></div></label>
    <label class="remember"><input type="checkbox">Запомнить меня</label>
    <button class="btn btn-primary btn-wide" type="submit">${reg ? "Создать и войти" : "Войти"}</button>
    <div class="create-account" data-action="toggle-register">${reg ? "Уже есть аккаунт — войти" : "Создать аккаунт"}</div>
  </form><div class="demo-login"><strong>Демонстрационный вход</strong><span>Общий аккаунт: demo / demo (создаётся при первом запуске)</span></div></div></main>`;
}

function uploadBlock(kind, loaded) {
  const points = kind === "points";
  return `<section class="control-section"><div class="control-title"><strong>${points ? "Точки старта и посадки (ВПП)" : "Область съёмки"}</strong></div>
    <button class="upload-box ${loaded ? "loaded" : ""}" data-action="choose-${kind}"><span><b>${loaded ? (points ? "vpp.geojson" : "polygons.geojson") : "Загрузить файл"}</b><small>${loaded ? (points ? "6 площадок" : "8 зон") : (points ? "GeoJSON — точки" : "GeoJSON — полигоны")}</small></span>${loaded ? `<em>${icon("check", 14)} Загружено</em>` : ""}</button>
    <input type="file" id="file-${kind}" accept=".geojson,.json,application/geo+json" hidden>
    <button class="file-link" data-action="choose-${kind}">Выбрать файл</button></section>`;
}

function settingsPanel() {
  const ready = state.dataLoaded && state.fleet.length > 0;
  const types = [
    ["all", "Все"], ["visible", "RGB"], ["thermal", "ИК"], ["multispectral", "Мультиспектр"],
  ];
  return `<aside class="settings-panel">
    <section class="control-section resolution-section"><div class="control-title"><strong>Разрешение, м/пиксель (GSD)</strong></div><label class="resolution-input"><input id="resolution" type="number" min="0.1" max="10" step="0.1" value="${state.resolution}" aria-label="Разрешение, м/пиксель"></label><div class="chip-row">${[0.5, 1, 2].map((n) => `<button class="chip ${state.resolution === n ? "active" : ""}" data-resolution="${n}">${n}</button>`).join("")}</div></section>
    <section class="control-section"><div class="control-title"><strong>Ветер, км/ч</strong></div><label class="resolution-input"><input id="wind" type="number" min="0" max="50" value="${state.wind}" aria-label="Ветер, км/ч"></label></section>
    ${uploadBlock("points", state.pointsLoaded)}${uploadBlock("area", state.areaLoaded)}
    <button class="demo-scenario" data-action="load-demo">${icon("spark", 13)} Загрузить демо-сценарий</button>
    <section class="control-section"><div class="control-title"><strong>Тип съёмки</strong></div><div class="type-row">${types.map(([value, label]) => `<button class="type-chip ${state.type === value ? "active" : ""}" data-type="${value}">${label}</button>`).join("")}</div></section>
    <button class="fleet-launch ${state.fleetOpen ? "is-open" : ""}" data-action="toggle-fleet"><span><strong>Парк БВС</strong><small>${state.fleet.length || "—"} аппарата(ов)<br>${state.fleet.length ? "все участвуют в расчёте" : "загрузите данные"}</small></span><b>${state.fleetOpen ? "Скрыть" : "Показать"}</b><span class="arrow">${icon("chevronRight", 16)}</span></button>
    <button class="btn btn-primary continue" data-action="calculate" ${ready && !state.calculating ? "" : "disabled"}>${state.calculating ? "Расчёт MILP…" : ready ? "Рассчитать" : "Продолжить"}</button></aside>`;
}

function mapButtons() {
  return `<div class="map-buttons"><button data-action="zoom-in" title="Приблизить">${icon("plus", 16)}</button><button data-action="zoom-out" title="Отдалить">${icon("minus", 16)}</button><button data-action="zoom-reset" title="Сбросить">${icon("home", 16)}</button></div>
    <div class="map-info" id="map-info"></div>
    <div class="map-legend">
      <div><span class="lg-swatch" style="background:#1976eb"></span>Зона RGB</div>
      <div><span class="lg-swatch" style="background:#ff4d0a"></span>Зона ИК</div>
      <div><span class="lg-swatch" style="background:#21b878"></span>Зона мультиспектр</div>
      <div><span class="lg-swatch lg-forbidden"></span>Запретная зона</div>
      <div><span class="lg-vpp"></span>ВПП — старт / посадка</div>
      <div><span class="lg-line-thick"></span>подлёт к зоне / возврат</div>
      <div><span class="lg-line-thin"></span>галсы съёмки в зоне</div>
    </div>
    <div class="north">С<span>↑</span></div>`;
}

function mapSurface(loaded) {
  return `<div class="map-surface ${loaded ? "has-data" : ""}">
    ${loaded ? "" : `<div class="map-placeholder"><strong>Подготовьте данные для расчёта</strong><span>Загрузите ВПП и зоны слева<br>или нажмите «Демо-сценарий»</span></div>`}
    ${mapButtons()}</div>`;
}

function demoPanel(results = false) {
  return `<section class="demo-panel"><h3>Как это работает</h3><div>${results
    ? "<p>• MILP распределил зоны: совместимость ПН, батарея с запасом 20%, запретные зоны учтены</p><p>• Раскройте вариант, чтобы посмотреть состав работ; маршрут выбранного — на карте</p><p>• Скачайте полётное задание (GeoJSON) или выберите вариант</p>"
    : "<p>• Задайте GSD и ветер, загрузите ВПП и зоны (или демо-сценарий)</p><p>• Алгоритм MILP построит 3 варианта: баланс, мин. время, мин. налёт</p><p>• Справа — ИИ-помощник: спросите про данные, расчёт и результат</p>"}</div></section>`;
}

function aiPanel() {
  const messages = state.aiHistory
    .slice(-6)
    .map((m) => (m.role === "assistant" ? `<div class="ai-msg assistant ai-md">${renderAiMarkdown(m.content)}</div>` : `<div class="ai-msg user">${escapeHtml(m.content)}</div>`))
    .join("");
  return `<aside class="ai-panel"><h2>${icon("spark")} ИИ-помощник</h2>
    <div class="ai-messages">${messages || '<div class="ai-msg-hint">Спросите о данных, подходящих БВС или запустите расчёт через диалог.</div>'}</div>
    <div class="ai-actions"><button data-message="Проверь загруженные данные: зоны, ВПП, парк.">Проверь загруженные данные</button><button data-message="Какие БВС из парка подходят для этой задачи и почему?">Какие БВС подойдут?</button></div>
    <div class="ai-compose"><input id="ai-question" placeholder="Задайте вопрос или опишите задачу" ${state.aiBusy ? "disabled" : ""}><button data-action="send-ai" ${state.aiBusy ? "disabled" : ""}>${state.aiBusy ? "…" : icon("send")}</button></div></aside>`;
}

function droneRow(drone) {
  const excluded = state.excluded.has(drone.id);
  const payloadChips = (drone.payloads || []).map((p) => `<i>${p}</i>`).join("");
  return `<article class="drone-row ${excluded ? "excluded" : ""}"><div class="drone-main"><strong>${drone.name}</strong><button class="dots" data-drone-menu="${drone.id}">•••</button></div><div class="drone-foot"><span>${payloadChips}</span><span class="drone-state">${excluded ? "<em>Исключён из списка</em>" : "<b>Готов</b>"}<small>Батарея&nbsp;&nbsp; <strong>${drone.battery_pct}%</strong></small></span></div>${state.fleetMenu === drone.id ? `<button class="drone-popover" data-toggle-drone="${drone.id}">${excluded ? "Вернуть в список" : "Убрать из списка"}</button>` : ""}</article>`;
}

function fleetDrawer() {
  return `<aside class="fleet-drawer"><div class="fleet-head"><span><strong>Парк БВС</strong><small>${state.fleet.length} аппаратов · ${state.excluded.size} исключено</small></span><button data-action="close-fleet">×</button></div><div class="fleet-scroll">${state.fleet.map(droneRow).join("")}</div></aside>`;
}

function setupScreen() {
  const loaded = state.dataLoaded;
  return `<div class="app">${header(1)}<main class="setup-layout">${settingsPanel()}<section class="center-workspace">${mapSurface(loaded)}${demoPanel(false)}${state.fleetOpen ? fleetDrawer() : ""}</section>${aiPanel()}</main></div>`;
}

const VARIANT_ORDER = [
  ["recommended", "Рекомендованный", "orange", "Лучший баланс времени и расхода ресурса"],
  ["time", "Лучший по времени", "blue", "Минимальное время до посадки последнего БВС"],
  ["resource", "Лучший по ресурсу", "green", "Минимальный суммарный налёт"],
];

const fmtMin = (v) => (v >= 60 ? `${Math.floor(v / 60)} ч ${Math.round(v % 60)} мин` : `${Math.round(v)} мин`);

function routeCard(variant, key) {
  const meta = VARIANT_ORDER.find(([k]) => k === key) || [key, key, "orange", ""];
  const [orderKey, badge, badgeClass, description] = meta;
  const expanded = state.expandedRoute === key;
  const selected = state.selectedVariant === key;
  const byZone = {};
  for (const s of variant.sorties) {
    byZone[s.zone] = byZone[s.zone] || { model: s.model, type: s.survey_type, time: 0, sorties: 0 };
    byZone[s.zone].time += s.duration_min;
    byZone[s.zone].sorties += 1;
    byZone[s.zone].type = s.survey_type;
  }
  const workRows = Object.entries(byZone).map(([zone, w]) => [
    zone,
    `${TYPE_LABELS[w.type] || w.type} · ${w.model}`,
    `${Math.round(w.time)} мин`,
    `${w.sorties} вылет${w.sorties > 1 ? "а" : ""}`,
  ]);
  return `<article class="route-card ${key === "recommended" ? "recommended" : ""} ${selected ? "selected" : ""} ${expanded ? "expanded" : ""}" data-variant="${key}"><div class="route-primary"><div class="route-copy"><div class="route-heading"><strong>${variant.metrics.uavs_used} БВС · ${variant.metrics.sorties} вылетов</strong><span class="route-badge ${badgeClass}">${badge}</span></div><p>${description} ${selected ? "· показан на карте" : ""}</p><div class="metrics"><b>${fmtMin(variant.metrics.total_time_min)}</b><b>${fmtMin(variant.metrics.total_flight_min)} налёт</b><button data-expand="${key}">Подробнее ${icon("chevron", 14)}</button></div></div><div class="route-buttons"><button class="download-btn" data-download="${key}">${icon("download", 15)} Скачать задание</button><button class="select-btn" data-select="${key}">${selected ? "На карте ✓" : "Показать"}</button></div></div>${expanded ? `<div class="route-work"><h4>Состав работ</h4>${workRows.map((row) => `<div class="work-row"><span><strong>${row[0]}</strong><small>${row[1]}</small></span><span><b>${row[2]}</b><small>время работы</small></span><span><b>${row[3]}</b><small>план</small></span></div>`).join("")}</div>` : ""}</article>`;
}

function completionModal() {
  if (!state.completion) return "";
  const downloading = state.completion === "download";
  return `<div class="modal-backdrop"><section class="thanks-modal"><div class="thanks-icon">${icon(downloading ? "download" : "flag", 22)}</div><h2>${downloading ? "Задание сформировано" : "Вариант выбран"}</h2><p>${downloading ? "Полётное задание (GeoJSON) выгружено: маршруты, этапы, высоты, скорость и расписание." : "Маршрут выбранного варианта показан на карте."}</p><div class="demo-summary"><strong>Итоги расчёта:</strong><ul>${summaryList()}</ul></div><button class="btn btn-primary btn-wide" data-action="close-completion">Вернуться к вариантам маршрута</button></section></div>`;
}

function summaryList() {
  const r = state.mission && state.mission.result && state.mission.result.status === "success" ? state.mission.result : null;
  const m = r ? r.variants[state.selectedVariant] : null;
  if (!m) return ["<li>Расчёт ещё не завершён</li>"];
  return [
    `<li>Время до посадки последнего БВС: ${fmtMin(m.metrics.total_time_min)}</li>`,
    `<li>Суммарный налёт: ${fmtMin(m.metrics.total_flight_min)}</li>`,
    `<li>БВС задействовано: ${m.metrics.uavs_used}, вылетов: ${m.metrics.sorties}</li>`,
  ];
}

function resultsScreen() {
  const mission = state.mission;
  const variants = mission && mission.result && mission.result.status === "success" ? mission.result.variants : {};
  const cards = VARIANT_ORDER.filter(([k]) => variants[k]).map(([k]) => routeCard(variants[k], k)).join("");
  const empty = Object.keys(variants).length === 0;
  return `<div class="app">${header(2)}<main class="results-page"><div class="results-title"><h1>Варианты маршрута</h1><span>${empty ? "выполните расчёт" : `MILP подготовил ${Object.keys(variants).length} вариант(а)`} · GSD ${state.resolution} м/пикс · ветер ${state.wind} км/ч</span></div><div class="results-grid"><section class="results-left">${mapSurface(true)}${demoPanel(true)}</section><aside class="routes-panel">${empty ? '<div class="demo-panel"><h3>Нет вариантов</h3><p>Вернитесь в настройку и выполните расчёт.</p></div>' : cards}<div class="improve"><span><strong>Совет</strong><small>Сравните «мин. время» и «мин. налёт»: первый быстрее, второй экономит ресурс техники.</small></span><button data-action="back-settings">Изменить параметры</button></div></aside>${aiPanel()}</div></main>${completionModal()}</div>`;
}

/* ---------------- Симуляция полёта (шаг 3) ---------------- */

function havM(a, b) {
  const R = 6371000, toR = Math.PI / 180;
  const dLat = (b[1] - a[1]) * toR, dLon = (b[0] - a[0]) * toR;
  const s = Math.sin(dLat / 2) ** 2 + Math.cos(a[1] * toR) * Math.cos(b[1] * toR) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}

function currentVariant() {
  const m = state.mission;
  if (!m || !m.result || m.result.status !== "success") return null;
  return m.result.variants[state.selectedVariant] || null;
}

// Позиция и этап БВС в момент t (минут после старта его вылета)
function uavStateAt(s, t) {
  const route = s.route;
  const lens = [];
  let total = 0;
  for (let i = 0; i < route.length - 1; i++) { const d = havM(route[i], route[i + 1]); lens.push(d); total += d; }
  if (t <= 0) return { stage: "На ВПП", stageCls: "", progress: 0, pos: route[0] };
  if (t >= s.duration_min) return { stage: "Завершён", stageCls: "done", progress: 1, pos: route[route.length - 1] };
  const dist = (t / s.duration_min) * total;
  let acc = 0, pos = route[0];
  for (let i = 0; i < lens.length; i++) {
    if (acc + lens[i] >= dist) {
      const f = lens[i] > 0 ? (dist - acc) / lens[i] : 0;
      pos = [route[i][0] + (route[i + 1][0] - route[i][0]) * f, route[i][1] + (route[i + 1][1] - route[i][1]) * f];
      break;
    }
    acc += lens[i];
    pos = route[i + 1];
  }
  const dGo = lens[0], dBack = lens[lens.length - 1], dSurvey = Math.max(total - dGo - dBack, 0);
  let stage, stageCls;
  if (dist < dGo) { stage = "Подлёт"; stageCls = ""; }
  else if (dist < dGo + dSurvey) { stage = "Съёмка"; stageCls = "survey"; }
  else { stage = "Возврат"; stageCls = ""; }
  return { stage, stageCls, progress: dist / total, pos };
}

function fleetBatteryPct(name) {
  const u = state.fleet.find((x) => x.name === name);
  return u ? u.battery_pct : 100;
}

function variantColorOf(variant) {
  return (name) => {
    const uavs = [...new Set(variant.sorties.map((s) => s.uav))];
    return UAV_COLORS[uavs.indexOf(name) % UAV_COLORS.length];
  };
}

function flightCardHtml(s, st, batt) {
  const state_ = st || uavStateAt(s, state.flight.t - s.start_min);
  const battVal = batt ?? Math.max(fleetBatteryPct(s.uav) - state_.progress * s.battery_used_pct, 0);
  const pct = Math.round(state_.progress * 100);
  return `<div class="flight-card"><div class="fc-head"><span>${s.uav} → ${s.zone}</span><span class="fc-stage ${state_.stageCls}">${state_.stage}</span></div>
    <div class="fc-zone">${s.model} · ${s.payload} · старт T+${Math.round(s.start_min)} мин · ${Math.round(s.duration_min)} мин</div>
    <div class="fc-bar"><i style="width:${pct}%"></i></div>
    <div class="fc-foot"><span>прогресс ${pct}%</span><span>батарея ${Math.round(battVal)}%</span></div></div>`;
}

function flightScreen() {
  const v = currentVariant();
  return `<div class="app">${header(3)}<main class="results-page"><div class="results-title"><h1>Полёт: ${v.title}</h1><span>готовность ${fmtMin(v.metrics.total_time_min)} · налёт ${fmtMin(v.metrics.total_flight_min)} · ${v.metrics.uavs_used} БВС · ${v.metrics.sorties} вылетов</span></div>
  <div class="results-grid"><section class="results-left">${mapSurface(true)}
    <div class="flight-bar">
      <button class="btn-ghost" data-action="flight-toggle">${state.flight.playing ? "⏸ Пауза" : "▶ Пуск"}</button>
      <button class="btn-ghost" data-action="flight-reset">⟲ Сброс</button>
      <span class="flight-scale">${[2, 5, 10].map((n) => `<button data-flight-scale="${n}" class="${state.flight.scale === n ? "active" : ""}">×${n}</button>`).join("")}</span>
      <b id="flight-time" class="flight-time">T+${state.flight.t.toFixed(1)} мин</b>
    </div></section>
    <aside class="routes-panel"><div class="flight-cards" id="flight-cards">${v.sorties.map((s) => flightCardHtml(s)).join("")}</div></aside>
    ${aiPanel()}</div></main></div>`;
}

let flightTimer = null;
function stopFlightTimer() {
  if (flightTimer) { clearInterval(flightTimer); flightTimer = null; }
}
function startFlightTimer() {
  stopFlightTimer();
  flightTimer = setInterval(() => {
    if (!state.flight.playing) return;
    state.flight.t += 0.1 * state.flight.scale;
    const v = currentVariant();
    if (v && state.flight.t >= v.metrics.total_time_min) {
      state.flight.t = v.metrics.total_time_min;
      state.flight.playing = false;
    }
    updateFlightUI();
  }, 100);
}
function updateFlightUI() {
  const v = currentVariant();
  if (!v) return;
  const t = state.flight.t;
  const timeEl = document.getElementById("flight-time");
  if (timeEl) timeEl.textContent = `T+${t.toFixed(1)} мин`;
  const colorOf = variantColorOf(v);
  const feats = [];
  const cards = v.sorties.map((s) => {
    const st = uavStateAt(s, t - s.start_min);
    const batt = Math.max(fleetBatteryPct(s.uav) - st.progress * s.battery_used_pct, 0);
    feats.push({ type: "Feature", properties: { name: s.uav, color: colorOf(s.uav) }, geometry: { type: "Point", coordinates: st.pos } });
    return flightCardHtml(s, st, batt);
  });
  const cardsEl = document.getElementById("flight-cards");
  if (cardsEl) cardsEl.innerHTML = cards.join("");
  setMapSource("flight-uavs", { type: "FeatureCollection", features: feats });
  const btn = document.querySelector('[data-action="flight-toggle"]');
  if (btn) btn.textContent = state.flight.playing ? "⏸ Пауза" : "▶ Пуск";
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function renderAiMarkdown(text) {
  const html = marked.parse(String(text || ""), { gfm: true, breaks: true });
  return DOMPurify.sanitize(html);
}

function render() {
  document.documentElement.dataset.screen = state.screen;
  root.innerHTML =
    state.screen === "login" ? loginScreen() : state.screen === "setup" ? setupScreen() : state.screen === "flight" ? flightScreen() : resultsScreen();
  attachMap();
  if (state.screen === "results") loadRoutesOnMap();
  if (state.screen === "flight") {
    loadRoutesOnMap();
    updateFlightUI();
  }
  const aiMsgs = root.querySelector(".ai-messages");
  if (aiMsgs) aiMsgs.scrollTop = aiMsgs.scrollHeight;
}

function go(screen) {
  if (screen === "flight") {
    const v = currentVariant();
    if (!v) return notify("Сначала выполните расчёт и выберите вариант на экране «Результаты»");
    stopFlightTimer();
    state.flight.t = 0;
    state.flight.playing = true;
    state.screen = "flight";
    state.fleetOpen = false;
    render();
    startFlightTimer();
    return;
  }
  if (screen !== "flight") stopFlightTimer();
  if (screen !== "flight") state.flight.playing = false;
  state.screen = screen;
  state.fleetOpen = false;
  state.fleetMenu = null;
  render();
}

/* ---------------- Логика ---------------- */

async function ensureSession() {
  if (!state.token) return false;
  try {
    state.user = await api("/auth/me/");
  } catch {
    return false;
  }
  try {
    const projects = await api("/projects/");
    if (projects.length) {
      state.project = projects[0];
    } else {
      state.project = await api("/projects/", { method: "POST", body: { name: "Геоскан Москва" } });
    }
    const data = await api(`/projects/${state.project.id}/data/`);
    state.zonesData = data;
    state.dataLoaded = data.zones.features.length > 0;
    state.pointsLoaded = data.vpps.features.length > 0;
    state.areaLoaded = data.zones.features.some((f) => (f.properties || {}).kind === "survey");
    if (state.dataLoaded) {
      state.fleet = await api(`/projects/${state.project.id}/fleet/`);
    }
    state.screen = "setup";
  } catch (e) {
    notify(`Ошибка загрузки проекта: ${e.message}`);
    state.project = null;
  }
  return true;
}

async function doLogin(username, password, register, email) {
  try {
    if (register) {
      await api("/auth/register/", { method: "POST", body: { username, password, email: email || `${username}@geoscan.local` } });
    }
    const tokens = await api("/auth/login/", { method: "POST", body: { username, password } });
    state.token = tokens.access;
    localStorage.setItem("gs_token", tokens.access);
    const ok = await ensureSession();
    if (ok) {
      render();
      loadProjectMapData();
      notify(register ? "Аккаунт создан, добро пожаловать!" : "Вход выполнен");
    }
  } catch (e) {
    notify(`Ошибка входа: ${e.message}`);
  }
}

async function loadDemo() {
  if (!state.project) return;
  try {
    await api(`/projects/${state.project.id}/load_demo/`, { method: "POST" });
    const data = await api(`/projects/${state.project.id}/data/`);
    state.zonesData = data;
    state.dataLoaded = true;
    state.pointsLoaded = true;
    state.areaLoaded = true;
    state.fleet = await api(`/projects/${state.project.id}/fleet/`);
    render();
    loadProjectMapData();
    notify("Демо-сценарий загружен: 6 зон, 2 запрета, 6 ВПП");
  } catch (e) {
    notify(`Ошибка загрузки демо: ${e.message}`);
  }
}

async function uploadFile(kind, file) {
  if (!state.project) return;
  try {
    const text = await file.text();
    const fc = JSON.parse(text);
    if (kind === "points") {
      await api(`/projects/${state.project.id}/load_data/`, {
        method: "POST",
        body: { zones: state.zonesData ? state.zonesData.zones : emptyFC(), vpps: fc },
      });
      state.pointsLoaded = true;
      notify(`ВПП загружены: ${fc.features.length} площадок`);
    } else {
      for (const f of fc.features) {
        const p = f.properties || (f.properties = {});
        if (!p.kind) p.kind = "survey";
        if (p.kind === "survey" && !p.survey_type) p.survey_type = "visible";
      }
      await api(`/projects/${state.project.id}/load_data/`, {
        method: "POST",
        body: { zones: fc, vpps: state.zonesData ? state.zonesData.vpps : emptyFC() },
      });
      state.areaLoaded = true;
      notify(`Область загружена: ${fc.features.length} зон`);
    }
    const data = await api(`/projects/${state.project.id}/data/`);
    state.zonesData = data;
    state.dataLoaded = data.zones.features.length > 0;
    if (state.fleet.length === 0) state.fleet = await api(`/projects/${state.project.id}/fleet/`);
    render();
    loadProjectMapData();
  } catch (e) {
    notify(`Ошибка загрузки файла: ${e.message}`);
  }
}

async function calculate() {
  if (!state.project || state.calculating) return;
  state.calculating = true;
  render();
  try {
    const activeIds = state.fleet.filter((u) => !state.excluded.has(u.id)).map((u) => u.id);
    const body = {
      gsd: Number(state.resolution) || 3,
      wind_kmh: Number(state.wind) || 0,
      active_uav_ids: activeIds,
      survey_types: state.type === "all" ? null : [state.type],
    };
    const created = await api(`/projects/${state.project.id}/missions/`, { method: "POST", body });
    let mission = null;
    for (let i = 0; i < 80; i++) {
      await new Promise((r) => setTimeout(r, 1500));
      mission = await api(`/missions/${created.id}/`);
      if (["success", "infeasible", "error"].includes(mission.status)) break;
    }
    state.mission = mission;
    state.calculating = false;
    if (mission.status === "success") {
      state.selectedVariant = "recommended";
      go("results");
      notify(`Расчёт готов: ${mission.result.variants.recommended.metrics.uavs_used} БВС, ${fmtMin(mission.result.variants.recommended.metrics.total_time_min)}`);
    } else {
      const reason = (mission.result && (mission.result.reasons || [])[0]) || mission.status;
      notify(`Расчёт: ${reason}`);
    }
    render();
  } catch (e) {
    state.calculating = false;
    render();
    notify(`Ошибка расчёта: ${e.message}`);
  }
}

async function downloadTask() {
  if (!state.mission) return;
  try {
    const fc = await api(`/missions/${state.mission.id}/export/`);
    const blob = new Blob([JSON.stringify(fc, null, 2)], { type: "application/geo+json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "flight-task.geojson";
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 800);
    state.completion = "download";
    render();
  } catch (e) {
    notify(`Ошибка экспорта: ${e.message}`);
  }
}

async function sendAi() {
  const input = root.querySelector("#ai-question");
  const text = input?.value.trim();
  if (!text || state.aiBusy) return;
  input.value = "";
  state.aiHistory.push({ role: "user", content: text });
  state.aiBusy = true;
  render();
  try {
    const res = await api("/chat/", {
      method: "POST",
      body: {
        message: text,
        history: state.aiHistory.slice(0, -1).slice(-10),
        project_id: state.project ? state.project.id : null,
      },
    });
    state.aiHistory.push({ role: "assistant", content: res.response || "…" });
    if (res.map_data_list && res.map_data_list.length) {
      const fc = res.map_data_list.find((d) => d.type === "routes")?.data;
      if (fc) {
        const feats = (fc.features || []).filter((f) => f.properties && f.properties.kind === "route");
        const uavs = [...new Set(feats.map((f) => f.properties.uav))];
        const colorOf = (name) => UAV_COLORS[uavs.indexOf(name) % UAV_COLORS.length];
        const transit = [];
        const gals = [];
        for (const f of feats) {
          const { transit: t, gals: g } = splitRoute(f.geometry.coordinates, colorOf(f.properties.uav), { uav: f.properties.uav, zone: f.properties.zone });
          transit.push(...t);
          gals.push(...g);
        }
        setMapSource("routes-transit", { type: "FeatureCollection", features: transit });
        setMapSource("routes-gals", { type: "FeatureCollection", features: gals });
      }
    }
  } catch (e) {
    state.aiHistory.push({ role: "assistant", content: `Ошибка: ${e.message}` });
  }
  state.aiBusy = false;
  render();
}

/* ---------------- События ---------------- */

root.addEventListener("submit", (event) => {
  if (event.target.id === "login-form") {
    event.preventDefault();
    const username = root.querySelector("#nickname").value.trim();
    const password = root.querySelector("#password").value;
    const email = root.querySelector("#email")?.value.trim();
    doLogin(username, password, state.registerMode, email);
  }
});

root.addEventListener("input", (event) => {
  if (event.target.id === "resolution") state.resolution = Number(event.target.value) || 1;
  if (event.target.id === "wind") state.wind = Number(event.target.value) || 0;
});

root.addEventListener("click", (event) => {
  const button = event.target.closest("button, .create-account");
  if (!button) return;

  if (button.dataset.screen) {
    if (button.dataset.screen === "results" && !state.dataLoaded) return notify("Сначала загрузите данные (демо-сценарий или файлы).");
    if (button.dataset.screen === "results" && (!state.mission || state.mission.result?.status !== "success")) return notify("Сначала выполните расчёт.");
    if (button.dataset.screen === "flight" && (!state.mission || state.mission.result?.status !== "success")) return notify("Сначала выполните расчёт и выберите вариант.");
    return go(button.dataset.screen);
  }
  if (button.dataset.flightScale) {
    state.flight.scale = Number(button.dataset.flightScale);
    render();
    return;
  }
  if (button.dataset.resolution) {
    state.resolution = Number(button.dataset.resolution);
    return render();
  }
  if (button.dataset.type) {
    state.type = button.dataset.type;
    return render();
  }
  if (button.dataset.message) {
    const input = root.querySelector("#ai-question");
    if (input) input.value = button.dataset.message;
    return sendAi();
  }
  if (button.dataset.droneMenu) {
    state.fleetMenu = Number(button.dataset.droneMenu);
    return render();
  }
  if (button.dataset.toggleDrone) {
    const id = Number(button.dataset.toggleDrone);
    state.excluded.has(id) ? state.excluded.delete(id) : state.excluded.add(id);
    state.fleetMenu = null;
    return render();
  }
  if (button.dataset.expand) {
    state.expandedRoute = state.expandedRoute === button.dataset.expand ? null : button.dataset.expand;
    return render();
  }
  if (button.dataset.download) return downloadTask();
  if (button.dataset.select) {
    state.selectedVariant = button.dataset.select;
    loadRoutesOnMap();
    state.completion = "select";
    return render();
  }

  switch (button.dataset.action) {
    case "toggle-register":
      state.registerMode = !state.registerMode;
      render();
      break;
    case "logout":
      logout();
      break;
    case "load-demo":
      loadDemo();
      break;
    case "choose-points":
      root.querySelector("#file-points")?.click();
      break;
    case "choose-area":
      root.querySelector("#file-area")?.click();
      break;
    case "toggle-fleet":
      state.fleetOpen = !state.fleetOpen;
      state.fleetMenu = null;
      render();
      break;
    case "close-fleet":
      state.fleetOpen = false;
      render();
      break;
    case "calculate":
      calculate();
      break;
    case "back-settings":
      go("setup");
      break;
    case "close-completion":
      state.completion = null;
      render();
      break;
    case "send-ai":
      sendAi();
      break;
    case "flight-toggle":
      state.flight.playing = !state.flight.playing;
      if (state.flight.playing) startFlightTimer();
      updateFlightUI();
      break;
    case "flight-reset":
      state.flight.t = 0;
      state.flight.playing = false;
      updateFlightUI();
      break;
    case "zoom-in":
      map && map.zoomIn();
      break;
    case "zoom-out":
      map && map.zoomOut();
      break;
    case "zoom-reset":
      if (map) loadProjectMapData();
      break;
  }
});

root.addEventListener("change", (event) => {
  if (event.target.id === "file-points" && event.target.files[0]) uploadFile("points", event.target.files[0]);
  if (event.target.id === "file-area" && event.target.files[0]) uploadFile("area", event.target.files[0]);
});

/* ---------------- Старт ---------------- */

(async () => {
  if (state.token && (await ensureSession())) {
    render();
    loadProjectMapData();
  } else {
    state.token = null;
    render();
  }
})();

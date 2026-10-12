const UAV_COLOR = {
  1: "#d64545",
  2: "#2f6fdb",
  3: "#2e9b57",
  4: "#8a4ad1",
  5: "#e07b00",
  6: "#0097a7",
  7: "#6d4c41",
  8: "#c2185b",
  9: "#455a64",
};

const TYPE_LABEL = {
  visible: "видимый",
  multispectral: "мультиспектр",
  thermal: "тепловизор",
};

const drawSource = new ol.source.Vector();
const resultSource = new ol.source.Vector();
const drawLayer = new ol.layer.Vector({ source: drawSource, style: styleDraw });
const resultLayer = new ol.layer.Vector({ source: resultSource, style: styleResult });

const VIEW_AREA_M2 = 100 * 1000 * 1000;

const map = new ol.Map({
  target: "map",
  layers: [
    new ol.layer.Tile({ source: new ol.source.OSM() }),
    drawLayer,
    resultLayer,
  ],
  controls: ol.control.defaults.defaults({ zoom: false, rotate: false }),
  interactions: ol.interaction.defaults.defaults({
    altShiftDragRotate: false,
    doubleClickZoom: false,
    keyboard: false,
    mouseWheelZoom: false,
    pinchRotate: false,
    pinchZoom: false,
    shiftDragZoom: false,
  }),
  view: new ol.View({
    center: ol.proj.fromLonLat([37.62, 55.75]),
    enableRotation: false,
    constrainResolution: false,
  }),
});

const extentLabel = document.getElementById("map-extent");
let lockingExtent = false;

function lockViewArea() {
  if (lockingExtent) {
    return;
  }
  const size = map.getSize();
  const view = map.getView();
  const center = view.getCenter();
  if (!size || size[0] < 2 || size[1] < 2 || !center) {
    return;
  }
  const latitude = ol.proj.toLonLat(center)[1] * Math.PI / 180;
  const scale = Math.abs(Math.cos(latitude));
  if (scale < 1e-6) {
    return;
  }
  const resolution = Math.sqrt(VIEW_AREA_M2 / (size[0] * size[1])) / scale;
  const widthKm = (resolution * size[0] * scale) / 1000;
  const heightKm = (resolution * size[1] * scale) / 1000;
  extentLabel.textContent = `100 км², ${kmText(widthKm)} × ${kmText(heightKm)} км`;
  const current = view.getResolution();
  if (current && Math.abs(current - resolution) / resolution < 1e-5) {
    return;
  }
  lockingExtent = true;
  view.setResolution(resolution);
  lockingExtent = false;
}

function kmText(value) {
  return value.toFixed(1).replace(".", ",");
}

map.on("change:size", lockViewArea);
map.on("moveend", lockViewArea);
map.getView().on("change:resolution", lockViewArea);
lockViewArea();

const select = new ol.interaction.Select({ layers: [drawLayer] });
map.addInteraction(select);

const viewport = map.getViewport();
map.on("pointerdrag", () => {
  viewport.classList.add("is-panning");
});
map.on("pointerup", () => {
  viewport.classList.remove("is-panning");
});

let draw = null;
let mode = { kind: "vpp", vpp: 1 };
let polygonSeq = 0;
let zoneSeq = 0;
let polygonVertices = 0;
let lastVertex = null;
let activeZone = null;
let forbiddenPattern = null;

let config = null;

const statusNode = document.getElementById("status");
const solveButton = document.getElementById("solve");
const errorNode = document.getElementById("form-error");

document.getElementById("export-vpp-geojson").addEventListener("click", () => {
  downloadText("vpp.geojson", geojsonText(vppFeatures()), "application/geo+json");
});
document.getElementById("export-vpp-kml").addEventListener("click", () => {
  downloadText("vpp.kml", kmlText("ВПП", vppFeatures()), "application/vnd.google-earth.kml+xml");
});
document.getElementById("export-poly-geojson").addEventListener("click", () => {
  downloadText("polygons.geojson", geojsonText(polygonFeatures()), "application/geo+json");
});
document.getElementById("export-poly-kml").addEventListener("click", () => {
  downloadText("polygons.kml", kmlText("Полигоны", polygonFeatures()), "application/vnd.google-earth.kml+xml");
});
bindFileLoad("load-vpp-button", "load-vpp", loadVppText);
bindFileLoad("load-poly-button", "load-poly", loadPolygonText);

solveButton.addEventListener("click", solve);
document.getElementById("criteria").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-mode]");
  if (!button || !shownResult) {
    return;
  }
  selectCriterion(button.dataset.mode);
});
loadConfig();

function activateDraw() {
  if (draw) {
    draw.abortDrawing();
    map.removeInteraction(draw);
    draw = null;
  }
  polygonVertices = 0;
  lastVertex = null;
  if (mode.kind === "select") {
    return;
  }
  const drawingPolygon = mode.kind === "polygon" || mode.kind === "forbidden";
  draw = new ol.interaction.Draw({
    source: drawSource,
    type: drawingPolygon ? "Polygon" : "Point",
    style: mode.kind === "forbidden" ? forbiddenSketchStyle : undefined,
    condition: function () {
      return false;
    },
  });
  draw.on("drawend", onDrawEnd);
  map.addInteraction(draw);
}

function addPolygonVertex(coordinate) {
  draw.appendCoordinates([coordinate]);
  polygonVertices += 1;
  lastVertex = coordinate.slice();
}

function releaseForbiddenDraft() {
  if (mode.kind !== "forbidden") {
    return;
  }
  if (polygonVertices >= 3 && draw) {
    draw.finishDrawing();
  } else if (polygonVertices > 0 && draw) {
    draw.abortDrawing();
    polygonVertices = 0;
    lastVertex = null;
  }
  activeZone = null;
}

function finishForbiddenZone() {
  if (polygonVertices > 0 && polygonVertices < 3) {
    showError("В контуре нужны хотя бы три точки.");
    return;
  }
  const hadZone = Boolean(activeZone) || polygonVertices >= 3;
  if (!hadZone) {
    showError("Сначала нарисуйте контур запретной зоны.");
    return;
  }
  if (polygonVertices >= 3 && draw) {
    draw.finishDrawing();
  }
  activeZone = null;
  showError("");
  refreshStatus();
}

function appendForbiddenPart(ring) {
  if (!ring || ring.length < 4) {
    return;
  }
  if (!activeZone) {
    zoneSeq += 1;
    activeZone = new ol.Feature(new ol.geom.MultiPolygon([]));
    activeZone.set("kind", "forbidden");
    activeZone.set("zid", "z" + zoneSeq);
    activeZone.set("name", "Запрет " + zoneSeq);
    drawSource.addFeature(activeZone);
  }
  const parts = activeZone.getGeometry().getCoordinates();
  parts.push([ring]);
  activeZone.getGeometry().setCoordinates(parts);
  activeZone.changed();
}

function forbiddenHatch() {
  if (forbiddenPattern) {
    return forbiddenPattern;
  }
  const canvas = document.createElement("canvas");
  canvas.width = 12;
  canvas.height = 12;
  const context = canvas.getContext("2d");
  context.strokeStyle = "rgba(176, 24, 24, 0.95)";
  context.lineWidth = 2;
  context.beginPath();
  context.moveTo(0, 12);
  context.lineTo(12, 0);
  context.moveTo(-2, 2);
  context.lineTo(2, -2);
  context.moveTo(10, 14);
  context.lineTo(14, 10);
  context.stroke();
  forbiddenPattern = context.createPattern(canvas, "repeat");
  return forbiddenPattern;
}

function forbiddenSketchStyle() {
  return new ol.style.Style({
    stroke: new ol.style.Stroke({ color: "rgba(176, 24, 24, 0.95)", width: 2 }),
    fill: new ol.style.Fill({ color: forbiddenHatch() }),
    image: new ol.style.Circle({
      radius: 4,
      fill: new ol.style.Fill({ color: "#b01818" }),
    }),
  });
}

function awayFromLast(coordinate, pixel) {
  if (!lastVertex) {
    return true;
  }
  const lastPixel = map.getPixelFromCoordinate(lastVertex);
  const dx = pixel[0] - lastPixel[0];
  const dy = pixel[1] - lastPixel[1];
  return dx * dx + dy * dy > 64;
}

function onDrawEnd(event) {
  const feature = event.feature;
  if (mode.kind === "vpp") {
    feature.set("kind", "vpp");
    feature.set("vpp", mode.vpp);
    const stale = drawSource
      .getFeatures()
      .filter((item) => item !== feature && item.get("kind") === "vpp" && item.get("vpp") === mode.vpp);
    stale.forEach((item) => drawSource.removeFeature(item));
  } else if (mode.kind === "forbidden") {
    const ring = feature.getGeometry().getCoordinates()[0];
    drawSource.removeFeature(feature);
    appendForbiddenPart(ring);
    polygonVertices = 0;
    lastVertex = null;
  } else {
    polygonSeq += 1;
    feature.set("kind", "polygon");
    feature.set("surveyType", document.querySelector('input[name="ptype"]:checked').value);
    feature.set("pid", "p" + polygonSeq);
  }
  clearResults();
  window.setTimeout(() => {
    refreshStatus();
    activateDraw();
  }, 0);
}

function loadConfig() {
  fetch("/api/config")
    .then((response) => response.json())
    .then((payload) => {
      config = payload || {};
      if (payload && payload.resolution != null) {
        document.getElementById("resolution").value = payload.resolution;
      }
      refreshStatus();
    })
    .catch(() => refreshStatus());
}

function renderLegend() {
  const root = document.getElementById("legend");
  root.replaceChildren();
  if (!config) {
    return;
  }
  root.append(legendMark("dash", "без назначения"));
  root.append(legendMark("route", "маршрут"));
  const seen = new Set();
  for (const unit of config.fleet) {
    if (seen.has(unit.name)) {
      continue;
    }
    seen.add(unit.name);
    const item = document.createElement("span");
    item.className = "key";
    const swatch = document.createElement("i");
    swatch.className = "swatch";
    swatch.style.background = uavColor(unit.index);
    const name = document.createElement("span");
    name.textContent = legendName(unit);
    const pad = document.createElement("span");
    pad.className = "pad";
    pad.textContent = "на всех ВПП";
    item.append(swatch, name, pad);
    root.append(item);
  }
}

function uavColor(index) {
  if (!index) {
    return "#9a9a9a";
  }
  const kit = config && config.fleet && config.fleet.length > 6
    ? config.fleet.length / 6
    : 9;
  const slot = ((index - 1) % kit) + 1;
  return UAV_COLOR[slot] || "#204070";
}

function legendMark(kind, label) {
  const item = document.createElement("span");
  item.className = "key";
  const swatch = document.createElement("i");
  swatch.className = "swatch " + kind;
  const name = document.createElement("span");
  name.textContent = label;
  item.append(swatch, name);
  return item;
}

function legendName(unit) {
  const parts = unit.name.split(" / ");
  const model = parts[0] || unit.name;
  const camera = (parts[1] || "").replace(/^Geoscan |^DSC-/, "");
  if (model.includes("801")) {
    return "Геоскан 801";
  }
  const shortModel = model.replace("Геоскан ", "");
  return camera ? shortModel + " " + camera : shortModel;
}

function solve() {
  showError("");
  solveButton.disabled = true;
  fetch("/api/solve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload()),
  })
    .then(async (response) => {
      const body = await response.json();
      if (!response.ok) {
        throw new Error(body.error || "Расчёт не выполнен.");
      }
      return body;
    })
    .then(showResult)
    .catch((error) => showError(error.message))
    .finally(refreshStatus);
}

function payload() {
  const vpps = [];
  const polygons = [];
  const forbidden = [];
    for (const feature of drawSource.getFeatures()) {
      if (feature.get("kind") === "vpp") {
        const [lon, lat] = ol.proj.toLonLat(feature.getGeometry().getCoordinates());
        vpps.push({ index: feature.get("vpp"), lon: lon, lat: lat });
      }
      if (feature.get("kind") === "polygon") {
        polygons.push({
          id: feature.get("pid"),
          survey_type: feature.get("surveyType"),
          ring: feature.getGeometry().getCoordinates()[0].map((coordinate) => ol.proj.toLonLat(coordinate)),
        });
      }
      if (feature.get("kind") === "forbidden") {
        const geometry = feature.getGeometry();
        const parts = geometry.getType() === "MultiPolygon" ? geometry.getPolygons() : [geometry];
        for (const part of parts) {
          forbidden.push({
            name: feature.get("name") || "Запрет",
            ring: part.getCoordinates()[0].map((coordinate) => ol.proj.toLonLat(coordinate)),
          });
        }
      }
    }
    return {
      resolution: Number(document.getElementById("resolution").value),
      vpps: vpps,
      polygons: polygons,
      forbidden: forbidden,
    };
}

let shownResult = null;
let shownScenario = "time";

function showResult(result) {
  shownResult = result;
  shownScenario = "time";
  document.getElementById("criteria").hidden = false;
  renderPlan(result);
  selectCriterion("time");
}

function selectCriterion(modeId) {
  shownScenario = modeId;
  const mode = (shownResult && shownResult.modes || []).find((item) => item.id === modeId);
  drawPaths(mode ? mode.paths || [] : []);
  for (const button of document.querySelectorAll("#criteria button")) {
    button.classList.toggle("active", button.dataset.mode === modeId);
  }
  for (const section of document.querySelectorAll("#table-wrap section")) {
    section.classList.toggle("active", section.dataset.mode === modeId);
  }
  const note = document.getElementById("map-note");
  if (note && mode) {
    note.textContent = "На карте маршрут «" + mode.title.toLowerCase()
      + "»: сплошные линии — галсы, пунктир — перелёт с ВПП и обратно, точки — перегон между галсами.";
  }
}

function drawPaths(paths) {
  resultSource.clear();
  const legend = document.getElementById("legend");
  legend.replaceChildren();
  const seen = new Set();
  for (const path of paths) {
    if (!seen.has(path.unit)) {
      seen.add(path.unit);
      const item = document.createElement("span");
      item.className = "key";
      const swatch = document.createElement("i");
      swatch.className = "swatch";
      swatch.style.background = path.color;
      const name = document.createElement("span");
      name.textContent = path.unit;
      item.append(swatch, name);
      legend.append(item);
    }
    addRouteLines(path.transit, "route", path.color);
    addRouteLines(path.transfers, "transfer", path.color);
    addRouteLines(path.lines, "gall", path.color);
  }
  legend.append(legendMark("route", "перелёт с ВПП и обратно"));
  legend.append(legendMark("transfer", "перегон между галсами"));
}

function addRouteLines(segments, kind, color) {
  for (const line of segments || []) {
    if (!line || line.length < 2) {
      continue;
    }
    resultSource.addFeature(new ol.Feature({
      geometry: new ol.geom.LineString(line.map((point) => ol.proj.fromLonLat(point))),
      kind: kind,
      color: color,
    }));
  }
}

function unitColors(result) {
  const colors = new Map();
  for (const mode of result.modes || []) {
    for (const path of mode.paths || []) {
      if (path.unit && !colors.has(path.unit)) {
        colors.set(path.unit, path.color);
      }
    }
  }
  return colors;
}

function renderPlan(result) {
  const colors = unitColors(result);
  const wrap = document.getElementById("table-wrap");
  wrap.replaceChildren();
  const note = document.createElement("p");
  note.id = "map-note";
  note.className = "summary";
  wrap.append(note);
  for (const mode of result.modes || []) {
    const block = document.createElement("section");
    block.dataset.mode = mode.id;
    const heading = document.createElement("h2");
    heading.textContent = mode.title;
    block.append(heading);
    const summary = document.createElement("p");
    summary.className = "summary";
    summary.textContent = "T = " + mode.T + " ч, R = " + mode.R + " %";
    block.append(summary);
    if (mode.rows && mode.rows.length) {
      const list = document.createElement("ul");
      list.className = "plan";
      for (const row of mode.rows) {
        const item = document.createElement("li");
        const color = colors.get(row.unit);
        if (color) {
          const swatch = document.createElement("i");
          swatch.className = "swatch square";
          swatch.style.background = color;
          item.append(swatch);
        }
        const text = document.createElement("span");
        text.textContent = row.zone + ": " + row.unit + ", " + row.area + " км²";
        item.append(text);
        list.append(item);
      }
      block.append(list);
    }
    wrap.append(block);
  }
}

function refreshStatus() {
  const vpps = new Set(
    drawSource.getFeatures().filter((feature) => feature.get("kind") === "vpp").map((feature) => feature.get("vpp"))
  );
  const counts = { visible: 0, multispectral: 0, thermal: 0 };
  for (const feature of drawSource.getFeatures()) {
    if (feature.get("kind") === "polygon") {
      counts[feature.get("surveyType")] += 1;
    }
  }
  const regions = counts.visible + counts.multispectral + counts.thermal;
  const zones = drawSource.getFeatures().filter((feature) => feature.get("kind") === "forbidden").length;
  statusNode.textContent =
    "ВПП " + vpps.size + "/6. Видимых " + counts.visible +
    ", мультиспектральных " + counts.multispectral +
    ", тепловизионных " + counts.thermal +
    ". Запретных зон " + zones + ".";
  solveButton.disabled = !(vpps.size >= 1 && regions > 0);
  const hasPads = vpps.size > 0;
  const hasPolygons = regions + zones > 0;
  document.getElementById("export-vpp-geojson").disabled = !hasPads;
  document.getElementById("export-vpp-kml").disabled = !hasPads;
  document.getElementById("export-poly-geojson").disabled = !hasPolygons;
  document.getElementById("export-poly-kml").disabled = !hasPolygons;
}

function clearResults() {
  resultSource.clear();
  document.getElementById("table-wrap").replaceChildren();
  document.getElementById("legend").replaceChildren();
  document.getElementById("criteria").hidden = true;
  shownResult = null;
  shownScenario = "time";
}

function showError(message) {
  errorNode.textContent = message;
}

function formatMin(value) {
  return Number(value).toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatScore(value) {
  return Math.round(Number(value)).toLocaleString("ru-RU");
}

function formatNum(value) {
  return Number(value).toLocaleString("ru-RU", { maximumFractionDigits: 1 });
}

function vppFeatures() {
  return drawSource
    .getFeatures()
    .filter((feature) => feature.get("kind") === "vpp")
    .sort((left, right) => left.get("vpp") - right.get("vpp"))
    .map((feature) => ({
      name: "ВПП-" + feature.get("vpp"),
      properties: { name: "ВПП-" + feature.get("vpp"), vpp: feature.get("vpp") },
      geometry: {
        type: "Point",
        coordinates: lonLat(feature.getGeometry().getCoordinates()),
      },
    }));
}

function polygonFeatures() {
  const features = [];
  for (const feature of drawSource.getFeatures()) {
    if (feature.get("kind") === "polygon") {
      const number = String(feature.get("pid") || "").replace(/^p/, "");
      const name = number ? "Район " + number : "Район";
      features.push({
        name: name,
        properties: {
          name: name,
          kind: "survey",
          survey_type: feature.get("surveyType"),
        },
        geometry: {
          type: "Polygon",
          coordinates: projectRings(feature.getGeometry().getCoordinates()),
        },
      });
    }
    if (feature.get("kind") === "forbidden") {
      const name = feature.get("name") || "Запрет";
      features.push({
        name: name,
        properties: { name: name, kind: "forbidden" },
        geometry: {
          type: "MultiPolygon",
          coordinates: feature.getGeometry().getCoordinates().map(projectRings),
        },
      });
    }
  }
  return features;
}

function projectRings(rings) {
  return rings.map((ring) => ring.map(lonLat));
}

function lonLat(coordinate) {
  const [lon, lat] = ol.proj.toLonLat(coordinate);
  return [Math.round(lon * 1e6) / 1e6, Math.round(lat * 1e6) / 1e6];
}

function geojsonText(features) {
  return JSON.stringify({
    type: "FeatureCollection",
    features: features.map((feature) => ({
      type: "Feature",
      properties: feature.properties,
      geometry: feature.geometry,
    })),
  }, null, 2);
}

function kmlText(title, features) {
  const placemarks = features.map((feature) => {
    return "<Placemark><name>" + xmlEscape(feature.name) + "</name>" +
      kmlGeometry(feature.geometry) + "</Placemark>";
  }).join("");
  return "<?xml version=\"1.0\" encoding=\"UTF-8\"?>" +
    "<kml xmlns=\"http://www.opengis.net/kml/2.2\"><Document><name>" +
    xmlEscape(title) + "</name>" + placemarks + "</Document></kml>";
}

function kmlGeometry(geometry) {
  if (geometry.type === "Point") {
    return "<Point><coordinates>" + kmlCoord(geometry.coordinates) + "</coordinates></Point>";
  }
  if (geometry.type === "Polygon") {
    return kmlPolygon(geometry.coordinates);
  }
  const parts = geometry.coordinates.map((polygon) => kmlPolygon(polygon)).join("");
  return "<MultiGeometry>" + parts + "</MultiGeometry>";
}

function kmlPolygon(rings) {
  let body = "<outerBoundaryIs><LinearRing><coordinates>" +
    rings[0].map(kmlCoord).join(" ") + "</coordinates></LinearRing></outerBoundaryIs>";
  for (const hole of rings.slice(1)) {
    body += "<innerBoundaryIs><LinearRing><coordinates>" +
      hole.map(kmlCoord).join(" ") + "</coordinates></LinearRing></innerBoundaryIs>";
  }
  return "<Polygon>" + body + "</Polygon>";
}

function kmlCoord(pair) {
  return pair[0] + "," + pair[1] + ",0";
}

function xmlEscape(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;");
}

function bindFileLoad(buttonId, inputId, apply) {
  const input = document.getElementById(inputId);
  document.getElementById(buttonId).addEventListener("click", () => {
    input.value = "";
    input.click();
  });
  input.addEventListener("change", () => {
    const file = input.files && input.files[0];
    if (!file) {
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      try {
        apply(String(reader.result || ""));
        showError("");
        clearResults();
        refreshStatus();
      } catch (error) {
        showError(error.message || "Не удалось прочитать файл.");
      }
    };
    reader.readAsText(file);
  });
}

function loadVppText(raw) {
  const pads = readCoordinateFile(raw).pads;
  if (!pads.length) {
    throw new Error("В файле нет точек ВПП.");
  }
  removeDrawn("vpp");
  const byIndex = new Map();
  for (const pad of pads) {
    byIndex.set(pad.index, pad);
  }
  const placed = [];
  for (const pad of byIndex.values()) {
    const feature = new ol.Feature(new ol.geom.Point(ol.proj.fromLonLat([pad.lon, pad.lat])));
    feature.set("kind", "vpp");
    feature.set("vpp", pad.index);
    drawSource.addFeature(feature);
    placed.push([pad.lon, pad.lat]);
  }
  focusCoordinates(placed);
}

function loadPolygonText(raw) {
  const polygons = readCoordinateFile(raw).polygons;
  if (!polygons.length) {
    throw new Error("В файле нет полигонов.");
  }
  if (draw && (mode.kind === "polygon" || mode.kind === "forbidden")) {
    draw.abortDrawing();
    polygonVertices = 0;
    lastVertex = null;
  }
  activeZone = null;
  removeDrawn("polygon");
  removeDrawn("forbidden");
  polygonSeq = 0;
  zoneSeq = 0;
  const placed = [];
  for (const item of polygons) {
    if (item.kind === "forbidden") {
      zoneSeq += 1;
      const feature = new ol.Feature(new ol.geom.MultiPolygon(item.parts.map(toMapRings)));
      feature.set("kind", "forbidden");
      feature.set("zid", "z" + zoneSeq);
      feature.set("name", item.name || "Запрет " + zoneSeq);
      drawSource.addFeature(feature);
    } else {
      polygonSeq += 1;
      const feature = new ol.Feature(new ol.geom.Polygon(toMapRings(item.rings)));
      feature.set("kind", "polygon");
      feature.set("surveyType", item.surveyType);
      feature.set("pid", "p" + polygonSeq);
      drawSource.addFeature(feature);
    }
    for (const ring of item.kind === "forbidden" ? item.parts.flat() : item.rings) {
      placed.push(...ring);
    }
  }
  focusCoordinates(placed);
}

function removeDrawn(kind) {
  drawSource
    .getFeatures()
    .filter((feature) => feature.get("kind") === kind)
    .forEach((feature) => drawSource.removeFeature(feature));
}

function toMapRings(rings) {
  const mapped = (rings || [])
    .filter((ring) => ring && ring.length >= 3)
    .map((ring) => closeRing(ring).map((pair) => ol.proj.fromLonLat(pair)));
  if (!mapped.length) {
    throw new Error("В полигоне меньше трёх вершин.");
  }
  return mapped;
}

function closeRing(ring) {
  if (!ring || ring.length < 3) {
    throw new Error("В полигоне меньше трёх вершин.");
  }
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (first[0] === last[0] && first[1] === last[1]) {
    return ring;
  }
  return ring.concat([[first[0], first[1]]]);
}

function focusCoordinates(lonLats) {
  if (!lonLats.length) {
    return;
  }
  const lon = lonLats.reduce((sum, pair) => sum + pair[0], 0) / lonLats.length;
  const lat = lonLats.reduce((sum, pair) => sum + pair[1], 0) / lonLats.length;
  map.getView().setCenter(ol.proj.fromLonLat([lon, lat]));
  lockViewArea();
}

function readCoordinateFile(raw) {
  const text = String(raw).replace(/^\uFEFF/, "").trim();
  if (!text) {
    throw new Error("Файл пустой.");
  }
  if (text.startsWith("{") || text.startsWith("[")) {
    try {
      return readGeoJson(JSON.parse(text));
    } catch (error) {
      if (error instanceof SyntaxError) {
        throw new Error("Файл не является GeoJSON или KML.");
      }
      throw error;
    }
  }
  const document = new DOMParser().parseFromString(text, "text/xml");
  if (document.querySelector("parsererror")) {
    throw new Error("Файл не является GeoJSON или KML.");
  }
  return readKml(document);
}

function readGeoJson(data) {
  const features = data.type === "FeatureCollection"
    ? data.features || []
    : data.type === "Feature"
      ? [data]
      : [{ type: "Feature", properties: {}, geometry: data }];
  const pads = [];
  const polygons = [];
  for (const feature of features) {
    if (!feature || !feature.geometry) {
      continue;
    }
    const properties = feature.properties || {};
    const geometry = feature.geometry;
    if (geometry.type === "Point") {
      const index = vppIndex(properties);
      const pair = pairOf(geometry.coordinates);
      if (index && pair) {
        pads.push({ index: index, lon: pair[0], lat: pair[1] });
      }
    } else if (geometry.type === "Polygon") {
      const rings = geometry.coordinates.map(ringOf);
      const forbidden = properties.kind === "forbidden";
      polygons.push({
        kind: forbidden ? "forbidden" : "survey",
        name: properties.name || "",
        surveyType: surveyTypeOf(properties),
        rings: rings,
        parts: [rings],
      });
    } else if (geometry.type === "MultiPolygon") {
      const parts = geometry.coordinates.map((polygon) => polygon.map(ringOf));
      if (properties.kind === "survey") {
        for (const rings of parts) {
          polygons.push({
            kind: "survey",
            name: properties.name || "",
            surveyType: surveyTypeOf(properties),
            rings: rings,
            parts: [rings],
          });
        }
      } else {
        polygons.push({
          kind: "forbidden",
          name: properties.name || "",
          surveyType: "visible",
          rings: parts[0] || [],
          parts: parts,
        });
      }
    }
  }
  return { pads: pads, polygons: polygons.filter(validPolygon) };
}

function readKml(document) {
  const pads = [];
  const polygons = [];
  for (const placemark of kmlElements(document, "Placemark")) {
    const name = kmlText(placemark, "name");
    const points = kmlElements(placemark, "Point");
    const polygonNodes = kmlElements(placemark, "Polygon");
    if (points.length && !polygonNodes.length) {
      const pair = kmlPairs(points[0])[0];
      const index = vppIndex({ name: name });
      if (index && pair) {
        pads.push({ index: index, lon: pair[0], lat: pair[1] });
      }
      continue;
    }
    if (!polygonNodes.length) {
      continue;
    }
    const parts = polygonNodes.map((node) => {
      const rings = kmlElements(node, "LinearRing").map((ring) => kmlPairs(ring));
      return rings.filter((ring) => ring.length >= 3);
    }).filter((rings) => rings.length);
    if (!parts.length) {
      continue;
    }
    const forbidden = name.startsWith("Запрет") || parts.length > 1;
    if (forbidden) {
      polygons.push({
        kind: "forbidden",
        name: name,
        surveyType: "visible",
        rings: parts[0],
        parts: parts,
      });
    } else {
      polygons.push({
        kind: "survey",
        name: name,
        surveyType: "visible",
        rings: parts[0],
        parts: parts,
      });
    }
  }
  return { pads: pads, polygons: polygons };
}

function validPolygon(item) {
  const parts = item.kind === "forbidden" ? item.parts : [item.rings];
  return parts.some((rings) => rings && rings[0] && rings[0].length >= 3);
}

function ringOf(ring) {
  return (ring || []).map(pairOf).filter(Boolean);
}

function pairOf(value) {
  if (!value || value.length < 2) {
    return null;
  }
  const lon = Number(value[0]);
  const lat = Number(value[1]);
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) {
    return null;
  }
  return [lon, lat];
}

function vppIndex(properties) {
  const raw = Number(properties.vpp);
  if (raw >= 1 && raw <= 6) {
    return raw;
  }
  const match = String(properties.name || "").match(/ВПП\s*-?\s*([1-6])/);
  return match ? Number(match[1]) : null;
}

function surveyTypeOf(properties) {
  const value = properties.survey_type;
  if (value === "multispectral" || value === "thermal" || value === "visible") {
    return value;
  }
  return "visible";
}

function kmlElements(root, name) {
  return [...root.getElementsByTagNameNS("*", name)];
}

function kmlText(root, name) {
  const nodes = kmlElements(root, name);
  return nodes.length ? nodes[0].textContent.trim() : "";
}

function kmlPairs(node) {
  const coordinates = kmlElements(node, "coordinates");
  if (!coordinates.length) {
    return [];
  }
  return coordinates[0].textContent.trim().split(/\s+/).map((token) => {
    const [lon, lat] = token.split(",");
    return pairOf([lon, lat]);
  }).filter(Boolean);
}

function downloadText(filename, text, mime) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([text], { type: mime + ";charset=utf-8" }));
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
}

function styleDraw(feature) {
  if (feature.get("kind") === "forbidden") {
    return new ol.style.Style({
      stroke: new ol.style.Stroke({ color: "rgba(176, 24, 24, 0.95)", width: 2 }),
      fill: new ol.style.Fill({ color: forbiddenHatch() }),
      text: new ol.style.Text({
        text: feature.get("name") || "Запрет",
        font: "bold 14px sans-serif",
        textAlign: "center",
        fill: new ol.style.Fill({ color: "#8a1010" }),
        stroke: new ol.style.Stroke({ color: "#fff", width: 4 }),
      }),
    });
  }
  if (feature.get("kind") === "vpp") {
    return new ol.style.Style({
      image: new ol.style.Circle({
        radius: 8,
        fill: new ol.style.Fill({ color: "#1c1c1c" }),
        stroke: new ol.style.Stroke({ color: "#fff", width: 2 }),
      }),
      text: new ol.style.Text({
        text: String(feature.get("vpp")),
        fill: new ol.style.Fill({ color: "#fff" }),
        font: "12px sans-serif",
      }),
    });
  }
  const surveyType = feature.get("surveyType");
  const color = surveyType === "thermal"
    ? "rgba(194, 24, 91, 0.9)"
    : surveyType === "multispectral"
      ? "rgba(46, 155, 87, 0.9)"
      : "rgba(47, 111, 219, 0.9)";
  const fill = surveyType === "thermal"
    ? "rgba(194, 24, 91, 0.2)"
    : surveyType === "multispectral"
      ? "rgba(46, 155, 87, 0.2)"
      : "rgba(47, 111, 219, 0.2)";
  return new ol.style.Style({
    stroke: new ol.style.Stroke({ color: color, width: 2 }),
    fill: new ol.style.Fill({ color: fill }),
    text: new ol.style.Text({
      text: polygonCaption(feature),
      font: "bold 14px sans-serif",
      textAlign: "center",
      fill: new ol.style.Fill({ color: "#1c1c1c" }),
      stroke: new ol.style.Stroke({ color: "#fff", width: 4 }),
    }),
  });
}

function polygonCaption(feature) {
  const pid = String(feature.get("pid") || "");
  const number = pid.startsWith("p") && /^\d+$/.test(pid.slice(1)) ? pid.slice(1) : "";
  const type = TYPE_LABEL[feature.get("surveyType")] || "";
  if (number && type) {
    return "Район " + number + "\n" + type;
  }
  return number ? "Район " + number : type;
}

function styleResult(feature) {
  const color = feature.get("color") || uavColor(feature.get("uav"));
  const kind = feature.get("kind");
  if (kind === "route") {
    return new ol.style.Style({
      stroke: new ol.style.Stroke({ color: color, width: 3, lineDash: [8, 6] }),
    });
  }
  if (kind === "transfer") {
    return new ol.style.Style({
      stroke: new ol.style.Stroke({ color: color, width: 2, lineDash: [1, 6] }),
    });
  }
  return new ol.style.Style({
    stroke: new ol.style.Stroke({
      color: color,
      width: kind === "outline" ? 2 : 4,
      lineDash: kind === "outline" ? [4, 4] : undefined,
    }),
  });
}

const root = document.querySelector('#prototype');
const toast = document.querySelector('#toast');

const state = {
  screen: 'login', resolution: 1, pointsLoaded: false, areaLoaded: false,
  type: 'RGB', fleetOpen: false, fleetMenu: null, excluded: new Set(),
  expandedRoute: null, completion: null,
};

const icon = (name, size = 18) => {
  const paths = {
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    lock: '<rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    layers: '<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5M3 16l9 5 9-5"/>',
    target: '<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2"/><path d="M12 2v3m0 14v3M2 12h3m14 0h3"/>',
    plus: '<path d="M12 5v14M5 12h14"/>', minus: '<path d="M5 12h14"/>',
    spark: '<path d="m12 3 1.6 4.4L18 9l-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6L12 3Z"/><path d="m19 15 .8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8L19 15Z"/>',
    send: '<path d="m3 3 18 9-18 9 3-9-3-9Z"/><path d="M6 12h15"/>',
    chevron: '<path d="m8 10 4 4 4-4"/>',
    download: '<path d="M12 3v12m0 0 4-4m-4 4-4-4"/><path d="M5 19h14"/>',
    flag: '<path d="M5 21V4m0 1h11l-2 3 2 3H5"/>',
    chevronRight: '<path d="m9 18 6-6-6-6"/>',
  };
  return `<svg class="icon" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || ''}</svg>`;
};
const logo = (className = 'logo') => `<img class="${className}" src="/public/assets/strela-logo.png" alt="СТРЕЛА">`;
const notify = message => { toast.textContent = message; toast.classList.add('visible'); clearTimeout(notify.timer); notify.timer = setTimeout(() => toast.classList.remove('visible'), 2200); };

function header(active = 1) {
  const steps = ['Настройка', 'Результаты', 'Полёт'];
  return `<header class="topbar"><div class="top-logo">${logo()}</div><nav class="steps" aria-label="Этапы сценария">
    ${steps.map((label, index) => { const n = index + 1; return `<button class="step ${n === active ? 'active' : ''}" data-screen="${n === 1 ? 'setup' : n === 2 ? 'results' : 'flight'}"><span>${n}</span>${label}</button>${n < 3 ? '<i></i>' : ''}`; }).join('')}
  </nav><div class="profile"><span class="avatar">ИП</span><span><strong>Иван Петров</strong><small>Инженер-оператор</small></span></div></header>`;
}

function loginScreen() {
  return `<main class="login-screen"><div class="login-stack">${logo('login-logo')}<form class="login-card" id="login-form">
    <h1>Вход в систему</h1><p>Планирование беспилотных авиационных работ</p>
    <label>Имя<div class="input-wrap">${icon('user')}<input id="nickname" value="demo" aria-label="Имя"></div></label>
    <label>Пароль<div class="input-wrap">${icon('lock')}<input id="password" type="password" placeholder="Введите пароль" aria-label="Пароль"></div></label>
    <label class="remember"><input type="checkbox">Запомнить меня</label><button class="btn btn-primary btn-wide" type="submit" data-action="login">Войти</button><div class="create-account">Создать аккаунт</div>
  </form><div class="demo-login"><strong>Демонстрационный вход</strong><span>Используйте общий ник и пароль: demo / demo</span></div></div></main>`;
}

function uploadBlock(kind, loaded) {
  const points = kind === 'points';
  return `<section class="control-section"><div class="control-title"><strong>${points ? 'Точки старта и посадки' : 'Область съёмки'}</strong></div>
    <button class="upload-box ${loaded ? 'loaded' : ''}" data-action="upload-${kind}"><span><b>${loaded ? (points ? 'start_points.geojson' : 'survey_area.geojson') : 'Загрузить файл'}</b><small>${loaded ? (points ? '3 точки · 24 КБ' : '1 область · 48 КБ') : (points ? 'GeoJSON, KML или CSV' : 'KML, GeoJSON или SHP')}</small></span>${loaded ? `<em>${icon('check', 14)} Загружено</em>` : ''}</button>
    <button class="file-link" data-action="upload-${kind}">Выбрать файл</button></section>`;
}

function settingsPanel() {
  const ready = state.pointsLoaded && state.areaLoaded;
  return `<aside class="settings-panel"><section class="control-section resolution-section"><div class="control-title"><strong>Разрешение метр/пиксель</strong></div><label class="resolution-input"><input id="resolution" type="number" min="1" max="100" value="${state.resolution}" aria-label="Разрешение, метр на пиксель"></label><div class="chip-row">${[1,3,5].map(n => `<button class="chip ${state.resolution === n ? 'active' : ''}" data-resolution="${n}">${n}</button>`).join('')}</div></section>
    ${uploadBlock('points', state.pointsLoaded)}${uploadBlock('area', state.areaLoaded)}
    <section class="control-section"><div class="control-title"><strong>Тип съёмки</strong></div><div class="type-row">${['RGB','ИК','Геофизическая','LiDAR','Мультиспектр'].map(type => `<button class="type-chip ${state.type === type ? 'active' : ''}" data-type="${type}">${type}</button>`).join('')}</div></section>
    <button class="fleet-launch ${state.fleetOpen ? 'is-open' : ''}" data-action="toggle-fleet"><span><strong>Парк БВС</strong><small>56 аппаратов<br>все участвуют в расчёте</small></span><b>${state.fleetOpen ? 'Скрыть' : 'Показать'}</b><span class="arrow">${icon('chevronRight', 16)}</span></button>
    <button class="btn btn-primary continue" data-action="calculate" ${ready ? '' : 'disabled'}>${ready ? 'Рассчитать' : 'Продолжить'}</button></aside>`;
}

function mapSurface(loaded) {
  return `<div class="map-surface ${loaded ? 'has-data' : ''}">${loaded ? '<img class="map-art" src="/public/assets/setup-loaded.png" alt="Карта с областью съёмки и точками старта">' : ''}
    ${loaded ? '' : `<div class="map-placeholder"><strong>Подготовьте данные для расчёта</strong><span>Загрузите точки старта и область съёмки слева<br>Карта отобразит их после загрузки</span></div>`}</div>`;
}

function demoPanel(results = false) {
  return `<section class="demo-panel"><h3>Демонстрационный режим</h3><div>${results ? '<p>• Маршруты рассчитаны на тестовых данных и показывают, как система распределяет районы съёмки между БВС</p><p>• Раскройте вариант, чтобы посмотреть состав работ</p><p>• Выберите подходящий маршрут или скачайте полётное задание</p>' : '<p>• Заполните характеристики слева, загрузите точки старта и область съёмки</p><p>• Карта работает, но в рамках хакатона данные загружаются из файлов</p><p>• Справа доступен ИИ-помощник — экспериментальная функция для проверки параметров и объяснения результатов</p>'}</div></section>`;
}

function aiPanel() {
  return `<aside class="ai-panel"><h2>${icon('spark')} ИИ-помощник</h2><div class="ai-actions"><button data-message="Загруженные данные прошли проверку.">Проверь загруженные данные</button><button data-message="Для задачи подходят аппараты Геоскан.">Какие БВС подойдут?</button></div><div class="ai-compose"><input id="ai-question" placeholder="Задайте вопрос или опишите задачу"><button data-action="send-ai">${icon('send')}</button></div></aside>`;
}

const droneList = Array.from({length: 56}, (_, i) => ({id:i+1, battery:[46,88,64,60,72,55][i%6]}));
function droneRow(drone) {
  const excluded = state.excluded.has(drone.id);
  return `<article class="drone-row ${excluded ? 'excluded' : ''}"><div class="drone-main"><strong>Геоскан ${201 + (drone.id % 4) * 200}</strong><button class="dots" data-drone-menu="${drone.id}">•••</button></div><div class="drone-foot"><span><i>Мультиспектр</i><i>RGB</i></span><span class="drone-state">${excluded ? '<em>Исключён из списка</em>' : '<b>Готов</b>'}<small>Батарея&nbsp;&nbsp; <strong>${drone.battery}%</strong></small></span></div>${state.fleetMenu === drone.id ? `<button class="drone-popover" data-toggle-drone="${drone.id}">${excluded ? 'Вернуть в список' : 'Убрать из списка'}</button>` : ''}</article>`;
}
function fleetDrawer() {
  return `<aside class="fleet-drawer"><div class="fleet-head"><span><strong>Парк БВС</strong><small>56 аппаратов · все доступны по умолчанию</small></span><button data-action="close-fleet">×</button></div><div class="fleet-scroll">${droneList.map(droneRow).join('')}</div></aside>`;
}

function setupScreen() {
  const loaded = state.pointsLoaded && state.areaLoaded;
  return `<div class="app">${header(1)}<main class="setup-layout">${settingsPanel()}<section class="center-workspace">${mapSurface(loaded)}${demoPanel(false)}${state.fleetOpen ? fleetDrawer() : ''}</section>${aiPanel()}</main></div>`;
}

const routes = [
  {id:1,title:'Вариант 1',badge:'Рекомендованный',badgeClass:'orange',description:'Лучший баланс времени и расхода ресурса.',time:'58 мин',drones:'2 БВС',work:[['Район №1','Мультиспектр · Геоскан 201','22 мин','2 вылета'],['Район №2','Тепловизор · Геоскан 801','24 мин','2 вылета']]},
  {id:2,title:'Вариант 2',badge:'Лучший по времени',badgeClass:'blue',description:'Самый быстрый',time:'44 мин',drones:'3 БВС',work:[['Район №1','RGB · Geoscan Gemini','18 мин','2 вылета'],['Район №2','Тепловизор · Геоскан 801','19 мин','2 вылета']]},
  {id:3,title:'Вариант 3',badge:'Лучший по ресурсу',badgeClass:'green',description:'Минимальный суммарный налёт',time:'1 ч 52 мин',drones:'1 БВС',work:[['Район №1','Мультиспектр · Геоскан 201','48 мин','3 вылета'],['Район №2','Тепловизор · Геоскан 201','51 мин','3 вылета']]},
];
function routeCard(route) {
  const expanded = state.expandedRoute === route.id;
  return `<article class="route-card ${route.id === 1 ? 'recommended' : ''} ${expanded ? 'expanded' : ''}"><div class="route-primary"><div class="route-copy"><div class="route-heading"><strong>${route.title}</strong><span class="route-badge ${route.badgeClass}">${route.badge}</span></div><p>${route.description}</p><div class="metrics"><b>${route.time}</b><b>${route.drones}</b><button data-expand="${route.id}">Подробнее ${icon('chevron',14)}</button></div></div><div class="route-buttons"><button class="download-btn" data-download="${route.id}">${icon('download',15)} Скачать полётное задание</button><button class="select-btn" data-select="${route.id}">Выбрать</button></div></div>${expanded ? `<div class="route-work"><h4>Состав работ</h4>${route.work.map(row => `<div class="work-row"><span><strong>${row[0]}</strong><small>${row[1]}</small></span><span><b>${row[2]}</b><small>время работы</small></span><span><b>${row[3]}</b><small>план</small></span></div>`).join('')}</div>` : ''}</article>`;
}
function completionModal() {
  if (!state.completion) return '';
  const downloading = state.completion === 'download';
  return `<div class="modal-backdrop"><section class="thanks-modal"><div class="thanks-icon">${icon(downloading ? 'download' : 'flag',22)}</div><h2>Спасибо за внимание!</h2><p>${downloading ? 'Полётное задание подготовлено, скачивание уже началось' : 'Полётное задание подготовлено'}</p><div class="demo-summary"><strong>В рамках демонстрации мы:</strong><ul><li>Загрузили точки и область съёмки</li><li>Рассчитали три варианта маршрута</li><li>Распределили районы между БВС</li></ul></div><button class="btn btn-primary btn-wide" data-action="close-completion">Вернуться к вариантам маршрута</button></section></div>`;
}
function resultsScreen() {
  return `<div class="app">${header(2)}<main class="results-page"><div class="results-title"><h1>Варианты маршрута</h1><span>Алгоритм подготовил 3 выполнимых варианта</span></div><div class="results-grid"><section class="results-left">${mapSurface(true)}${demoPanel(true)}</section><aside class="routes-panel">${routes.map(routeCard).join('')}<div class="improve"><span><strong>Как улучшить план</strong><small>Добавьте резервную точку посадки — это повысит надёжность полёта.</small></span><button data-action="back-settings">Изменить параметры</button></div></aside></div></main>${completionModal()}</div>`;
}

function render() { document.documentElement.dataset.screen = state.screen; root.innerHTML = state.screen === 'login' ? loginScreen() : state.screen === 'setup' ? setupScreen() : resultsScreen(); }
function go(screen) { if (screen === 'flight') return notify('Полёт завершает демонстрационный сценарий после выбора маршрута.'); state.screen = screen; state.fleetOpen = false; state.fleetMenu = null; render(); }
function downloadTask(routeId) {
  const route = routes.find(item => item.id === routeId) || routes[0];
  const text = ['Полётное задание — Карьер Северный', `${route.title}: ${route.badge}`, `Разрешение: ${state.resolution} м/пиксель`, ...route.work.map(row => `${row[0]} — ${row[1]}`)].join('\n');
  const url = URL.createObjectURL(new Blob([text], {type:'text/plain;charset=utf-8'})); const link = document.createElement('a'); link.href = url; link.download = 'flight-task.txt'; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 800); state.completion = 'download'; render();
}

root.addEventListener('submit', event => { if (event.target.id === 'login-form') { event.preventDefault(); go('setup'); } });
root.addEventListener('input', event => { if (event.target.id === 'resolution') state.resolution = Number(event.target.value) || 1; });
root.addEventListener('click', event => {
  const button = event.target.closest('button'); if (!button) return;
  if (button.dataset.screen) { if (button.dataset.screen === 'results' && !(state.pointsLoaded && state.areaLoaded)) return notify('Сначала загрузите точки и область съёмки.'); return go(button.dataset.screen); }
  if (button.dataset.resolution) { state.resolution = Number(button.dataset.resolution); return render(); }
  if (button.dataset.type) { state.type = button.dataset.type; return render(); }
  if (button.dataset.message) return notify(button.dataset.message);
  if (button.dataset.droneMenu) { state.fleetMenu = Number(button.dataset.droneMenu); return render(); }
  if (button.dataset.toggleDrone) { const id = Number(button.dataset.toggleDrone); state.excluded.has(id) ? state.excluded.delete(id) : state.excluded.add(id); state.fleetMenu = null; return render(); }
  if (button.dataset.expand) { const id = Number(button.dataset.expand); state.expandedRoute = state.expandedRoute === id ? null : id; return render(); }
  if (button.dataset.download) return downloadTask(Number(button.dataset.download));
  if (button.dataset.select) { state.completion = 'select'; return render(); }
  switch (button.dataset.action) {
    case 'login': go('setup'); break;
    case 'upload-points': state.pointsLoaded = true; render(); notify('Точки старта загружены'); break;
    case 'upload-area': state.areaLoaded = true; render(); notify('Область съёмки загружена'); break;
    case 'toggle-fleet': state.fleetOpen = !state.fleetOpen; state.fleetMenu = null; render(); break;
    case 'close-fleet': state.fleetOpen = false; state.fleetMenu = null; render(); break;
    case 'calculate': if (state.pointsLoaded && state.areaLoaded) go('results'); break;
    case 'back-settings': go('setup'); break;
    case 'close-completion': state.completion = null; render(); break;
    case 'send-ai': notify(root.querySelector('#ai-question')?.value.trim() ? 'ИИ-помощник подготовил ответ' : 'Введите вопрос'); break;
  }
});
render();

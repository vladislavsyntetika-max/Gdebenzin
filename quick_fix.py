import base64
import re

# Простой HTML без Telegram WebApp и с быстрыми тайлами
SIMPLE_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>ГДЕ БЕНЗИН!? — Карта АЗС</title>
<link rel="stylesheet" href="/leaflet.css" />
<script src="/leaflet.js"></script>
<style>
html, body { margin: 0; padding: 0; height: 100%; background: #14171A; }
#map { position: absolute; top: 0; left: 0; right: 0; bottom: 64px; }
#bottom { position: absolute; bottom: 0; left: 0; right: 0; min-height: 64px; background: #1A1D21; border-top: 1px solid #262B31; display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 0 12px; color: #E8E6E1; }
.stat-item { font-size: 15px; font-weight: 700; cursor: pointer; line-height: 1.3; }
.stat-item b { color: #FFB000; font-size: 19px; }
#missing-btn { padding: 9px 12px; border-radius: 10px; background: #1E2227; border: 1px solid #2B3036; color: #E8E6E1; font-size: 12.5px; font-weight: 700; cursor: pointer; }
</style>
</head>
<body>
<div id="map"></div>
<div id="bottom">
<div class="stat-item" onclick="onStatTotalClick()">Всего станций: <b id="stat-total">0</b></div>
<div class="stat-item" id="stat-reported-item" onclick="onStatReportedClick()">С отчётом: <b id="stat-reported">0</b></div>
<button id="missing-btn" onclick="startPinMode()">+ Нет АЗС</button>
</div>
<script>
const map = L.map('map', { zoomControl: false }).setView([59.94, 30.31], 12);

// CartoDB tiles - БЫСТРЫЕ в РФ!
L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
  attribution: '&copy; OpenStreetMap &copy; CARTO',
  subdomains: 'abcd',
  maxZoom: 20
}).addTo(map);

let stationsData = [];

async function loadStations() {
  try {
    const res = await fetch('/api/stations');
    const data = await res.json();
    stationsData = data.stations;
    document.getElementById('stat-total').textContent = stationsData.length;
    renderMarkers();
  } catch (e) {
    console.error('Ошибка:', e);
  }
}

function renderMarkers() {
  map.eachLayer(layer => {
    if (layer instanceof L.Marker) map.removeLayer(layer);
  });
  let reported = 0;
  stationsData.forEach(s => {
    const status = getStatusFor(s.fuels, 'all');
    if (status !== 'unknown') reported++;
    const color = { ok: '#1B8A4A', low: '#C97C00', none: '#C62828', unknown: '#8A8F98' }[status];
    const marker = L.marker([s.lat, s.lng], {
      icon: L.divIcon({
        className: '',
        html: `<div style="width:16px;height:16px;border-radius:50%;background:${color};border:2px solid #14171A;box-shadow:0 0 4px rgba(0,0,0,0.5)"></div>`,
        iconSize: [16, 16],
        iconAnchor: [8, 8],
      })
    }).addTo(map);
    marker.bindPopup(`<b>${s.name}</b><br>${s.addr}`);
  });
  document.getElementById('stat-reported').textContent = reported;
}

function getStatusFor(fuels, fuelKey) {
  if (fuelKey !== 'all') {
    const f = fuels[fuelKey];
    return (f && f.status !== 'unknown' && !f.stale) ? f.status : 'unknown';
  }
  let worst = -1, any = false;
  for (const key in fuels) {
    const f = fuels[key];
    if (f.status !== "unknown" && !f.stale) { any = true; worst = Math.max(worst, {ok:0,low:1,none:2}[f.status]); }
  }
  if (!any) return "unknown";
  return worst === 0 ? "ok" : worst === 1 ? "low" : "none";
}

function onStatTotalClick() {
  document.getElementById('net-select').value = 'all';
  document.getElementById('fuel-select').value = 'all';
  document.getElementById('search-input').value = '';
  renderMarkers();
  const pts = stationsData.map(s => [s.lat, s.lng]);
  if (pts.length) map.fitBounds(pts, { padding: [30, 30] });
}

function onStatReportedClick() {}
function startPinMode() { alert('Режим добавления АЗС'); }

loadStations();
</script>
</body>
</html>"""

# Читаем webserver.py
with open('webserver.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Кодируем в base64
new_b64 = base64.b64encode(SIMPLE_HTML.encode('utf-8')).decode('ascii')

# Заменяем MAP_HTML_B64
content = re.sub(r'MAP_HTML_B64 = "[^"]+"', f'MAP_HTML_B64 = "{new_b64}"', content)

# Сохраняем
with open('webserver.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ ГОТОВО! HTML заменён на простой и быстрый")
print("Теперь выполните:")
print("  git add webserver.py")
print("  git commit -m 'fix: простой HTML без Telegram WebApp'")
print("  git push origin main")
print("\n⚠️ После деплоя откройте карту в режиме ИНКОГНИТО!")
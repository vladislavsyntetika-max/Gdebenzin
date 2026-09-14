import base64
import re
import os

# Ищем webserver.py
for path in ['webserver.py', 'bot/webserver.py', '../webserver.py']:
    if os.path.exists(path):
        WEB_PATH = path
        break
else:
    print("❌ Не нашёл webserver.py")
    exit(1)

print(f" Обрабатываю: {WEB_PATH}")

with open(WEB_PATH, 'r', encoding='utf-8') as f:
    content = f.read()

match = re.search(r'MAP_HTML_B64 = "([^"]+)"', content)
if not match:
    print("❌ MAP_HTML_B64 не найден")
    exit(1)

b64 = match.group(1)
html = base64.b64decode(b64).decode('utf-8')

# 1. Заменяем синхронную загрузку telegram-web-app.js на асинхронную с fallback
html = html.replace(
    '<script src="https://telegram.org/js/telegram-web-app.js"></script>',
    '''<script>
// Загружаем Telegram WebApp асинхронно, чтобы не блокировать страницу
(function() {
  window.Telegram = window.Telegram || {};
  window.Telegram.WebApp = {
    ready: function(){},
    expand: function(){},
    initDataUnsafe: {},
    showAlert: function(msg){ alert(msg); },
    openLink: function(url){ window.open(url, '_blank'); },
    openTelegramLink: function(url){ window.open(url, '_blank'); },
    HapticFeedback: { notificationOccurred: function(){} }
  };
  var script = document.createElement('script');
  script.src = 'https://telegram.org/js/telegram-web-app.js';
  script.async = true;
  script.onload = function() {
    if (window.Telegram && window.Telegram.WebApp) {
      window.Telegram.WebApp.ready();
      window.Telegram.WebApp.expand();
    }
  };
  script.onerror = function() {
    console.warn('Telegram WebApp не загрузился, используем fallback');
  };
  document.head.appendChild(script);
})();
</script>'''
)
print("✅ Заменил загрузку Telegram WebApp на асинхронную")

# 2. Заменяем OpenStreetMap на CartoDB (быстрее в РФ)
html = html.replace(
    "L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(map);",
    """L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; OpenStreetMap &copy; CARTO',
    subdomains: 'abcd',
    maxZoom: 20
}).addTo(map);"""
)
print("✅ Заменил тайлы на CartoDB")

# 3. Добавляем обработку ошибок в loadStations()
old_load = """async function loadStations() {
  const res = await fetch('/api/stations');
  const data = await res.json();
  stationsData = data.stations;
  networksData = data.networks;
  fuelsData = data.fuels;
  statusesData = data.statuses;
  stationFlagsData = data.station_flags;
  document.getElementById('stat-24h').textContent = data.reports_24h;
  renderFilterSelects();
  renderMarkers();
  loadMyStats();
}"""

new_load = """async function loadStations() {
  try {
    console.log('🔄 Загрузка данных станций...');
    const res = await fetch('/api/stations');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    stationsData = data.stations;
    networksData = data.networks;
    fuelsData = data.fuels;
    statusesData = data.statuses;
    stationFlagsData = data.station_flags;
    document.getElementById('stat-24h').textContent = data.reports_24h;
    renderFilterSelects();
    renderMarkers();
    loadMyStats();
    console.log('✅ Карта загружена:', stationsData.length, 'станций');
  } catch (e) {
    console.error(' Ошибка загрузки карты:', e);
    document.getElementById('stat-24h').textContent = 'Ошибка';
    if (tg && tg.showAlert) {
      tg.showAlert('Ошибка загрузки карты: ' + e.message);
    } else {
      alert('Ошибка загрузки карты: ' + e.message);
    }
  }
}"""

if old_load in html:
    html = html.replace(old_load, new_load)
    print("✅ Добавил обработку ошибок в loadStations()")
else:
    print("️ loadStations() не найден в исходном виде")

# Кодируем обратно
new_b64 = base64.b64encode(html.encode('utf-8')).decode('ascii')
content = content.replace(b64, new_b64)

with open(WEB_PATH, 'w', encoding='utf-8') as f:
    f.write(content)

print(f"\n ГОТОВО! Применены все исправления:")
print("  - Асинхронная загрузка Telegram WebApp (не блокирует страницу)")
print("  - CartoDB тайлы вместо OpenStreetMap (быстрее в РФ)")
print("  - Обработка ошибок в loadStations()")
print("\nТеперь выполните:")
print("  git add webserver.py")
print("  git commit -m 'fix: асинхронная загрузка Telegram WebApp и CartoDB тайлы'")
print("  git push origin main")
print("\n⚠️ ВАЖНО: После деплоя откройте карту в режиме Инкогнито или с полной очисткой кэша (Ctrl+F5)!")
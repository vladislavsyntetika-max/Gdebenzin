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

print(f"📄 Обрабатываю: {WEB_PATH}")

with open(WEB_PATH, 'r', encoding='utf-8') as f:
    content = f.read()

# Находим MAP_HTML_B64
match = re.search(r'MAP_HTML_B64 = "([^"]+)"', content)
if not match:
    print("❌ MAP_HTML_B64 не найден")
    exit(1)

b64 = match.group(1)
html = base64.b64decode(b64).decode('utf-8')

# 1. Заменяем OpenStreetMap на CartoDB (стабильнее в РФ)
old_tile = "L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(map);"

new_tile = """// CartoDB tiles - стабильнее в РФ
L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 20,
    crossOrigin: true
}).addTo(map);

// Обработка ошибок загрузки тайлов
map.on('tileerror', function() {
    console.warn('Ошибка загрузки тайла, пробуем другой поддомен...');
});"""

if old_tile in html:
    html = html.replace(old_tile, new_tile)
    print("✅ Заменил тайлы на CartoDB")
else:
    print("⚠️ Не нашёл строку с тайлами")

# 2. Добавляем обработку ошибок инициализации карты
if "map.on('tileerror'" not in html:
    error_handler = """
// Глобальная обработка ошибок
window.addEventListener('error', function(e) {
    console.error('Global error:', e.error);
});

window.addEventListener('unhandledrejection', function(e) {
    console.error('Unhandled promise rejection:', e.reason);
});"""
    html = html.replace('</script>', error_handler + '</script>')
    print("✅ Добавил обработку ошибок")

# 3. Упрощаем инициализацию карты - убираем сложные анимации
old_map_init = "L.map('map', { zoomControl: false, attributionControl: false }).setView([59.94, 30.31], BASE_ZOOM);"
new_map_init = "L.map('map', { zoomControl: false, attributionControl: false, fadeAnimation: false, markerZoomAnimation: false }).setView([59.94, 30.31], BASE_ZOOM);"

if old_map_init in html:
    html = html.replace(old_map_init, new_map_init)
    print("✅ Упростил инициализацию карты")

# 4. Добавляем проверку загрузки данных
if "loadStations()" in html and "console.log('✅ Карта загружена'" not in html:
    old_load = """async function loadStations() {
  const res = await fetch('/api/stations');
  const data = await res.json();"""
  
    new_load = """async function loadStations() {
  try {
    console.log('🔄 Загрузка данных станций...');
    const res = await fetch('/api/stations');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    console.log('✅ Данные загружены:', data.stations.length, 'станций');"""
    
    html = html.replace(old_load, new_load)
    print("✅ Добавил логирование загрузки")

# Кодируем обратно
new_b64 = base64.b64encode(html.encode('utf-8')).decode('ascii')
content = content.replace(b64, new_b64)

with open(WEB_PATH, 'w', encoding='utf-8') as f:
    f.write(content)

print("\n🎉 ГОТОВО! Применены все исправления:")
print("  - CartoDB вместо OpenStreetMap")
print("  - Обработка ошибок тайлов")
print("  - Упрощённая инициализация")
print("  - Логирование в консоль")
print("\nТеперь выполните:")
print("  git add webserver.py")
print("  git commit -m 'fix: CartoDB тайлы и обработка ошибок карты'")
print("  git push origin main")
print("\nПосле деплоя:")
print("  1. Откройте https://azs-spb-bot-syntetika.amvera.io/map")
print("  2. Нажмите F12 → Console")
print("  3. Посмотрите, есть ли ошибки")
print("  4. Если карта не грузится — пришлите скриншот консоли")
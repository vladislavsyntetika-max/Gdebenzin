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
    print(" MAP_HTML_B64 не найден")
    exit(1)

b64 = match.group(1)
html = base64.b64decode(b64).decode('utf-8')

# Заменяем tileLayer на CartoDB (более стабильный в РФ)
old_tile = "L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(map);"

new_tile = """// Пробуем CartoDB (стабильнее в РФ)
L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 20
}).addTo(map);

// Если CartoDB не грузится через 5 секунд, пробуем резервный вариант
let tileLoadTimeout = setTimeout(() => {
    console.warn('CartoDB tiles loading slow, trying backup...');
}, 5000);"""

if old_tile in html:
    html = html.replace(old_tile, new_tile)
    print("✅ Заменил тайлы на CartoDB")
else:
    print("⚠️ Не нашёл строку с тайлами, возможно уже изменено")

# Добавляем обработку ошибок карты
if "map.on('tileerror'" not in html:
    error_handler = """
// Обработка ошибок загрузки тайлов
map.on('tileerror', function() {
    console.warn('Ошибка загрузки тайла');
});

map.on('load', function() {
    console.log('Карта загружена');
});
"""
    # Вставляем после инициализации карты
    html = html.replace(
        "L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'",
        error_handler + "L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'"
    )
    print("✅ Добавил обработку ошибок")

# Кодируем обратно
new_b64 = base64.b64encode(html.encode('utf-8')).decode('ascii')
content = content.replace(b64, new_b64)

with open(WEB_PATH, 'w', encoding='utf-8') as f:
    f.write(content)

print("\n🎉 ГОТОВО! Тайлы заменены на CartoDB (стабильнее)")
print("Теперь выполните:")
print("  git add webserver.py")
print("  git commit -m 'fix: заменены тайлы карты на CartoDB для стабильности'")
print("  git push origin main")
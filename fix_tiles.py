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

match = re.search(r'MAP_HTML_B64 = "([^"]+)"', content)
if not match:
    print("❌ MAP_HTML_B64 не найден")
    exit(1)

b64 = match.group(1)
html = base64.b64decode(b64).decode('utf-8')

# Заменяем CartoDB на OpenStreetMap (несколько поддоменов для скорости)
old_carto = """L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; OpenStreetMap &copy; CARTO',
    subdomains: 'abcd',
    maxZoom: 20
}).addTo(map);"""

new_osm = """L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    subdomains: 'abc',
    maxZoom: 19
}).addTo(map);"""

if old_carto in html:
    html = html.replace(old_carto, new_osm)
    print("✅ Заменил CartoDB на OpenStreetMap")
else:
    # Если не нашли точное совпадение, ищем любой CartoDB
    if 'cartocdn.com' in html:
        html = re.sub(
            r"L\.tileLayer\('https://\{s\}\.basemaps\.cartocdn\.com/[^']+',\s*\{[^}]+\}\)\.addTo\(map\);",
            new_osm,
            html,
            flags=re.DOTALL
        )
        print("✅ Заменил CartoDB на OpenStreetMap (regex)")
    else:
        print("⚠️ CartoDB не найден, возможно уже заменён")

# Кодируем обратно
new_b64 = base64.b64encode(html.encode('utf-8')).decode('ascii')
content = content.replace(b64, new_b64)

with open(WEB_PATH, 'w', encoding='utf-8') as f:
    f.write(content)

print("\n ГОТОВО! Тайлы заменены на OpenStreetMap")
print("Теперь выполните:")
print("  git add webserver.py")
print("  git commit -m 'fix: заменены тайлы CartoDB на OpenStreetMap (требует API ключ)'")
print("  git push origin main")
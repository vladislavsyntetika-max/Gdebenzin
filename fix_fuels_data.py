import base64
import re

with open('webserver.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Находим MAP_HTML_B64
match = re.search(r'MAP_HTML_B64 = "([^"]+)"', content)
if not match:
    print("❌ MAP_HTML_B64 не найден")
    exit(1)

b64 = match.group(1)
html = base64.b64decode(b64).decode('utf-8')

# Добавляем объявление переменных в начало <script>
old_script_start = "<script>"
new_script_start = """<script>
// Глобальные переменные
let stationsData = [];
let networksData = {};
let fuelsData = [];
let statusesData = [];
let stationFlagsData = [];
let markers = {};
let activeNet = "all";
let activeFuel = "all";
let activeSearch = "";
let favOnly = false;
let reportedOnly = false;
let proximityStationId = null;
let proximityReported = new Set();
let proximityTimer = null;
let watchId = null;
let userMarker = null;
let userAccCircle = null;
let firstFix = true;
let followMode = true;
let nearStationId = null;
let lastHeading = 0;
let pinMode = false;
let dropPinMarker = null;
let deferredInstallPrompt = null;"""

if old_script_start in html:
    html = html.replace(old_script_start, new_script_start, 1)
    print("✅ Добавлены глобальные переменные")
else:
    print(" Не найдено место для вставки")
    exit(1)

# Кодируем обратно
new_b64 = base64.b64encode(html.encode('utf-8')).decode('ascii')
content = content.replace(b64, new_b64)

with open('webserver.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ ГОТОВО!")
print("\nТеперь выполните:")
print("  git add webserver.py fix_fuels_data.py")
print("  git commit -m 'fix: добавлены глобальные переменные для карты'")
print("  git push origin main")
print("\n⚠️ После деплоя откройте карту в РЕЖИМЕ ИНКОГНИТО (Ctrl+Shift+N)!")
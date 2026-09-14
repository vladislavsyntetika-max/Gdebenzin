import base64
import re

with open('webserver.py', 'r', encoding='utf-8') as f:
    content = f.read()

match = re.search(r'MAP_HTML_B64 = "([^"]+)"', content)
b64 = match.group(1)
html = base64.b64decode(b64).decode('utf-8')

# Удаляем ДУБЛИРУЮЩИЕСЯ объявления переменных которые я добавил
old_block = """<script>
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

new_block = """<script>"""

if old_block in html:
    html = html.replace(old_block, new_block)
    print("✅ Убрал дублирующие объявления переменных")
else:
    # Пробуем найти просто объявления let
    html = re.sub(r'let stationsData = \[\];\s*', '', html)
    html = re.sub(r'let networksData = \{\};\s*', '', html)
    html = re.sub(r'let fuelsData = \[\];\s*', '', html)
    html = re.sub(r'let statusesData = \[\];\s*', '', html)
    html = re.sub(r'let stationFlagsData = \[\];\s*', '', html)
    print("✅ Убрал дублирующие объявления через regex")

new_b64 = base64.b64encode(html.encode('utf-8')).decode('ascii')
content = content.replace(b64, new_b64)

with open('webserver.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ ГОТОВО! Убрал дубликаты")
print("git add webserver.py && git commit -m 'fix: removed duplicate variable declarations' && git push origin main")
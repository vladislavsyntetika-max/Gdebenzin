#!/usr/bin/env python3
"""
Автоматически исправляет карту для быстрой загрузки:
1. Заменяет внешний telegram-web-app.js на локальную версию
2. Отключает Service Worker (убирает кэш-проблемы)
3. Ускоряет первую загрузку
"""
import base64
import re
import os
import sys

# Ищем webserver.py
for path in ['webserver.py', 'bot/webserver.py', '../webserver.py']:
    if os.path.exists(path):
        WEB_PATH = path
        break
else:
    print("❌ Не нашёл webserver.py. Запустите скрипт в папке с проектом.")
    sys.exit(1)

print(f" Обрабатываю: {WEB_PATH}")

with open(WEB_PATH, 'r', encoding='utf-8') as f:
    content = f.read()

# Находим MAP_HTML_B64
match = re.search(r'MAP_HTML_B64 = "([^"]+)"', content)
if not match:
    print("❌ MAP_HTML_B64 не найден")
    sys.exit(1)

b64 = match.group(1)
html = base64.b64decode(b64).decode('utf-8')

# 1. Заменяем внешний скрипт Telegram на локальный
html = html.replace(
    '<script src="https://telegram.org/js/telegram-web-app.js"></script>',
    '''<script>
// Локальная версия Telegram WebApp API
window.Telegram = window.Telegram || {};
window.Telegram.WebApp = {
  ready: function() {},
  expand: function() {},
  close: function() {},
  initDataUnsafe: {},
  showAlert: function(msg) { alert(msg); },
  showConfirm: function(msg, callback) { callback(confirm(msg)); },
  openLink: function(url) { window.open(url, '_blank'); },
  openTelegramLink: function(url) { window.open(url, '_blank'); },
  HapticFeedback: { notificationOccurred: function() {} }
};
</script>'''
)
print("✅ Заменил внешний Telegram WebApp на локальный")

# 2. Отключаем Service Worker (убираем регистрацию)
html = re.sub(
    r"if \('serviceWorker' in navigator\) \{[\s\S]*?navigator\.serviceWorker\.register\('/sw\.js'\)[\s\S]*?\}",
    "// Service Worker отключён для ускорения загрузки",
    html
)
print("✅ Отключил Service Worker")

# 3. Убираем или упрощаем SW_JS в самом webserver.py
content = re.sub(
    r'SW_JS = """[\s\S]*?"""',
    '''SW_JS = """
// Service Worker отключён для стабильности
self.addEventListener('install', (e) => { self.skipWaiting(); });
self.addEventListener('activate', (e) => { self.clients.claim(); });
self.addEventListener('fetch', (e) => {
  // Просто пропускаем все запросы без кэша
  return;
});
"""''',
    content
)
print("✅ Упростил SW_JS в коде")

# Кодируем обратно
new_b64 = base64.b64encode(html.encode('utf-8')).decode('ascii')
content = content.replace(b64, new_b64)

with open(WEB_PATH, 'w', encoding='utf-8') as f:
    f.write(content)

print("\n🎉 ГОТОВО! Карта должна загружаться быстрее.")
print("\nТеперь выполните:")
print("  git add webserver.py")
print("  git commit -m 'fix: ускорена загрузка карты (локальный WebApp, отключён SW)'")
print("  git push origin main")
print("\nПосле деплоя:")
print("  1. Подождите 2-3 минуты")
print("  2. Полностью закройте Telegram на телефоне")
print("  3. Откройте бота снова и нажмите '🗺 Открыть карту'")
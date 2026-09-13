import base64
import re
import os

# Ищем webserver.py
for path in ['webserver.py', 'bot/webserver.py', '../webserver.py']:
    if os.path.exists(path):
        WEB_PATH = path
        break
else:
    print("❌ Не нашёл webserver.py. Запустите скрипт в папке с проектом.")
    exit(1)

print(f"📄 Обрабатываю: {WEB_PATH}")

with open(WEB_PATH, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Исправляем SW_JS (Service Worker) на абсолютно безопасную версию
safe_sw = '''SW_JS = """
const CACHE_NAME = 'azs-spb-v2';
self.addEventListener('install', (e) => { self.skipWaiting(); });
self.addEventListener('activate', (e) => { self.clients.claim(); });
self.addEventListener('fetch', (e) => {
  // API запросы всегда идут в сеть, без кэша
  if (e.request.url.includes('/api/')) return;
  
  e.respondWith(
    caches.match(e.request).then((cached) => {
      return fetch(e.request).then((res) => {
        if (res && res.status === 200) {
          const responseToCache = res.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(e.request, responseToCache);
          });
        }
        return res;
      }).catch(() => {
        // Если сеть недоступна, возвращаем кэш. Если кэша нет, возвращаем безопасный ответ, а НЕ undefined!
        return cached || new Response('Offline', { status: 503, statusText: 'Service Unavailable', headers: { 'Content-Type': 'text/plain' } });
      });
    })
  );
});
"""'''

# Находим и заменяем SW_JS = """..."""
content = re.sub(r'SW_JS = """.*?"""', safe_sw, content, flags=re.DOTALL)
print("✅ Service Worker исправлен (версия кэша v2, защита от сбоев сети)")

# 2. Исправляем кнопку "Установить" в HTML
match = re.search(r'MAP_HTML_B64 = "([^"]+)"', content)
if match:
    b64 = match.group(1)
    try:
        html = base64.b64decode(b64).decode('utf-8')
        
        # Добавляем onclick к кнопке
        html = html.replace(
            '<button id="install-banner-btn">Установить</button>',
            '<button id="install-banner-btn" onclick="doInstallPrompt()">Установить</button>'
        )
        
        # Добавляем функцию doInstallPrompt перед закрывающим </script>
        install_fn = """
function doInstallPrompt() {
  if (window.deferredInstallPrompt) {
    window.deferredInstallPrompt.prompt();
    window.deferredInstallPrompt.userChoice.then(function(choice) {
      if (choice.outcome === 'accepted') {
        document.getElementById('install-banner').style.display = 'none';
      }
      window.deferredInstallPrompt = null;
    });
    return;
  }
  var msg = 'Чтобы добавить ярлык:\\n\\n' +
    '• На Android: нажмите ⋮ (три точки) → "Добавить на главный экран"\\n' +
    '• На iPhone: нажмите кнопку "Поделиться" (⬆) → "На экран Домой"\\n\\n' +
    'В Telegram это делается через меню браузера, а не через кнопку.';
  
  if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.showAlert) {
    window.Telegram.WebApp.showAlert(msg);
  } else {
    alert(msg);
  }
}
"""
        if 'function doInstallPrompt()' not in html:
            html = html.replace('</script>', install_fn + '</script>')
            print("✅ Функция doInstallPrompt добавлена в HTML")
        else:
            print("⚠️ Функция doInstallPrompt уже существует")
            
        # Кодируем обратно
        new_b64 = base64.b64encode(html.encode('utf-8')).decode('ascii')
        content = content.replace(b64, new_b64)
    except Exception as e:
        print(f"❌ Ошибка декодирования HTML: {e}")
        exit(1)
else:
    print("❌ MAP_HTML_B64 не найден")
    exit(1)

with open(WEB_PATH, 'w', encoding='utf-8') as f:
    f.write(content)

print("\n🎉 ГОТОВО! Все критические исправления применены.")
print("Теперь выполните:")
print("  git add webserver.py")
print("  git commit -m 'fix: исправлен Service Worker (ошибка clone) и кнопка установки'")
print("  git push origin main")
print("\n⚠️ ВАЖНО: После деплоя обязательно откройте карту в режиме Инкогнито или с полной очисткой кэша (Ctrl+F5), чтобы браузер удалил сломанный Service Worker v1!")
import base64
import re
import os

# Находим webserver.py
path = 'webserver.py'
if not os.path.exists(path):
    path = 'bot/webserver.py'

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Находим MAP_HTML_B64
match = re.search(r'MAP_HTML_B64 = "([^"]+)"', content)
if not match:
    print("❌ MAP_HTML_B64 не найден")
    exit(1)

b64 = match.group(1)
html = base64.b64decode(b64).decode('utf-8')

# Заменяем сложную функцию initInstallUI на простую
old_func_pattern = r'function initInstallUI\(\) \{[\s\S]*?\n\}\ninitInstallUI\(\);'

new_func = '''function initInstallUI() {
  // Если уже установлено как приложение — баннер не нужен
  if (window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true) {
    document.getElementById('install-banner').style.display = 'none';
    return;
  }
  // Всегда показываем баннер с кнопкой
  showInstallBanner(' Добавьте ярлык на главный экран', function() {
    openInstallModal();
  });
}
initInstallUI();'''

html = re.sub(old_func_pattern, new_func, html)

# Кодируем обратно
new_b64 = base64.b64encode(html.encode('utf-8')).decode('ascii')
content = content.replace(b64, new_b64)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Кнопка 'Установить' теперь всегда показывает инструкцию")
print("Теперь выполните:")
print("  git add webserver.py")
print("  git commit -m 'fix: кнопка Установить показывает инструкцию'")
print("  git push origin main")

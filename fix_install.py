#!/usr/bin/env python3
"""Чинит кнопку "Установить" в карте. Запускать один раз."""
import base64, re, os

path = os.path.join(os.path.dirname(__file__), 'webserver.py')
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

m = re.search(r'MAP_HTML_B64 = "([^"]+)"', content)
if not m:
    print("❌ MAP_HTML_B64 не найден"); exit(1)

html = base64.b64decode(m.group(1)).decode('utf-8')

# 1) Добавляем onclick на кнопку
html = html.replace(
    '<button id="install-banner-btn">Установить</button>',
    '<button id="install-banner-btn" onclick="doInstallPrompt()">Установить</button>'
)

# 2) Вставляем функцию doInstallPrompt ПЕРЕД закрывающим </script>
install_fn = """
function doInstallPrompt() {
    if (window.deferredInstallPrompt) {
        window.deferredInstallPrompt.prompt();
        window.deferredInstallPrompt.userChoice.then(function(c) {
            if (c.outcome === 'accepted') {
                document.getElementById('install-banner').style.display = 'none';
            }
            window.deferredInstallPrompt = null;
        });
    } else {
        var msg = 'Чтобы добавить ярлык:\\n\\n' +
            '• Android (Chrome): меню браузера (⋮) → "Добавить на главный экран"\\n' +
            '• iPhone (Safari): кнопка "Поделиться" (⬆) → "На экран Домой"\\n\\n' +
            'В Telegram это делается через меню браузера, а не через кнопку.';
        if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.showAlert) {
            window.Telegram.WebApp.showAlert(msg);
        } else {
            alert(msg);
        }
    }
}
"""
html = html.replace('</script>', install_fn + '</script>')

new_b64 = base64.b64encode(html.encode('utf-8')).decode('ascii')
content = content.replace(m.group(1), new_b64)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Кнопка 'Установить' починена. Коммить и пуш.")
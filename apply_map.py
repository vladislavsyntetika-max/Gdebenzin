"""
apply_map.py — подставляет свежий webapp/map.html в MAP_HTML_B64 внутри webserver.py.

Запускать из корня проекта:
    python3 apply_map.py

Скрипт читает webapp/map.html, кодирует его в base64 и заменяет
содержимое переменной MAP_HTML_B64 = "..." в webserver.py.
Оригинальный webserver.py перед изменением сохраняется как webserver.py.bak.
"""

import base64
import re
import shutil
import sys
from pathlib import Path

HTML_PATH = Path("webapp/map.html")
SERVER_PATH = Path("webserver.py")
BACKUP_PATH = Path("webserver.py.bak")


def main() -> int:
    if not HTML_PATH.exists():
        print(f"ОШИБКА: не найден {HTML_PATH}. Создайте webapp/map.html.")
        return 1
    if not SERVER_PATH.exists():
        print(f"ОШИБКА: не найден {SERVER_PATH}.")
        return 1

    html = HTML_PATH.read_text(encoding="utf-8")
    if "<!DOCTYPE html" not in html and "<html" not in html.lower():
        print(f"ПРЕДУПРЕЖДЕНИЕ: файл {HTML_PATH} не похож на HTML. Прерываю.")
        return 1

    new_b64 = base64.b64encode(html.encode("utf-8")).decode("ascii")
    text = SERVER_PATH.read_text(encoding="utf-8")

    pattern = re.compile(r'MAP_HTML_B64\s*=\s*"[^"]*"')
    match = pattern.search(text)
    if not match:
        print("ОШИБКА: в webserver.py не найдена строка вида: MAP_HTML_B64 = \"...\"")
        return 1

    shutil.copy2(SERVER_PATH, BACKUP_PATH)
    print(f"Бэкап сохранён: {BACKUP_PATH}")

    new_text = text[:match.start()] + 'MAP_HTML_B64 = "' + new_b64 + '"' + text[match.end():]
    SERVER_PATH.write_text(new_text, encoding="utf-8")

    print(f"OK. Размер HTML: {len(html)} байт. Base64: {len(new_b64)} байт.")
    print("Готово. Можно коммитить и деплоить:")
    print("  git add webserver.py webapp/map.html apply_map.py")
    print('  git commit -m "fix(map): новый HTML карты вместо сломанного Qwen"')
    print("  git push origin main")
    return 0


if __name__ == "__main__":
    sys.exit(main())
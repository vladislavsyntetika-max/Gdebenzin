"""
weekly_report.py — генератор постов для канала на основе живой базы бота.

Запускается вручную на сервере (там, где реально лежит db.sqlite3 — см. README,
переменная DB_PATH), а не локально — иначе секции будут пустыми/неактуальными.

Использование:
    python3 weekly_report.py            # печатает посты в консоль — скопировать вручную в канал
    python3 weekly_report.py --send      # публикует все посты прямо в канал
                                          # (нужны те же BOT_TOKEN и CHANNEL_ID, что у самого бота)

Печатает несколько постов, разделённых линией "==========" — каждый можно
опубликовать в Telegram отдельным сообщением (или все сразу через --send).
"""

import asyncio
import sys
import time
from collections import Counter

# Переиспользуем всю работу с БД и форматирование прямо из bot.py, чтобы скрипт
# никогда не расходился со схемой таблиц и с тем, как считаются баллы/звания.
import bot as core

WEEK_SECONDS = 7 * 86400


def week_bounds():
    now = int(time.time())
    return now - WEEK_SECONDS, now


def post_weekly_stats() -> str:
    week_ago, _now = week_bounds()
    conn = core.db()
    total_reports = conn.execute(
        "SELECT COUNT(*) FROM feed WHERE ts > ?", (week_ago,)
    ).fetchone()[0]
    active_stations = conn.execute(
        "SELECT COUNT(DISTINCT station_id) FROM feed WHERE ts > ?", (week_ago,)
    ).fetchone()[0]
    active_users = conn.execute(
        "SELECT COUNT(DISTINCT user_id) FROM feed WHERE ts > ? AND user_id != 0", (week_ago,)
    ).fetchone()[0]
    scouting_reports = conn.execute(
        "SELECT COUNT(*) FROM points_log WHERE reason='scout_bonus' AND ts > ?", (week_ago,)
    ).fetchone()[0]
    top_station_row = conn.execute(
        "SELECT station_id, COUNT(*) c FROM feed WHERE ts > ? GROUP BY station_id ORDER BY c DESC LIMIT 1",
        (week_ago,),
    ).fetchone()
    conn.close()

    lines = ["📊 <b>Неделя в цифрах</b>", ""]
    lines.append(f"Отчётов от водителей: <b>{total_reports}</b>")
    lines.append(f"Станций, по которым отчитывались: <b>{active_stations}</b> из {len(core.STATIONS)}")
    lines.append(f"Активных участников: <b>{active_users}</b>")
    if scouting_reports:
        lines.append(f"Из них «разведка» (первыми отметили станцию после долгого затишья): <b>{scouting_reports}</b> 🔭")
    if top_station_row:
        station_id, c = top_station_row
        s = core.STATION_BY_ID.get(station_id)
        if s:
            lines.append(f"Самая обсуждаемая станция недели: {s[1]}, {s[3]} — {c} отметок")
    lines.append("")
    lines.append("Присоединяйтесь: @naidibenzin_bot")
    return "\n".join(lines)


def post_weekly_leaderboard() -> str:
    rows = core.get_weekly_leaderboard(10)
    if not rows:
        return "🏆 <b>Топ недели</b>\n\nНа этой неделе ещё не было отчётов — рано постить."
    return core.format_leaderboard_text(rows, title="🏆 <b>Топ разведчиков недели</b>")


def post_scouts_shoutout():
    """Именные благодарности тем, кто сделал 'разведку' — первым отчитался по станции
    без свежих данных 8+ часов (раздел 10 стратегии)."""
    week_ago, _now = week_bounds()
    conn = core.db()
    rows = conn.execute(
        """
        SELECT user_id, COUNT(*) c
        FROM points_log
        WHERE reason='scout_bonus' AND ts > ?
        GROUP BY user_id
        ORDER BY c DESC
        LIMIT 5
        """,
        (week_ago,),
    ).fetchall()
    if not rows:
        conn.close()
        return None  # нечего постить на этой неделе — пропускаем рубрику

    names = []
    for user_id, c in rows:
        row = conn.execute("SELECT username FROM user_points WHERE user_id=?", (user_id,)).fetchone()
        username = row[0] if row else None
        label = core.format_display(username, user_id)
        names.append(f"{label} ({c})" if c > 1 else label)
    conn.close()

    lines = ["🔭 <b>Разведчики недели</b>", ""]
    lines.append("Первыми отметили станции, по которым давно не было данных: " + ", ".join(names))
    return "\n".join(lines)


def post_thank_helpers():
    """Раздел 10 стратегии: именной шаутаут тем, кто помог поправить карту.
    Приблизительно берём заявки, СОЗДАННЫЕ на этой неделе и уже отмеченные
    исправленными на момент запуска скрипта (в issue_reports нет отдельной
    метки времени исправления — это единственное ограничение точности)."""
    week_ago, _now = week_bounds()
    conn = core.db()
    rows = conn.execute(
        "SELECT user_id, username FROM issue_reports WHERE status='fixed' AND ts > ?",
        (week_ago,),
    ).fetchall()
    conn.close()
    if not rows:
        return None  # нечего постить на этой неделе — пропускаем рубрику

    names = []
    seen = set()
    for user_id, username in rows:
        if user_id in seen:
            continue
        seen.add(user_id)
        names.append(core.format_display(username, user_id))

    lines = ["🙌 <b>Спасибо, кто помог поправить карту на этой неделе</b>", ""]
    lines.append(", ".join(names))
    lines.append("")
    lines.append("Заметили неточность — жмите «⚠️ Неточность» на карточке станции, разберёмся быстро.")
    return "\n".join(lines)


def build_posts() -> list:
    posts = [
        post_weekly_stats(),
        post_weekly_leaderboard(),
        post_scouts_shoutout(),
        post_thank_helpers(),
    ]
    return [p for p in posts if p]  # пропускаем рубрики, для которых нечего сказать


async def send_posts(posts):
    if not core.BOT_TOKEN:
        print("BOT_TOKEN не задан — отправка невозможна. Проверьте переменные окружения.", file=sys.stderr)
        return
    if not core.CHANNEL_ID:
        print("CHANNEL_ID не задан — отправка невозможна. Проверьте переменные окружения.", file=sys.stderr)
        return

    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties

    bot = Bot(token=core.BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    try:
        for post in posts:
            await bot.send_message(core.CHANNEL_ID, post)
            await asyncio.sleep(1)  # не спамить Telegram API подряд
    finally:
        await bot.session.close()


def main():
    posts = build_posts()
    if not posts:
        print("За неделю нет данных — постить пока нечего.")
        return

    if "--send" in sys.argv:
        asyncio.run(send_posts(posts))
        print(f"Готово: {len(posts)} постов отправлены в канал.")
        return

    print(f"Сгенерировано постов: {len(posts)}\n")
    for post in posts:
        print(post)
        print("\n" + "=" * 40 + "\n")
    print("Это предпросмотр (текст не отправлен). Для публикации: python3 weekly_report.py --send")


if __name__ == "__main__":
    main()


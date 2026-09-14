"""
Веб-сервер для карты «ГДЕ БЕНЗИН!?».
Работает в том же процессе, что и бот (см. bot.py -> main()).
Статика (HTML, JS, CSS) отдаётся из папки webapp/.
"""

import html
import json
import time
from aiohttp import web
import bot as core


async def handle_map(request):
    return web.FileResponse("webapp/map.html")


async def handle_leaflet_js(request):
    return web.FileResponse("webapp/leaflet.js")


async def handle_leaflet_css(request):
    return web.FileResponse("webapp/leaflet.css")


async def handle_manifest(request):
    # Минимальный PWA-манифест. Если нужен — можно потом вынести в файл.
    manifest = {
        "name": "ГДЕ БЕНЗИН!? — топливо в реале",
        "short_name": "Где бензин",
        "start_url": "/map",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#14171A",
        "theme_color": "#14171A",
    }
    return web.json_response(manifest, content_type="application/manifest+json")


async def handle_sw(request):
    # Service worker можно пока отключить (возвращаем минимальный, чтобы PWA не падал).
    sw = "self.addEventListener('install', e => self.skipWaiting());"
    return web.Response(text=sw, content_type="application/javascript")


async def handle_rules(request):
    rules = """<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Правила — ГДЕ БЕНЗИН!?</title>
<style>body{background:#14171A;color:#E8E6E1;font-family:-apple-system,sans-serif;
padding:20px;line-height:1.6;max-width:640px;margin:0 auto}
h1{font-size:20px}h2{font-size:16px;color:#FFB000;margin-top:24px}</style>
</head><body>
<h1>Правила и конфиденциальность</h1>
<p>Это открытый некоммерческий проект, не связанный с сетями АЗС официально.</p>
<h2>Что мы храним</h2>
<p>Ваш ID, отметки о топливе и сообщения о неточностях с их временем. Точные координаты
сохраняются только если вы сами сообщаете об отсутствующей станции.</p>
<h2>Кому передаются данные</h2>
<p>Никому.</p>
<h2>Ответственность</h2>
<p>Данные вносят сами водители, точность не гарантируется.</p>
</body></html>"""
    return web.Response(text=rules, content_type="text/html")


async def handle_stations(request):
    conn = core.db()
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
        day_ago = int(time.time()) - 86400
        reports_by_station = {}
        for station_id, fuel, status, ts in conn.execute(
            "SELECT station_id, fuel, status, ts FROM reports WHERE ts > ?", (day_ago,)
        ):
            reports_by_station.setdefault(station_id, {})[fuel] = (status, ts)

        recent_by_key = {}
        recent_rows = conn.execute("""
            SELECT station_id, fuel, status FROM (
                SELECT station_id, fuel, status,
                ROW_NUMBER() OVER (PARTITION BY station_id, fuel ORDER BY ts DESC) AS rn
                FROM feed WHERE ts > ?
            ) WHERE rn <= 5
        """, (day_ago,))
        for station_id, fuel, status in recent_rows:
            recent_by_key.setdefault((station_id, fuel), []).append(status)

        reports_24h = conn.execute(
            "SELECT COUNT(*) FROM feed WHERE ts > ?", (day_ago,)
        ).fetchone()[0]
    finally:
        conn.close()

    def confidence_for(station_id, fuel, current_status):
        recent = recent_by_key.get((station_id, fuel))
        if not recent:
            return None
        matches = sum(1 for s in recent if s == current_status)
        return round(matches / len(recent) * 100)

    result = []
    for sid, name, net, addr, lat, lng in core.STATIONS:
        rep = reports_by_station.get(sid, {})
        fuels = {}
        for key, label in core.FUELS:
            if key in rep:
                status, ts = rep[key]
                fuels[key] = {
                    "status": status, "label": label,
                    "ago": core.time_ago(ts),
                    "stale": core.is_stale(ts),
                    "confidence": confidence_for(sid, key, status),
                }
            else:
                fuels[key] = {"status": "unknown", "label": label,
                              "ago": None, "stale": False, "confidence": None}
        flags = {}
        for key, label in core.STATION_FLAGS:
            if key in rep:
                status, ts = rep[key]
                flags[key] = {"on": status == "on" and not core.is_stale(ts),
                              "label": label, "ago": core.time_ago(ts)}
            else:
                flags[key] = {"on": False, "label": label, "ago": None}
        result.append({"id": sid, "name": name, "net": net, "addr": addr,
                       "lat": lat, "lng": lng, "fuels": fuels, "flags": flags})

    return web.json_response({
        "stations": result,
        "networks": core.NETWORKS,
        "fuels": core.FUELS,
        "statuses": core.STATUSES,
        "station_flags": core.STATION_FLAGS,
        "reports_24h": reports_24h,
    })


async def handle_user_stats(request):
    try:
        user_id = int(request.query.get("user_id", "0"))
    except ValueError:
        user_id = 0
    stats = core.get_user_stats(user_id)
    stats["fixed_issues"] = core.user_fixed_issues_count(user_id)
    profile = core.get_points_profile(user_id)
    stats["points"] = profile["total_points"]
    stats["rank"] = profile["rank"]
    stats["streak_days"] = profile["streak_days"]
    return web.json_response(stats)


async def handle_report(request):
    try:
        data = await request.json()
        station_id = str(data["station_id"])
        fuel = str(data["fuel"])
        status = str(data["status"])
        user_id = int(data.get("user_id") or 0)
        username = data.get("username")
        if username:
            username = str(username).strip()[:40]
            if not core.is_real_username(username):
                username = html.escape(username) if username else None
        else:
            username = None
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return web.json_response({"ok": False, "error": "bad_request"}, status=400)

    if station_id not in core.STATION_BY_ID:
        return web.json_response({"ok": False, "error": "unknown_station"}, status=404)
    is_flag = fuel in dict(core.STATION_FLAGS)
    if is_flag:
        if status not in ("on", "off"):
            return web.json_response({"ok": False, "error": "unknown_status"}, status=400)
    else:
        if fuel not in dict(core.FUELS):
            return web.json_response({"ok": False, "error": "unknown_fuel"}, status=400)
        if status not in dict(core.STATUSES):
            return web.json_response({"ok": False, "error": "unknown_status"}, status=400)

    core.save_report(station_id, fuel, status, user_id, username)
    points_earned = 0
    scouting = False
    if not is_flag:
        scouting = core.is_scouting_report(station_id)
        allow_points = core.can_award_station_points(user_id, station_id)
        if allow_points:
            points_earned = core.POINTS_REPORT + (core.POINTS_SCOUT_BONUS if scouting else 0)
            core.award_points(user_id, username, core.POINTS_REPORT, "report", station_id)
            if scouting:
                core.award_points(user_id, username, core.POINTS_SCOUT_BONUS, "scout_bonus", station_id)
        core.record_daily_activity(user_id, username)
    return web.json_response({"ok": True, "points_earned": points_earned, "scouting": scouting})


@web.middleware
async def cors_middleware(request, handler):
    if request.path.startswith("/api/") and request.method == "OPTIONS":
        resp = web.Response()
    else:
        resp = await handler(request)
    if request.path.startswith("/api/"):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


def build_app() -> web.Application:
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get("/map", handle_map)
    app.router.add_get("/leaflet.js", handle_leaflet_js)
    app.router.add_get("/leaflet.css", handle_leaflet_css)
    app.router.add_get("/manifest.json", handle_manifest)
    app.router.add_get("/sw.js", handle_sw)
    app.router.add_get("/rules", handle_rules)
    app.router.add_get("/api/stations", handle_stations)
    app.router.add_get("/api/user-stats", handle_user_stats)
    app.router.add_post("/api/report", handle_report)
    app.router.add_route("OPTIONS", "/api/{tail:.*}", lambda request: web.Response())
    return app


async def run_webserver(port: int):
    app = build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    core.log.info(f"Веб-сервер карты запущен на порту {port}")
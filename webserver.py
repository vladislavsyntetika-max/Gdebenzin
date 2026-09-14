"""
Веб-сервер для карты «ГДЕ БЕНЗИН!?».
Работает в том же процессе, что и бот (см. bot.py -> main()).
Статика (HTML, JS, CSS) отдаётся из папки webapp/.
"""

import html
import json
import os
import time
from aiohttp import web
import bot as core

PHOTOS_DIR = os.getenv("PHOTOS_DIR", "/data/photos" if os.path.isdir("/data") else "data/photos")
MAX_PHOTO_SIZE = 5 * 1024 * 1024  # 5 МБ


# ---------- Статика ----------

async def handle_map(request):
    return web.FileResponse("webapp/map.html")


async def handle_leaflet_js(request):
    return web.FileResponse("webapp/leaflet.js")


async def handle_leaflet_css(request):
    return web.FileResponse("webapp/leaflet.css")


async def handle_manifest(request):
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


# ---------- API ----------

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

        # Последнее фото по каждой станции
        photos_by_station = {}
        try:
            photo_rows = conn.execute("""
                SELECT station_id, file_path, username, ts FROM (
                    SELECT station_id, file_path, username, ts,
                           ROW_NUMBER() OVER (PARTITION BY station_id ORDER BY ts DESC) AS rn
                    FROM photos
                ) WHERE rn = 1
            """)
            for sid, fpath, uname, pts in photo_rows:
                photos_by_station[sid] = (fpath, uname, pts)
        except Exception:
            pass
    finally:
        conn.close()

    def confidence_for(station_id, fuel, current_status):
        recent = recent_by_key.get((station_id, fuel))
        if not recent:
            return None
        matches = sum(1 for s in recent if s == current_status)
        return round(matches / len(recent) * 100)

    def last_photo_for(sid):
        row = photos_by_station.get(sid)
        if not row:
            return None
        fpath, uname, pts = row
        fname = os.path.basename(fpath)
        return {
            "url": f"/api/photo/{sid}/{fname}",
            "username": uname,
            "ago": core.time_ago(pts),
            "ts": pts,
        }

    def build_station_obj(sid, name, net, addr, lat, lng):
        rep = reports_by_station.get(sid, {})
        fuels = {}
        for key, label in core.FUELS:
            if key in rep:
                status, ts = rep[key]
                fuels[key] = {
                    "status": status,
                    "label": label,
                    "ago": core.time_ago(ts),
                    "stale": core.is_stale(ts),
                    "ts": ts,
                    "confidence": confidence_for(sid, key, status),
                }
            else:
                fuels[key] = {"status": "unknown", "label": label, "ago": None,
                              "stale": False, "ts": 0, "confidence": None}
        flags = {}
        for key, label in core.STATION_FLAGS:
            if key in rep:
                status, ts = rep[key]
                flags[key] = {"on": status == "on" and not core.is_stale(ts),
                              "label": label, "ago": core.time_ago(ts), "ts": ts}
            else:
                flags[key] = {"on": False, "label": label, "ago": None, "ts": 0}
        return {
            "id": sid, "name": name, "net": net, "addr": addr,
            "lat": lat, "lng": lng, "fuels": fuels, "flags": flags,
            "last_photo": last_photo_for(sid),
        }

    result = []
    for sid, name, net, addr, lat, lng in core.STATIONS:
        result.append(build_station_obj(sid, name, net, addr, lat, lng))

    try:
        custom_rows = core.get_custom_stations()
    except AttributeError:
        custom_rows = []
    for row in custom_rows:
        sid, name, net, addr, lat, lng = row[0], row[1], row[2], row[3], row[4], row[5]
        result.append(build_station_obj(sid, name, net, addr, lat, lng))

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

    try:
        exists = core.station_exists(station_id)
    except AttributeError:
        exists = station_id in core.STATION_BY_ID
    if not exists:
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


async def handle_add_station(request):
    try:
        data = await request.json()
        lat = float(data["lat"])
        lng = float(data["lng"])
        net = str(data["net"]).strip()
        fuels = data.get("fuels") or {}
        user_id = int(data.get("user_id") or 0)
        username = str(data.get("username") or "").strip()[:40] or None
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return web.json_response({"ok": False, "error": "bad_request"}, status=400)

    admin_id = getattr(core, "ADMIN_ID", 0)
    if not admin_id or user_id != admin_id:
        return web.json_response({"ok": False, "error": "forbidden"}, status=403)

    if net not in core.NETWORKS:
        return web.json_response({"ok": False, "error": "unknown_network"}, status=400)
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        return web.json_response({"ok": False, "error": "bad_coords"}, status=400)

    try:
        station_id = core.add_custom_station(
            name=core.NETWORKS[net]["label"], net=net,
            addr="Добавлено с карты", lat=lat, lng=lng, user_id=user_id,
        )
    except AttributeError:
        return web.json_response({"ok": False, "error": "bot_not_updated"}, status=500)

    for fuel_key, status_val in (fuels or {}).items():
        if fuel_key in dict(core.FUELS) and status_val in dict(core.STATUSES):
            core.save_report(station_id, fuel_key, status_val, user_id, username)

    return web.json_response({
        "ok": True,
        "station": {"id": station_id, "name": core.NETWORKS[net]["label"]},
    })


async def handle_delete_station(request):
    """
    POST /api/delete-station
    Тело JSON: { station_id, user_id }
    Удаляет только custom-станции (с префиксом custom-). Только для админа.
    """
    try:
        data = await request.json()
        station_id = str(data["station_id"])
        user_id = int(data.get("user_id") or 0)
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return web.json_response({"ok": False, "error": "bad_request"}, status=400)

    admin_id = getattr(core, "ADMIN_ID", 0)
    if not admin_id or user_id != admin_id:
        return web.json_response({"ok": False, "error": "forbidden"}, status=403)

    if not station_id.startswith("custom-"):
        return web.json_response({"ok": False, "error": "only_custom_stations"}, status=400)

    try:
        core.delete_custom_station(station_id)
    except AttributeError:
        return web.json_response({"ok": False, "error": "bot_not_updated"}, status=500)

    return web.json_response({"ok": True})


async def handle_upload_photo(request):
    try:
        reader = await request.multipart()
    except Exception:
        return web.json_response({"ok": False, "error": "not_multipart"}, status=400)

    station_id = None
    user_id = 0
    username = None
    photo_bytes = None
    photo_name = "photo.jpg"

    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "station_id":
            station_id = (await part.text()).strip()
        elif part.name == "user_id":
            try:
                user_id = int((await part.text()).strip() or 0)
            except ValueError:
                user_id = 0
        elif part.name == "username":
            username = (await part.text()).strip()[:40] or None
        elif part.name == "photo":
            photo_name = part.filename or "photo.jpg"
            chunk = await part.read(decode=False)
            if len(chunk) > MAX_PHOTO_SIZE:
                return web.json_response({"ok": False, "error": "too_large"}, status=413)
            photo_bytes = chunk

    try:
        exists = core.station_exists(station_id) if station_id else False
    except AttributeError:
        exists = station_id in core.STATION_BY_ID if station_id else False
    if not exists:
        return web.json_response({"ok": False, "error": "unknown_station"}, status=404)
    if not photo_bytes:
        return web.json_response({"ok": False, "error": "no_photo"}, status=400)

    dir_path = os.path.join(PHOTOS_DIR, station_id)
    os.makedirs(dir_path, exist_ok=True)
    ts = int(time.time())
    ext = ".jpg"
    lower = photo_name.lower()
    if lower.endswith(".png"):
        ext = ".png"
    elif lower.endswith(".webp"):
        ext = ".webp"
    file_path = os.path.join(dir_path, f"{ts}{ext}")
    with open(file_path, "wb") as f:
        f.write(photo_bytes)

    try:
        core.save_photo(station_id, file_path, user_id, username)
    except AttributeError:
        pass

    return web.json_response({
        "ok": True,
        "station_id": station_id,
        "photo_url": f"/api/photo/{station_id}/{ts}{ext}",
        "ts": ts,
    })


async def handle_get_photo(request):
    station_id = request.match_info["station_id"]
    filename = request.match_info["filename"]
    if "/" in filename or ".." in filename or "\\" in filename:
        return web.Response(status=400)
    if "/" in station_id or ".." in station_id or "\\" in station_id:
        return web.Response(status=400)
    path = os.path.join(PHOTOS_DIR, station_id, filename)
    if not os.path.isfile(path):
        return web.Response(status=404)
    return web.FileResponse(path)


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
    app.router.add_post("/api/add-station", handle_add_station)
    app.router.add_post("/api/delete-station", handle_delete_station)
    app.router.add_post("/api/upload-photo", handle_upload_photo)
    app.router.add_get("/api/photo/{station_id}/{filename}", handle_get_photo)
    app.router.add_route("OPTIONS", "/api/{tail:.*}", lambda request: web.Response())
    return app


async def run_webserver(port: int):
    app = build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    core.log.info(f"Веб-сервер карты запущен на порту {port}")
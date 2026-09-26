"""
Веб-сервер для карты «ГДЕ БЕНЗИН!?».
Работает в том же процессе, что и бот (см. bot.py -> main()).
Статика (HTML, JS, CSS) отдаётся из папки webapp/.
"""

import asyncio
import html
import json
import os
import time
from aiohttp import web
import bot as core

PHOTOS_DIR = os.getenv("PHOTOS_DIR", "/data/photos" if os.path.isdir("/data") else "data/photos")
MAX_PHOTO_SIZE = 5 * 1024 * 1024  # 5 МБ


# ---------- Статика ----------

def _record_ref(request, where):
    try:
        ref = (request.query.get("ref") or "").strip().lower()
        ref = "".join(c for c in ref if c.isalnum() or c in "_-")[:20]
        core.inc_metric(f"{where}_view")
        if ref:
            core.inc_metric(f"ref_{where}_{ref}")
    except Exception:
        core.log.exception("_record_ref failed")


async def handle_landing(request):
    """Рендерит лендинг с актуальным числом станций."""
    try:
        with open("webapp/landing.html", "r", encoding="utf-8") as f:
            tpl = f.read()
    except Exception as e:
        core.log.exception("landing.html не прочитан: %s", e)
        return web.Response(status=500, text="landing template error")

    _record_ref(request, "landing")
    total = len(core.STATIONS)
    try:
        total += len(core.get_custom_stations())
    except AttributeError:
        pass
    # Вычесть override-deleted станции (они скрыты на карте)
    try:
        deleted = sum(1 for r in core.get_station_overrides() if r[6])
        total = max(0, total - deleted)
    except Exception:
        pass

    html_out = tpl.replace("{{COUNT}}", str(total))
    resp = web.Response(text=html_out, content_type="text/html", charset="utf-8")
    resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp


async def handle_map(request):
    _record_ref(request, "map")
    resp = web.FileResponse("webapp/map.html")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


async def handle_leaflet_js(request):
    return web.FileResponse("webapp/leaflet.js")


async def handle_leaflet_css(request):
    return web.FileResponse("webapp/leaflet.css")


async def handle_manifest(request):
    manifest = {
        "name": "ГДЕ БЕНЗИН!? — топливо в реале",
        "short_name": "Где бензин",
        "description": "Карта наличия топлива на АЗС СПб и ЛО от самих водителей.",
        "start_url": "/map",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#14171A",
        "theme_color": "#14171A",
        "lang": "ru",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}
        ],
    }
    return web.json_response(manifest, content_type="application/manifest+json")


async def handle_icon_192(request):
    return web.FileResponse("webapp/icon-192.png")


async def handle_icon_512(request):
    return web.FileResponse("webapp/icon-512.png")
async def handle_apple_icon(request):
    return web.FileResponse("webapp/apple-touch-icon.png")
async def handle_favicon(request):
    return web.FileResponse("webapp/icon-192.png")

async def handle_sw(request):
    sw = "self.addEventListener('install', e => self.skipWaiting());"
    return web.Response(text=sw, content_type="application/javascript")


async def handle_rules(request):
    rules = """<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Правила — ГДЕ БЕНЗИН!?</title>
<style>body{background:#14171A;color:#E8E6E1;font-family:-apple-system,sans-serif;
padding:20px;line-height:1.6;max-width:640px;margin:0 auto}
h1{font-size:20px}h2{font-size:16px;color:#FFB000;margin-top:24px}
a{color:#FFB000}</style>
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
<p><a href="/map">← Вернуться к карте</a></p>
</body></html>"""
    return web.Response(text=rules, content_type="text/html")


# ---------- API ----------

_STATIONS_CACHE = {"ts": 0.0, "json": None, "content_type": "application/json; charset=utf-8"}
_STATIONS_CACHE_TTL = 600.0  # 10 минут — данные меняются медленно
_STATIONS_CACHE_LOCK = asyncio.Lock()


def _build_stations_payload():
    """Синхронно собирает payload карты. Вызывается из handle_stations и warmup-таска."""
    conn = core.db()
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
        cutoff = int(time.time()) - 3 * 86400   # 3 суток — данные видны дольше
        day_ago = int(time.time()) - 86400      # только для счётчика «за 24ч»

        reports_by_station = {}
        for station_id, fuel, status, ts in conn.execute(
            "SELECT station_id, fuel, status, ts FROM reports WHERE ts > ?", (cutoff,)
        ):
            reports_by_station.setdefault(station_id, {})[fuel] = (status, ts)

        recent_by_key = {}
        recent_rows = conn.execute("""
            SELECT station_id, fuel, status FROM (
                SELECT station_id, fuel, status,
                ROW_NUMBER() OVER (PARTITION BY station_id, fuel ORDER BY ts DESC) AS rn
            FROM feed WHERE ts > ?
        ) WHERE rn <= 5
    """, (cutoff,))
        for station_id, fuel, status in recent_rows:
            recent_by_key.setdefault((station_id, fuel), []).append(status)

        reports_24h = conn.execute(
            "SELECT COUNT(*) FROM feed WHERE ts > ?", (day_ago,)
        ).fetchone()[0]

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
        now_ts = int(time.time())
        for key, label in core.FUELS:
            if key in rep:
                status, ts = rep[key]
                age = now_ts - ts
                if age < 8 * 3600:
                    fresh_level = "fresh"
                elif age < 48 * 3600:
                    fresh_level = "stale"
                elif age < 72 * 3600:
                    fresh_level = "old"
                else:
                    fresh_level = "gone"
                fuels[key] = {
                    "status": status,
                    "label": label,
                    "ago": core.time_ago(ts),
                    "stale": core.is_stale(ts),
                    "fresh_level": fresh_level,
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

    try:
        ov_rows = core.get_station_overrides()
    except AttributeError:
        ov_rows = []
    ov = {}
    for r in ov_rows:
        ov[r[0]] = {"name": r[1], "net": r[2], "addr": r[3], "lat": r[4], "lng": r[5], "deleted": r[6]}

    def apply_ov(sid, name, net, addr, lat, lng):
        o = ov.get(sid)
        if not o:
            return (sid, name, net, addr, lat, lng, False)
        if o["deleted"]:
            return None
        return (
            sid,
            o["name"] if o["name"] is not None else name,
            o["net"] if o["net"] is not None else net,
            o["addr"] if o["addr"] is not None else addr,
            o["lat"] if o["lat"] is not None else lat,
            o["lng"] if o["lng"] is not None else lng,
            False,
        )

    result = []
    for sid, name, net, addr, lat, lng in core.STATIONS:
        row = apply_ov(sid, name, net, addr, lat, lng)
        if row:
            result.append(build_station_obj(row[0], row[1], row[2], row[3], row[4], row[5]))

    try:
        custom_rows = core.get_custom_stations()
    except AttributeError:
        custom_rows = []
    for row in custom_rows:
        sid, name, net, addr, lat, lng = row[0], row[1], row[2], row[3], row[4], row[5]
        r2 = apply_ov(sid, name, net, addr, lat, lng)
        if r2:
            result.append(build_station_obj(r2[0], r2[1], r2[2], r2[3], r2[4], r2[5]))

    try:
        dps_rows = core.get_active_dps_reports(ttl_sec=1800)
    except AttributeError:
        dps_rows = []
    dps_list = [{"lat": r[0], "lng": r[1], "ts": r[2], "kind": (r[3] if len(r) > 3 else "dps")} for r in dps_rows]

    payload = {
        "stations": result,
        "networks": core.NETWORKS,
        "fuels": core.FUELS,
        "statuses": core.STATUSES,
        "station_flags": core.STATION_FLAGS,
        "reports_24h": reports_24h,
        "dps": dps_list,
    }
    return payload


def _refresh_stations_cache():
    """Пересобирает payload и обновляет кэш. Запускается warmup-таском."""
    t0 = time.time()
    payload = _build_stations_payload()
    t1 = time.time()
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    t2 = time.time()
    _STATIONS_CACHE["ts"] = time.time()
    _STATIONS_CACHE["json"] = body
    core.log.info(f"refresh: build={t1-t0:.2f}s json={t2-t1:.2f}s total={t2-t0:.2f}s bytes={len(body)}")
    return len(body)


async def handle_stations(request):
    try:
        core.inc_metric("api_hits")
    except Exception:
        core.log.exception("metrics api_hits failed")
    _no_cache_headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    now = time.time()
    if _STATIONS_CACHE["json"] is not None and (now - _STATIONS_CACHE["ts"]) < _STATIONS_CACHE_TTL:
        return web.Response(
            body=_STATIONS_CACHE["json"],
            content_type="application/json",
            charset="utf-8",
            headers=_no_cache_headers,
        )
    # Холодный кэш — считаем синхронно
    _refresh_stations_cache()
    return web.Response(
        body=_STATIONS_CACHE["json"],
        content_type="application/json",
        charset="utf-8",
        headers=_no_cache_headers,
    )


async def stations_warmup_task(interval_sec=15):
    # Первый прогрев — сразу, до первого запроса
    for attempt in range(3):
        try:
            size = await asyncio.get_event_loop().run_in_executor(None, _refresh_stations_cache)
            core.log.info(f"warmup: кэш станций прогрет, {size} байт (попытка {attempt+1})")
            break
        except Exception as e:
            core.log.exception(f"warmup: попытка {attempt+1} упала")
            await asyncio.sleep(3)

    while True:
        await asyncio.sleep(interval_sec)
        try:
            t0 = time.time()
            size = await asyncio.get_event_loop().run_in_executor(None, _refresh_stations_cache)
            dt = time.time() - t0
            core.log.info(f"warmup: перегрев {size} байт за {dt:.2f} сек")
        except Exception:
            core.log.exception("warmup: перегрев кэша упал")
    """Греет кэш в фоне, чтобы у юзера TTFB был ~0.1 сек всегда."""
    # Первый прогрев при старте
    try:
        size = await asyncio.get_event_loop().run_in_executor(None, _refresh_stations_cache)
        core.log.info(f"warmup: кэш станций прогрет, {size} байт")
    except Exception:
        core.log.exception("warmup: первичный прогрев упал")

    while True:
        await asyncio.sleep(interval_sec)
        try:
            size = await asyncio.get_event_loop().run_in_executor(None, _refresh_stations_cache)
        except Exception:
            core.log.exception("warmup: перегрев кэша упал")
    
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


async def handle_report_batch(request):
    """
    POST /api/report-batch
    Тело JSON: { station_id, user_id, username, fuels: {f92:'ok',...}, flags: {flag_queue:true,...} }
    Пишет все отметки батчем. Работает и для Telegram, и для анонимных веб-гостей.
    """
    try:
        data = await request.json()
        station_id = str(data["station_id"])
        user_id = int(data.get("user_id") or 0)
        username = data.get("username")
        if username:
            username = str(username).strip()[:40]
            if not core.is_real_username(username):
                username = html.escape(username) if username else None
        else:
            username = None
        fuels = data.get("fuels") or {}
        flags = data.get("flags") or {}
        if not isinstance(fuels, dict) or not isinstance(flags, dict):
            raise ValueError("bad_shape")
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return web.json_response({"ok": False, "error": "bad_request"}, status=400)

    try:
        exists = core.station_exists(station_id)
    except AttributeError:
        exists = station_id in core.STATION_BY_ID
    if not exists:
        return web.json_response({"ok": False, "error": "unknown_station"}, status=404)

    fuel_keys = dict(core.FUELS)
    status_keys = dict(core.STATUSES)
    flag_keys = dict(core.STATION_FLAGS)

    saved_fuel = False
    for fuel_key, status_val in fuels.items():
        if fuel_key in fuel_keys and status_val in status_keys:
            core.save_report(station_id, fuel_key, status_val, user_id, username)
            saved_fuel = True

    # Автоснятие остальных очередей: если активен один flag_queue_N — остальные false
    queue_flags = ["flag_queue_1", "flag_queue_2", "flag_queue_3"]
    active_queue = None
    for fq in queue_flags:
        if fq in flags and flags[fq]:
            active_queue = fq
            break
    if active_queue:
        for fq in queue_flags:
            if fq != active_queue:
                flags[fq] = False

    for flag_key, on in flags.items():
        if flag_key in flag_keys:
            core.save_report(station_id, flag_key, "on" if on else "off", user_id, username)

    points_earned = 0
    scouting = False
    if saved_fuel:
        scouting = core.is_scouting_report(station_id)
        allow_points = core.can_award_station_points(user_id, station_id)
        if allow_points:
            points_earned = core.POINTS_REPORT + (core.POINTS_SCOUT_BONUS if scouting else 0)
            core.award_points(user_id, username, core.POINTS_REPORT, "report", station_id)
            if scouting:
                core.award_points(user_id, username, core.POINTS_SCOUT_BONUS, "scout_bonus", station_id)
        core.record_daily_activity(user_id, username)

    return web.json_response({"ok": True, "points_earned": points_earned, "scouting": scouting})


async def handle_report_issue(request):
    """
    POST /api/report-issue
    Тело: { station_id, text, user_id?, username? }
    Для веб-гостей без Telegram — заявка сохраняется в БД, админ увидит её в общем потоке.
    """
    try:
        data = await request.json()
        station_id = data.get("station_id") or None
        if station_id is not None:
            station_id = str(station_id)
        text = str(data.get("text") or "").strip()
        user_id = int(data.get("user_id") or 0)
        username = str(data.get("username") or "").strip()[:40] or "веб-гость"
        if not text:
            raise ValueError("empty_text")
        if len(text) > 2000:
            text = text[:2000]
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return web.json_response({"ok": False, "error": "bad_request"}, status=400)

    if station_id:
        try:
            exists = core.station_exists(station_id)
        except AttributeError:
            exists = station_id in core.STATION_BY_ID
        if not exists:
            station_id = None  # не блокируем, но и не привязываем к фейку

    try:
        issue_id = core.save_issue(station_id, user_id, username, text)
    except Exception as e:
        core.log.exception("save_issue failed: %s", e)
        return web.json_response({"ok": False, "error": "db_error"}, status=500)

    # Уведомляем админа в Telegram (если ADMIN_ID задан)
    try:
        admin_id = getattr(core, "ADMIN_ID", 0)
        if admin_id:
            from aiogram import Bot
            from aiogram.client.default import DefaultBotProperties
            bot = Bot(token=core.BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
            try:
                station_line = ""
                if station_id:
                    s = core.get_station(station_id)
                    if s:
                        station_line = f"\nСтанция: {s[1]}, {s[3]} (id: {station_id})"
                safe_text = html.escape(text)
                msg = (
                    f"⚠️ Неточность #{issue_id} (веб)\n"
                    f"От: {html.escape(username)} (id {user_id}){station_line}\n\n{safe_text}"
                )
                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                fix_kb = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="✅ Исправлено", callback_data=f"fix:{issue_id}")
                ]])
                await bot.send_message(admin_id, msg, reply_markup=fix_kb)
            finally:
                await bot.session.close()
    except Exception as e:
        core.log.warning("Не удалось уведомить админа о веб-заявке: %s", e)

    return web.json_response({"ok": True, "issue_id": issue_id})

async def handle_share_credit(request):
    """POST /api/share-credit — начисление баллов за репост (не чаще 1 раза в сутки)."""
    try:
        data = await request.json()
        user_id = int(data.get("user_id") or 0)
        username = data.get("username") or None
        if username:
            username = str(username).strip()[:40]
            if not core.is_real_username(username):
                username = html.escape(username) if username else None
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return web.json_response({"ok": False, "error": "bad_request"}, status=400)
    if not user_id:
        return web.json_response({"ok": False, "error": "no_user"}, status=400)
    try:
        earned = core.award_share_points(user_id, username)
    except AttributeError:
        return web.json_response({"ok": False, "error": "bot_not_updated"}, status=500)
    except Exception:
        core.log.exception("share_credit failed")
        return web.json_response({"ok": False, "error": "db_error"}, status=500)
    return web.json_response({"ok": True, "points_earned": earned})

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

    try:
        _refresh_stations_cache()
    except Exception:
        core.log.exception("cache refresh after add failed")

    return web.json_response({
        "ok": True,
        "station": {"id": station_id, "name": core.NETWORKS[net]["label"]},
    })


async def handle_dps_report(request):
    try:
        data = await request.json()
        lat = float(data["lat"])
        lng = float(data["lng"])
        user_id = int(data.get("user_id") or 0)
        username = str(data.get("username") or "")[:64]
        kind = str(data.get("kind") or "dps")
        if kind not in ("dps", "camera"):
            kind = "dps"
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return web.json_response({"ok": False, "error": "bad_request"}, status=400)

    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        return web.json_response({"ok": False, "error": "bad_coords"}, status=400)

    try:
        core.save_dps_report(lat, lng, user_id, username, kind=kind)
    except AttributeError:
        return web.json_response({"ok": False, "error": "bot_not_updated"}, status=500)

    return web.json_response({"ok": True})


async def handle_delete_station(request):
    try:
        data = await request.json()
        station_id = str(data["station_id"])
        user_id = int(data.get("user_id") or 0)
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return web.json_response({"ok": False, "error": "bad_request"}, status=400)

    admin_id = getattr(core, "ADMIN_ID", 0)
    if not admin_id or user_id != admin_id:
        return web.json_response({"ok": False, "error": "forbidden"}, status=403)

    try:
        if station_id.startswith("custom-"):
            core.delete_custom_station(station_id)
        else:
            core.upsert_station_override(station_id, deleted=1)
    except AttributeError:
        return web.json_response({"ok": False, "error": "bot_not_updated"}, status=500)

    try:
        _refresh_stations_cache()
    except Exception:
        core.log.exception("cache refresh after delete failed")

    return web.json_response({"ok": True})


async def handle_edit_station(request):
    try:
        data = await request.json()
        station_id = str(data["station_id"])
        user_id = int(data.get("user_id") or 0)
        fields = {}
        for k in ("name", "net", "addr"):
            if k in data and data[k] is not None:
                fields[k] = str(data[k]).strip()[:200]
        for k in ("lat", "lng"):
            if k in data and data[k] is not None:
                v = float(data[k])
                if (k == "lat" and not -90 <= v <= 90) or (k == "lng" and not -180 <= v <= 180):
                    return web.json_response({"ok": False, "error": "bad_coords"}, status=400)
                fields[k] = v
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return web.json_response({"ok": False, "error": "bad_request"}, status=400)

    admin_id = getattr(core, "ADMIN_ID", 0)
    if not admin_id or user_id != admin_id:
        return web.json_response({"ok": False, "error": "forbidden"}, status=403)

    if fields.get("net") and fields["net"] not in core.NETWORKS:
        return web.json_response({"ok": False, "error": "unknown_network"}, status=400)

    try:
        core.upsert_station_override(station_id, **fields)
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


@web.middleware
async def gzip_middleware(request, handler):
    resp = await handler(request)
    accept = request.headers.get("Accept-Encoding", "")
    if "gzip" not in accept.lower():
        return resp
    if resp.headers.get("Content-Encoding"):
        return resp
    ct = (resp.content_type or "").lower()
    if ct not in ("application/json", "text/html", "application/javascript",
                  "text/css", "text/plain", "image/svg+xml"):
        return resp
    body = getattr(resp, "body", None)
    if body is None or len(body) < 512:
        return resp
    import gzip as _gzip
    compressed = _gzip.compress(body, 5)
    resp.body = compressed
    resp.headers["Content-Encoding"] = "gzip"
    resp.headers["Content-Length"] = str(len(compressed))
    resp.headers["Vary"] = "Accept-Encoding"
    return resp

def build_app() -> web.Application:
    app = web.Application(middlewares=[cors_middleware, gzip_middleware])
    app.router.add_get("/", handle_landing)
    app.router.add_get("/map", handle_map)
    app.router.add_get("/leaflet.js", handle_leaflet_js)
    app.router.add_get("/leaflet.css", handle_leaflet_css)
    app.router.add_get("/manifest.json", handle_manifest)
    app.router.add_get("/sw.js", handle_sw)
    app.router.add_get("/rules", handle_rules)
    app.router.add_get("/icon-192.png", handle_icon_192)
    app.router.add_get("/icon-512.png", handle_icon_512)
    app.router.add_get("/apple-touch-icon.png", handle_apple_icon)
    app.router.add_get("/apple-touch-icon-precomposed.png", handle_apple_icon)
    app.router.add_get("/favicon.ico", handle_favicon)
    app.router.add_get("/api/stations", handle_stations)
    app.router.add_post("/api/dps-report", handle_dps_report)
    app.router.add_get("/api/user-stats", handle_user_stats)
    app.router.add_post("/api/report", handle_report)
    app.router.add_post("/api/report-batch", handle_report_batch)
    app.router.add_post("/api/report-issue", handle_report_issue)
    app.router.add_post("/api/share-credit", handle_share_credit)
    app.router.add_post("/api/add-station", handle_add_station)
    app.router.add_post("/api/delete-station", handle_delete_station)
    app.router.add_post("/api/edit-station", handle_edit_station)
    app.router.add_post("/api/upload-photo", handle_upload_photo)
    app.router.add_get("/api/photo/{station_id}/{filename}", handle_get_photo)
    app.router.add_route("OPTIONS", "/api/{tail:.*}", lambda request: web.Response())
    return app


async def run_webserver(port: int):
    import hashlib
    for f in ("webapp/map.html", "webapp/landing.html", "webserver.py"):
        try:
            with open(f, "rb") as fh:
                h = hashlib.md5(fh.read()).hexdigest()
            core.log.info(f"startup: {f} md5={h}")
        except Exception as e:
            core.log.warning(f"startup: не смог прочитать {f}: {e}")

    app = build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    core.log.info(f"Веб-сервер карты запущен на порту {port}")
    asyncio.create_task(stations_warmup_task())

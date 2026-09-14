import base64
import re
import os

for path in ['webserver.py', 'bot/webserver.py', '../webserver.py']:
    if os.path.exists(path):
        WEB_PATH = path
        break
else:
    print("❌ Не нашёл webserver.py")
    exit(1)

print(f"📄 Обрабатываю: {WEB_PATH}")

with open(WEB_PATH, 'r', encoding='utf-8') as f:
    content = f.read()

match = re.search(r'MAP_HTML_B64 = "([^"]+)"', content)
if not match:
    print("❌ MAP_HTML_B64 не найден")
    exit(1)

b64 = match.group(1)
html = base64.b64decode(b64).decode('utf-8')

# 1. Заменяем упрощённый bindPopup на полный с popupHtml
html = html.replace(
    "marker.bindPopup(`<b>${s.name}</b><br>${s.addr}`);",
    "marker.bindPopup(popupHtml(s), {\n      maxWidth: 300, minWidth: 260,\n      autoPanPaddingTopLeft: L.point(16, 100),\n      autoPanPaddingBottomRight: L.point(16, 80),\n    });\n    marker.on('popupclose', () => {\n      if (s.id === proximityStationId) clearProximityState();\n    });"
)
print("✅ Восстановил bindPopup с popupHtml")

# 2. Добавляем функцию popupHtml перед закрывающим </script>, если её нет
if 'function popupHtml(s)' not in html:
    popup_fn = """
const STATUS_COLOR = { ok: "#1B8A4A", low: "#C97C00", none: "#C62828", unknown: "#8A8F98" };
const STATUS_LABEL = { ok: "Есть", low: "Мало", none: "Нет" };
const SEVERITY = { ok: 0, low: 1, none: 2 };
const FLAG_LABEL_SHORT = { flag_queue: "🚗 Очередь", flag_limit: "⛔ Лимит" };

function popupHtml(s) {
  let rows = '';
  fuelsData.forEach(([key, label]) => {
    const f = s.fuels[key];
    const known = f.status !== 'unknown' && !f.stale;
    const timeText = f.status !== 'unknown' ? (f.stale ? 'устарело' : f.ago) : 'нет данных';
    const confText = (known && f.confidence !== null && f.confidence !== undefined) ? ` · ${f.confidence}% совпало` : '';
    let btns = '';
    statusesData.forEach(([stKey, stLabelFull]) => {
      const shortLabel = STATUS_LABEL[stKey] || stLabelFull;
      btns += `<button class="sbtn ${stKey}${known && f.status === stKey ? ' current' : ''}" onclick="submitReport('${s.id}','${key}','${stKey}', this)">${shortLabel}</button>`;
    });
    rows += `<div class="fuel-block">
      <div class="fuel-head"><b>${label}</b><span class="fuel-time">${timeText}${confText}</span></div>
      <div class="fuel-btns">${btns}</div>
    </div>`;
  });

  let flagBtns = '';
  (stationFlagsData || []).forEach(([fkey, flabelFull]) => {
    const fl = s.flags ? s.flags[fkey] : null;
    const on = fl && fl.on;
    const shortLabel = FLAG_LABEL_SHORT[fkey] || flabelFull;
    flagBtns += `<button class="flag-btn${on ? ' on' : ''}" onclick="toggleFlag('${s.id}','${fkey}', this)">${shortLabel}</button>`;
  });
  rows += `<div class="flags-row">${flagBtns}</div>`;

  const starClass = isFav(s.id) ? '⭐' : '☆';
  rows += `<div class="popup-actions">
      <button class="route-btn" onclick="openRoute(${s.lat},${s.lng})">🧭 Маршрут</button>
    </div>
    <div class="issue-row">
      <button class="issue-btn" onclick="reportStationIssue('${s.id}')">️ Сообщить о неточности</button>
    </div>`;
  return `<div class="popup-title">${s.name}<span class="fav-star" onclick="toggleFavInPopup('${s.id}', this)">${starClass}</span></div><div class="popup-addr">${s.addr}</div>${rows}`;
}

function toggleFavInPopup(id, el) {
  toggleFav(id);
  el.textContent = isFav(id) ? '⭐' : '☆';
  if (favOnly) renderMarkers();
}
window.toggleFavInPopup = toggleFavInPopup;

async function toggleFlag(stationId, flagKey, btn) {
  const s = stationsData.find(x => x.id === stationId);
  const currentlyOn = s && s.flags && s.flags[flagKey] && s.flags[flagKey].on;
  const newStatus = currentlyOn ? 'off' : 'on';
  btn.classList.toggle('on', !currentlyOn);
  try {
    await fetch('/api/report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ station_id: stationId, fuel: flagKey, status: newStatus, user_id: userId }),
    });
    if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
    if (s) s.flags[flagKey] = { on: newStatus === 'on', label: s.flags[flagKey].label, ago: 'только что' };
  } catch (e) { console.error(e); }
}
window.toggleFlag = toggleFlag;

function openRoute(lat, lng) {
  const url = `https://yandex.ru/maps/?rtext=~${lat},${lng}&rtt=auto`;
  if (tg && tg.openLink) tg.openLink(url); else window.open(url, '_blank');
}
window.openRoute = openRoute;

function openBotDeepLink(payload) {
  const url = `https://t.me/${BOT_USERNAME}?start=${payload}`;
  if (tg && tg.openTelegramLink) {
    tg.openTelegramLink(url);
  } else {
    window.open(url, '_blank');
  }
}

function reportStationIssue(id) {
  openBotDeepLink('err_' + id.replace(/-/g, '_'));
}

async function submitReport(stationId, fuel, status, btn) {
  btn.classList.add('current');
  try {
    await fetch('/api/report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ station_id: stationId, fuel, status, user_id: userId }),
    });
    if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
    loadMyStats();
    const s = stationsData.find(x => x.id === stationId);
    if (s) {
      s.fuels[fuel] = { status, label: s.fuels[fuel].label, ago: 'только что', stale: false };
      const marker = markers[stationId];
      if (marker) {
        marker.setIcon(makeIcon(STATUS_COLOR[statusFor(s.fuels, activeFuel)]));
        marker.setPopupContent(popupHtml(s));
      }
    }
  } catch (e) { console.error(e); }
}
window.submitReport = submitReport;

function makeIcon(color) {
  return L.divIcon({
    className: '',
    html: `<div style="width:16px;height:16px;border-radius:50%;background:${color};border:2px solid #14171A;box-shadow:0 0 4px rgba(0,0,0,0.5)"></div>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });
}

function statusFor(fuels, fuelKey) {
  if (fuelKey !== 'all') {
    const f = fuels[fuelKey];
    return (f && f.status !== 'unknown' && !f.stale) ? f.status : 'unknown';
  }
  let worst = -1, any = false;
  for (const key in fuels) {
    const f = fuels[key];
    if (f.status !== "unknown" && !f.stale) { any = true; worst = Math.max(worst, SEVERITY[f.status]); }
  }
  if (!any) return "unknown";
  return worst === 0 ? "ok" : worst === 1 ? "low" : "none";
}
"""
    html = html.replace('</script>', popup_fn + '</script>')
    print("✅ Добавил функцию popupHtml и все вспомогательные функции")
else:
    print("️ popupHtml уже есть")

# Кодируем обратно
new_b64 = base64.b64encode(html.encode('utf-8')).decode('ascii')
content = content.replace(b64, new_b64)

with open(WEB_PATH, 'w', encoding='utf-8') as f:
    f.write(content)

print("\n ГОТОВО! Карточки станций восстановлены.")
print("Теперь выполните:")
print("  git add webserver.py")
print("  git commit -m 'fix: восстановлены карточки станций с кнопками топлива'")
print("  git push origin main")
import { useState, useEffect, useRef, useMemo } from "react";
import { Fuel, MapPin, Clock, RefreshCw, Search, ChevronDown, ChevronUp, AlertTriangle, CheckCircle2, CircleDashed, Radio } from "lucide-react";

const NETWORKS = {
  gpn: { label: "Газпромнефть", color: "#3E7CB1" },
  lukoil: { label: "Лукойл", color: "#D64550" },
  rosneft: { label: "Роснефть", color: "#C98A2E" },
  neste: { label: "Neste", color: "#2FA6A6" },
  tatneft: { label: "Татнефть", color: "#8B5FBF" },
  ptk: { label: "ПТК", color: "#E07A3F" },
};

const FUELS = [
  { key: "f92", label: "АИ-92" },
  { key: "f95", label: "АИ-95" },
  { key: "f98", label: "АИ-98" },
  { key: "dt", label: "ДТ" },
];

const STATUS = {
  ok: { label: "Есть", color: "#4CAF7D", bg: "rgba(76,175,125,0.16)", ring: "#4CAF7D" },
  low: { label: "Мало", color: "#E8A93D", bg: "rgba(232,169,61,0.16)", ring: "#E8A93D" },
  none: { label: "Нет", color: "#E5484D", bg: "rgba(229,72,77,0.16)", ring: "#E5484D" },
  unknown: { label: "Нет данных", color: "#8A8F98", bg: "rgba(138,143,152,0.12)", ring: "#4A4E56" },
};

const STATIONS = [
  { id: "gpn-1", name: "Газпромнефть", net: "gpn", addr: "ул. Десантников, 21", lat: 59.8534, lng: 30.1992 },
  { id: "gpn-2", name: "Газпромнефть", net: "gpn", addr: "Кушелевская дорога, 8", lat: 59.9886, lng: 30.3680 },
  { id: "gpn-3", name: "Газпромнефть", net: "gpn", addr: "Индустриальный пр., 68", lat: 59.9696, lng: 30.4560 },
  { id: "gpn-4", name: "Газпромнефть", net: "gpn", addr: "Планерная ул., 30", lat: 60.0083, lng: 30.2352 },
  { id: "gpn-5", name: "Газпромнефть", net: "gpn", addr: "ул. Полевая Сабировская, 56", lat: 59.9978, lng: 30.2691 },
  { id: "gpn-6", name: "Газпромнефть", net: "gpn", addr: "Лахтинский пр., 149А", lat: 59.9954, lng: 30.1235 },
  { id: "gpn-7", name: "Газпромнефть", net: "gpn", addr: "ул. Седова, 43к2", lat: 59.8867, lng: 30.4223 },
  { id: "gpn-8", name: "Газпромнефть", net: "gpn", addr: "Софийская ул., 69", lat: 59.8554, lng: 30.4221 },
  { id: "gpn-9", name: "Газпромнефть", net: "gpn", addr: "Придорожная аллея, 28", lat: 60.0534, lng: 30.3736 },
  { id: "luk-1", name: "Лукойл", net: "lukoil", addr: "ул. Розенштейна, 37", lat: 59.9042, lng: 30.2869 },
  { id: "luk-2", name: "Лукойл", net: "lukoil", addr: "Херсонский пр., 4", lat: 59.9289, lng: 30.3858 },
  { id: "luk-3", name: "Лукойл АЗС №95", net: "lukoil", addr: "Литовская ул., 5а", lat: 59.9776, lng: 30.3471 },
  { id: "luk-4", name: "Лукойл", net: "lukoil", addr: "Кушелевская дорога, 18", lat: 59.9905, lng: 30.3728 },
  { id: "luk-5", name: "Лукойл", net: "lukoil", addr: "Благодатная ул., 10", lat: 59.8762, lng: 30.3066 },
  { id: "luk-6", name: "Лукойл", net: "lukoil", addr: "Дальневосточный пр., 40", lat: 59.8949, lng: 30.4624 },
  { id: "luk-7", name: "Лукойл", net: "lukoil", addr: "пр. Просвещения, 10", lat: 60.0592, lng: 30.3070 },
  { id: "luk-8", name: "Лукойл", net: "lukoil", addr: "Выборгская наб., 18", lat: 59.9697, lng: 30.3368 },
  { id: "luk-9", name: "Лукойл АЗС №33", net: "lukoil", addr: "Московское ш., 13Д", lat: 59.8244, lng: 30.3551 },
  { id: "ptk-1", name: "Petersburg Fuel Company", net: "ptk", addr: "пр. Маршала Жукова, 10а", lat: 59.8661, lng: 30.2440 },
  { id: "ptk-2", name: "ПТК", net: "ptk", addr: "Левашовский пр., 19лА", lat: 59.9670, lng: 30.2835 },
  { id: "ros-1", name: "Роснефть", net: "rosneft", addr: "Театральная пл., 7лА", lat: 59.9269, lng: 30.2981 },
  { id: "ros-2", name: "Роснефть АЗС №17", net: "rosneft", addr: "пр. Наставников, 2к1", lat: 59.9348, lng: 30.4865 },
  { id: "ros-3", name: "Роснефть АЗС №17", net: "rosneft", addr: "пр. Ветеранов, 182", lat: 59.8347, lng: 30.1257 },
  { id: "ros-4", name: "Роснефть АЗС №17", net: "rosneft", addr: "Александровский парк, 8лА", lat: 59.9532, lng: 30.3221 },
  { id: "ros-5", name: "Роснефть", net: "rosneft", addr: "Коломяжский пр., 13к7", lat: 59.9991, lng: 30.3005 },
  { id: "ros-6", name: "Роснефть АЗС №17", net: "rosneft", addr: "пр. Королёва, 40", lat: 60.0181, lng: 30.2566 },
  { id: "ros-7", name: "Роснефть АЗС №17", net: "rosneft", addr: "ул. Книповича, 11лА", lat: 59.9076, lng: 30.3940 },
  { id: "ros-8", name: "Роснефть АЗС №17", net: "rosneft", addr: "ул. Маршала Казакова, 25а", lat: 59.8604, lng: 30.2173 },
  { id: "nes-1", name: "Neste", net: "neste", addr: "Средний пр. В.О., 91к2", lat: 59.9352, lng: 30.2502 },
  { id: "nes-2", name: "Neste", net: "neste", addr: "ул. Партизана Германа, 4", lat: 59.8429, lng: 30.1766 },
  { id: "nes-3", name: "Neste", net: "neste", addr: "Московский пр., 102", lat: 59.8967, lng: 30.3197 },
  { id: "nes-4", name: "Neste", net: "neste", addr: "пр. Испытателей, 2а", lat: 60.0017, lng: 30.3041 },
  { id: "nes-5", name: "Neste", net: "neste", addr: "пр. Косыгина, 20", lat: 59.9456, lng: 30.4800 },
  { id: "nes-6", name: "Neste", net: "neste", addr: "Северный пр., 32", lat: 60.0327, lng: 30.3627 },
  { id: "nes-7", name: "Neste", net: "neste", addr: "Софийская ул., 127к1", lat: 59.8882, lng: 30.3809 },
  { id: "nes-8", name: "Neste", net: "neste", addr: "Выборгское ш., 21", lat: 60.0578, lng: 30.3083 },
  { id: "tat-1", name: "Татнефть", net: "tatneft", addr: "Лабораторный пр., 21", lat: 59.9808, lng: 30.3843 },
  { id: "tat-2", name: "Татнефть", net: "tatneft", addr: "Планерная ул., 57к1", lat: 60.0214, lng: 30.2248 },
  { id: "tat-3", name: "Татнефть", net: "tatneft", addr: "Кузнецовская ул., 35", lat: 59.8719, lng: 30.3450 },
  { id: "tat-4", name: "Татнефть", net: "tatneft", addr: "Вербная ул., 23", lat: 60.0234, lng: 30.2949 },
];

const LAT_MIN = 59.80, LAT_MAX = 60.08, LNG_MIN = 30.10, LNG_MAX = 30.50;
const MAP_W = 640, MAP_H = 420;
function project(lat, lng) {
  const x = ((lng - LNG_MIN) / (LNG_MAX - LNG_MIN)) * MAP_W;
  const y = ((LAT_MAX - lat) / (LAT_MAX - LAT_MIN)) * MAP_H;
  return { x, y };
}

const SEVERITY = { ok: 0, low: 1, none: 2, unknown: -1 };

function timeAgo(ts) {
  if (!ts) return null;
  const diff = Math.max(0, Date.now() - ts);
  const min = Math.floor(diff / 60000);
  if (min < 1) return "только что";
  if (min < 60) return `${min} мин назад`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} ч назад`;
  const days = Math.floor(hr / 24);
  return `${days} дн назад`;
}

function freshness(ts) {
  if (!ts) return "none";
  const hrs = (Date.now() - ts) / 3600000;
  if (hrs < 3) return "fresh";
  if (hrs < 8) return "aging";
  return "stale";
}

function aggregateStatus(report) {
  if (!report) return "unknown";
  let worst = -1;
  let any = false;
  for (const f of FUELS) {
    const r = report[f.key];
    if (r && r.status && freshness(r.ts) !== "none") {
      any = true;
      worst = Math.max(worst, SEVERITY[r.status]);
    }
  }
  if (!any) return "unknown";
  return worst === 0 ? "ok" : worst === 1 ? "low" : "none";
}

export default function FuelMonitor() {
  const [reports, setReports] = useState({});
  const [feed, setFeed] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [tick, setTick] = useState(0);
  const [netFilter, setNetFilter] = useState("all");
  const [fuelFilter, setFuelFilter] = useState("f95");
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState(null);
  const [focusId, setFocusId] = useState(null);
  const [toast, setToast] = useState(null);
  const cardRefs = useRef({});

  useEffect(() => {
    let mounted = true;
    async function load() {
      try {
        const r = await window.storage.get("all-reports", true);
        if (mounted && r) setReports(JSON.parse(r.value));
      } catch (e) {}
      try {
        const f = await window.storage.get("activity-feed", true);
        if (mounted && f) setFeed(JSON.parse(f.value));
      } catch (e) {}
      if (mounted) setLoaded(true);
    }
    load();
    const iv = setInterval(() => setTick((t) => t + 1), 30000);
    return () => { mounted = false; clearInterval(iv); };
  }, []);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2400);
    return () => clearTimeout(t);
  }, [toast]);

  async function submitReport(stationId, fuelKey, status) {
    const now = Date.now();
    const next = { ...reports, [stationId]: { ...(reports[stationId] || {}), [fuelKey]: { status, ts: now } } };
    setReports(next);
    const station = STATIONS.find((s) => s.id === stationId);
    const entry = { ts: now, stationId, name: station.name, addr: station.addr, fuel: FUELS.find((f) => f.key === fuelKey).label, status };
    const nextFeed = [entry, ...feed].slice(0, 60);
    setFeed(nextFeed);
    setToast(`Спасибо! ${station.name}, ${entry.fuel} — ${STATUS[status].label.toLowerCase()}`);
    try {
      await window.storage.set("all-reports", JSON.stringify(next), true);
      await window.storage.set("activity-feed", JSON.stringify(nextFeed), true);
    } catch (e) {}
  }

  const filtered = useMemo(() => {
    return STATIONS.filter((s) => {
      if (netFilter !== "all" && s.net !== netFilter) return false;
      if (query && !(s.addr.toLowerCase().includes(query.toLowerCase()) || s.name.toLowerCase().includes(query.toLowerCase()))) return false;
      return true;
    });
  }, [netFilter, query]);

  const stats = useMemo(() => {
    const dayAgo = Date.now() - 86400000;
    const reportedToday = new Set(feed.filter((f) => f.ts > dayAgo).map((f) => f.stationId)).size;
    const lastTs = feed[0]?.ts || null;
    return { total: STATIONS.length, reportedToday, lastTs };
  }, [feed, tick]);

  function scrollToStation(id) {
    setFocusId(id);
    setExpanded(id);
    setTimeout(() => {
      cardRefs.current[id]?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 50);
    setTimeout(() => setFocusId(null), 2000);
  }

  return (
    <div style={{ fontFamily: "'IBM Plex Sans', ui-sans-serif, system-ui", background: "#14171A", color: "#E8E6E1", borderRadius: 16, padding: "20px 18px 28px", maxWidth: 720, margin: "0 auto" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500&display=swap');
        .mono { font-family: 'IBM Plex Mono', ui-monospace, monospace; }
        .pill { border:none; cursor:pointer; transition: transform .12s ease; }
        .pill:active { transform: scale(0.96); }
        .chip { cursor:pointer; user-select:none; }
        ::-webkit-scrollbar { width:6px; height:6px; }
        ::-webkit-scrollbar-thumb { background:#3A3F45; border-radius:3px; }
      `}</style>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14, flexWrap: "wrap", gap: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ width: 34, height: 34, borderRadius: 8, background: "#1E2227", display: "flex", alignItems: "center", justifyContent: "center", border: "1px solid #2B3036" }}>
            <Fuel size={18} color="#FFB000" />
          </div>
          <div>
            <div style={{ fontSize: 15, fontWeight: 500, letterSpacing: 0.2 }}>АЗС СПб · топливо в реале</div>
            <div style={{ fontSize: 11.5, color: "#8B9098" }}>Данные вносят водители — сообщество</div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 14 }} className="mono">
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 18, color: "#FFB000", fontWeight: 600, lineHeight: 1 }}>{stats.total}</div>
            <div style={{ fontSize: 10, color: "#6E747B" }}>станций</div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 18, color: "#4CAF7D", fontWeight: 600, lineHeight: 1 }}>{stats.reportedToday}</div>
            <div style={{ fontSize: 10, color: "#6E747B" }}>отчётов за 24ч</div>
          </div>
        </div>
      </div>

      <div style={{ background: "#1A1D21", border: "1px solid #262B31", borderRadius: 12, padding: 8, marginBottom: 14, position: "relative" }}>
        <svg viewBox={`0 0 ${MAP_W} ${MAP_H}`} width="100%" style={{ display: "block", borderRadius: 8 }}>
          <rect x="0" y="0" width={MAP_W} height={MAP_H} fill="#171A1E" rx="8" />
          <path d={`M 60 250 C 180 230, 260 260, 330 240 S 480 190, 600 210`} stroke="#20303A" strokeWidth="26" fill="none" strokeLinecap="round" opacity="0.55" />
          <path d={`M 60 250 C 180 230, 260 260, 330 240 S 480 190, 600 210`} stroke="#25384330" strokeWidth="1" fill="none" />
          {filtered.map((s) => {
            const { x, y } = project(s.lat, s.lng);
            const agg = aggregateStatus(reports[s.id]);
            const col = STATUS[agg].color;
            const isFocus = focusId === s.id;
            return (
              <g key={s.id} onClick={() => scrollToStation(s.id)} style={{ cursor: "pointer" }}>
                {isFocus && <circle cx={x} cy={y} r="11" fill="none" stroke={col} strokeWidth="2" opacity="0.8" />}
                <circle cx={x} cy={y} r={agg === "unknown" ? 3.2 : 4.4} fill={col} opacity={agg === "unknown" ? 0.5 : 0.95} stroke="#14171A" strokeWidth="1" />
              </g>
            );
          })}
        </svg>
        <div style={{ display: "flex", gap: 12, padding: "6px 4px 2px", fontSize: 10.5, color: "#8B9098", flexWrap: "wrap" }}>
          {Object.entries(STATUS).map(([k, v]) => (
            <div key={k} style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <span style={{ width: 7, height: 7, borderRadius: "50%", background: v.color, display: "inline-block" }} />
              {v.label}
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 10, alignItems: "center" }}>
        <div style={{ position: "relative", flex: 1 }}>
          <Search size={14} color="#6E747B" style={{ position: "absolute", left: 10, top: 10 }} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Поиск по адресу или сети"
            style={{ width: "100%", boxSizing: "border-box", background: "#1E2227", border: "1px solid #2B3036", borderRadius: 8, padding: "8px 10px 8px 30px", color: "#E8E6E1", fontSize: 13, outline: "none" }}
          />
        </div>
      </div>

      <div style={{ display: "flex", gap: 6, marginBottom: 8, flexWrap: "wrap" }}>
        {FUELS.map((f) => (
          <button key={f.key} onClick={() => setFuelFilter(f.key)} className="pill chip mono"
            style={{ padding: "5px 11px", borderRadius: 7, fontSize: 12, background: fuelFilter === f.key ? "#FFB000" : "#1E2227", color: fuelFilter === f.key ? "#14171A" : "#B7BBC1", border: "1px solid " + (fuelFilter === f.key ? "#FFB000" : "#2B3036") }}>
            {f.label}
          </button>
        ))}
      </div>

      <div style={{ display: "flex", gap: 6, marginBottom: 16, flexWrap: "wrap" }}>
        <button onClick={() => setNetFilter("all")} className="pill chip"
          style={{ padding: "5px 11px", borderRadius: 7, fontSize: 12, background: netFilter === "all" ? "#2B3036" : "transparent", color: "#E8E6E1", border: "1px solid #2B3036" }}>
          Все сети
        </button>
        {Object.entries(NETWORKS).map(([k, v]) => (
          <button key={k} onClick={() => setNetFilter(k)} className="pill chip"
            style={{ padding: "5px 11px", borderRadius: 7, fontSize: 12, background: netFilter === k ? v.color + "33" : "transparent", color: netFilter === k ? v.color : "#9CA0A6", border: "1px solid " + (netFilter === k ? v.color : "#2B3036") }}>
            {v.label}
          </button>
        ))}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {filtered.map((s) => {
          const rep = reports[s.id] || {};
          const isOpen = expanded === s.id;
          const isFocus = focusId === s.id;
          const netColor = NETWORKS[s.net].color;
          return (
            <div key={s.id} ref={(el) => (cardRefs.current[s.id] = el)}
              style={{ background: "#1A1D21", border: "1px solid " + (isFocus ? "#FFB000" : "#262B31"), borderRadius: 12, padding: "12px 14px", transition: "border-color .3s ease" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 2 }}>
                    <span style={{ width: 7, height: 7, borderRadius: "50%", background: netColor, flexShrink: 0 }} />
                    <span style={{ fontSize: 13.5, fontWeight: 500 }}>{s.name}</span>
                  </div>
                  <div style={{ fontSize: 12, color: "#8B9098", display: "flex", alignItems: "center", gap: 4 }}>
                    <MapPin size={11} /> {s.addr}
                  </div>
                </div>
                <button onClick={() => setExpanded(isOpen ? null : s.id)} className="pill"
                  style={{ background: "transparent", border: "1px solid #2B3036", borderRadius: 7, padding: "5px 9px", color: "#B7BBC1", display: "flex", alignItems: "center", gap: 4, fontSize: 11.5 }}>
                  Отметить {isOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                </button>
              </div>

              <div style={{ display: "flex", gap: 6, marginTop: 9, flexWrap: "wrap" }}>
                {FUELS.map((f) => {
                  const r = rep[f.key];
                  const st = r && freshness(r.ts) !== "none" ? r.status : "unknown";
                  const fr = r ? freshness(r.ts) : "none";
                  const s0 = STATUS[st];
                  const emphasize = f.key === fuelFilter;
                  return (
                    <div key={f.key} style={{ display: "flex", alignItems: "center", gap: 5, padding: "4px 8px", borderRadius: 7, background: s0.bg, border: emphasize ? `1px solid ${s0.ring}` : "1px solid transparent" }}>
                      <span className="mono" style={{ fontSize: 10.5, color: s0.color, fontWeight: 600 }}>{f.label}</span>
                      <span style={{ fontSize: 11, color: s0.color }}>{s0.label}</span>
                      {r && <span style={{ fontSize: 9.5, color: "#6E747B" }}>· {fr === "stale" ? "устарело" : timeAgo(r.ts)}</span>}
                    </div>
                  );
                })}
              </div>

              {isOpen && (
                <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px solid #262B31", display: "flex", flexDirection: "column", gap: 7 }}>
                  {FUELS.map((f) => (
                    <div key={f.key} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span className="mono" style={{ fontSize: 11.5, width: 42, color: "#B7BBC1" }}>{f.label}</span>
                      <div style={{ display: "flex", gap: 5, flex: 1 }}>
                        {["ok", "low", "none"].map((st) => (
                          <button key={st} onClick={() => submitReport(s.id, f.key, st)} className="pill"
                            style={{ flex: 1, padding: "6px 0", borderRadius: 6, fontSize: 11.5, background: STATUS[st].bg, color: STATUS[st].color, border: `1px solid ${STATUS[st].ring}55` }}>
                            {STATUS[st].label}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
        {filtered.length === 0 && (
          <div style={{ textAlign: "center", padding: "24px 0", color: "#6E747B", fontSize: 13 }}>Ничего не найдено</div>
        )}
      </div>

      <div style={{ marginTop: 20 }}>
        <div style={{ fontSize: 12, color: "#8B9098", marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
          <Radio size={12} /> Лента отчётов сообщества
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 220, overflowY: "auto", paddingRight: 4 }}>
          {feed.length === 0 && <div style={{ fontSize: 12, color: "#565B62" }}>Пока нет отчётов — станьте первым.</div>}
          {feed.slice(0, 20).map((e, i) => (
            <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5, padding: "6px 10px", background: "#1A1D21", borderRadius: 7, border: "1px solid #232830" }}>
              <span style={{ color: "#B7BBC1" }}>{e.name} · <span className="mono" style={{ color: STATUS[e.status].color }}>{e.fuel} {STATUS[e.status].label.toLowerCase()}</span></span>
              <span style={{ color: "#565B62" }} className="mono">{timeAgo(e.ts)}</span>
            </div>
          ))}
        </div>
      </div>

      {!loaded && (
        <div style={{ position: "absolute", inset: 0 }} />
      )}

      {toast && (
        <div style={{ position: "sticky", bottom: 8, marginTop: 14, background: "#232830", border: "1px solid #3A3F45", borderRadius: 9, padding: "9px 13px", fontSize: 12.5, color: "#E8E6E1", display: "flex", alignItems: "center", gap: 7 }}>
          <CheckCircle2 size={14} color="#4CAF7D" /> {toast}
        </div>
      )}
    </div>
  );
}

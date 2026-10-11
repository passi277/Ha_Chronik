/*
 * Chronik Card – what happened in the garden, day by day.
 * Shipped with the Chronik integration and loaded automatically.
 * Design follows the "HA Modern Home Cards" family.
 */

const CARD_VERSION = "0.3.2";

const CAT = {
  rain: { icon: "mdi:weather-pouring", color: "#42a5f5" },
  irrigation: { icon: "mdi:sprinkler-variant", color: "#26c6da" },
  mowing: { icon: "mdi:robot-mower", color: "#66bb6a" },
  pool: { icon: "mdi:pool", color: "#5c6bc0" },
  alarm: { icon: "mdi:shield-alert", color: "#ef5350" },
  ai: { icon: "mdi:creation", color: "#ab47bc" },
  other: { icon: "mdi:note-text-outline", color: "#8d6e63" },
};
const CAT_ORDER = ["rain", "irrigation", "mowing", "pool", "alarm", "ai", "other"];
const KIND_ICON = { error: "mdi:alert-circle", arming: "mdi:shield-lock", reset: "mdi:counter" };

const I18N = {
  de: {
    title: "Chronik", all: "Alle", today: "Heute", yesterday: "Gestern", running: "läuft",
    since: "seit", entries: "{n} Einträge", entry: "1 Eintrag", no_entries: "Keine Einträge",
    today_count: "Heute {n}", today_none: "Heute noch nichts", last: "zuletzt",
    more: "{n} weitere", loading: "Lade …", empty: "In diesem Zeitraum ist nichts passiert.",
    refresh: "Aktualisieren", close: "Schließen", days: "{n} T", source: "Quelle",
    duration: "Dauer", amount: "Menge", water: "Wasser", counter: "Zähler vorher", time: "Zeit",
    missing: "Chronik-Integration nicht geladen", zoom: "Bild vergrößern", open_image: "Bild öffnen", runs: "{n}× ", findings: "Befunde",
    cat_rain: "Regen", cat_irrigation: "Bewässerung", cat_mowing: "Mähen", cat_pool: "Pool",
    cat_alarm: "Alarme", cat_ai: "KI-Befunde", cat_other: "Notizen",
    stat_rain: "Regen", stat_irrigation: "{n} Läufe", stat_irrigation1: "1 Lauf",
    stat_mowing: "{n}× gemäht", stat_pool: "Pool", stat_alarm: "Alarme", stat_ai: "Befunde", stat_other: "Notizen",
  },
  en: {
    title: "Chronicle", all: "All", today: "Today", yesterday: "Yesterday", running: "running",
    since: "since", entries: "{n} entries", entry: "1 entry", no_entries: "No entries",
    today_count: "Today {n}", today_none: "Nothing yet today", last: "last",
    more: "{n} more", loading: "Loading …", empty: "Nothing happened in this period.",
    refresh: "Refresh", close: "Close", days: "{n} d", source: "Source",
    duration: "Duration", amount: "Amount", water: "Water", counter: "Counter before", time: "Time",
    missing: "Chronik integration not loaded", zoom: "Enlarge image", open_image: "Open image", runs: "{n}× ", findings: "findings",
    cat_rain: "Rain", cat_irrigation: "Irrigation", cat_mowing: "Mowing", cat_pool: "Pool",
    cat_alarm: "Alarms", cat_ai: "AI findings", cat_other: "Notes",
    stat_rain: "Rain", stat_irrigation: "{n} runs", stat_irrigation1: "1 run",
    stat_mowing: "mowed {n}×", stat_pool: "Pool", stat_alarm: "Alarms", stat_ai: "Findings", stat_other: "Notes",
  },
};

const REFRESH_MS = 2 * 60_000;
/** Signed media URLs are valid for a day – cache them across cards. */
const URL_TTL_MS = 20 * 3600_000;
const urlCache = new Map();
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const dayKey = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const startOfDay = (d) => { const x = new Date(d); x.setHours(0, 0, 0, 0); return x; };
const catOf = (e) => (CAT[e.category] && e.category !== "other" ? e.category : "other");

class ChronikCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._events = [];
    this._categories = [];
    this._loaded = false;
    this._loading = false;
    this._error = "";
    this._filter = "all";
    this._day = null;
    this._shown = 25;
    this._open = null;
    this._days = 7;
    this._sig = "";
    this._urls = {};
    this._pending = new Set();
  }

  static getStubConfig() {
    return { days: 7 };
  }

  setConfig(config) {
    this._config = { days: 7, limit: 25, show_stats: true, show_week: true, show_filters: true, ...config };
    this._days = Number(this._config.days) || 7;
    this._shown = Number(this._config.limit) || 25;
    this._render();
    if (this._hass) this._load(true);
  }

  getCardSize() {
    return 10;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    // Reload when one of the Chronik calendars changes (new or finished entry).
    const sig = Object.keys(hass.states)
      .filter((id) => id.startsWith("calendar.chronik"))
      .map((id) => `${id}:${hass.states[id].last_updated}`)
      .join("|");
    if (first || sig !== this._sig) {
      this._sig = sig;
      this._load(!first);
    }
  }

  connectedCallback() {
    this._timer = window.setInterval(() => this._load(true), REFRESH_MS);
    this._tick = window.setInterval(() => this._render(), 60_000);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
    clearInterval(this._tick);
  }

  // ---------- helpers ----------

  get _lang() {
    return this._hass?.locale?.language || this._hass?.language || "de";
  }

  _t(key, n) {
    const table = I18N[this._lang.startsWith("de") ? "de" : "en"];
    const text = table[key] ?? I18N.en[key] ?? key;
    return n === undefined ? text : text.replace("{n}", n);
  }

  _num(v, digits = 1) {
    return new Intl.NumberFormat(this._lang, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v);
  }

  _dur(sec) {
    const m = Math.round(sec / 60);
    if (sec > 0 && m === 0) return "<1 min";
    const h = Math.floor(m / 60);
    const r = m % 60;
    if (h && r) return `${h} h ${r} min`;
    if (h) return `${h} h`;
    return `${m} min`;
  }

  _time(iso) {
    return new Date(iso).toLocaleTimeString(this._lang, { hour: "2-digit", minute: "2-digit" });
  }

  _rel(iso) {
    const sec = (Date.now() - new Date(iso).getTime()) / 1000;
    const rtf = new Intl.RelativeTimeFormat(this._lang, { numeric: "auto", style: "short" });
    if (sec < 60) return rtf.format(0, "minute");
    if (sec < 3600) return rtf.format(-Math.round(sec / 60), "minute");
    if (sec < 86400) return rtf.format(-Math.round(sec / 3600), "hour");
    return rtf.format(-Math.round(sec / 86400), "day");
  }

  _dayLabel(d) {
    const diff = Math.round((startOfDay(new Date()) - startOfDay(d)) / 86400_000);
    if (diff === 0) return this._t("today");
    if (diff === 1) return this._t("yesterday");
    return d.toLocaleDateString(this._lang, { weekday: "short", day: "numeric", month: "short" });
  }

  _seconds(e) {
    if (e.running) {
      const seg = e.data?.seg_start ? new Date(e.data.seg_start) : new Date(e.start);
      return (e.data?.active_s || 0) + Math.max(0, (Date.now() - seg.getTime()) / 1000);
    }
    if (e.data && "active_s" in e.data) return e.data.active_s;
    return e.end ? (new Date(e.end) - new Date(e.start)) / 1000 : 0;
  }

  /** Short value shown on the right of an entry. */
  _value(e) {
    const d = e.data || {};
    if (e.category === "rain" && d.mm != null) return `${this._num(d.mm)} ${d.unit || "mm"}`;
    if (d.kind === "run") {
      const parts = [e.running ? this._t("running") : this._dur(this._seconds(e))];
      if (d.liters) parts.push(`${this._num(d.liters, 0)} L`);
      if (d.counter_before != null) parts.push(`${this._num(d.counter_before)} ${d.counter_unit || ""}`.trim());
      return parts.join(" · ");
    }
    return "";
  }

  _images(e) {
    const imgs = e?.data?.images;
    return Array.isArray(imgs) ? imgs.filter((p) => typeof p === "string" && p) : [];
  }

  /** Placeholder that gets an <img> as soon as the URL is resolved. */
  _imgSlot(path, cls) {
    const url = this._urls[path];
    return `<span class="${cls}" imgpath="${esc(path)}">${url ? `<img src="${esc(url)}" alt="" loading="lazy">` : ""}</span>`;
  }

  _directUrl(path) {
    if (/^(https?:|data:|blob:)/.test(path) || path.startsWith("/local/") || path.startsWith("/api/")) return path;
    if (path.startsWith("/config/www/")) return `/local/${path.slice("/config/www/".length)}`;
    return null;
  }

  _mediaId(path) {
    if (path.startsWith("media-source://")) return path;
    const m = path.match(/^\/media\/(?:local\/)?(.+)$/);
    return m ? `media-source://media_source/local/${m[1]}` : null;
  }

  /** Resolve image paths to (signed) URLs and fill the placeholders in place. */
  _resolveImages(paths) {
    if (!this._hass) return;
    for (const path of new Set(paths)) {
      if (this._urls[path] || this._pending.has(path)) continue;
      const direct = this._directUrl(path);
      const cached = urlCache.get(path);
      if (direct || (cached && Date.now() - cached.at < URL_TTL_MS)) {
        this._setUrl(path, direct || cached.url);
        continue;
      }
      const id = this._mediaId(path);
      if (!id || !this._hass.callWS) continue;
      this._pending.add(path);
      this._hass.callWS({ type: "media_source/resolve_media", media_content_id: id })
        .then((r) => {
          if (!r?.url) return;
          const url = /^(https?:|data:)/.test(r.url) ? r.url : this._hass.hassUrl?.(r.url) ?? r.url;
          urlCache.set(path, { url, at: Date.now() });
          this._setUrl(path, url);
        })
        .catch(() => { /* image gone – keep the icon */ })
        .finally(() => this._pending.delete(path));
    }
  }

  _setUrl(path, url) {
    this._urls[path] = url;
    this.shadowRoot.querySelectorAll("[imgpath]").forEach((el) => {
      if (el.getAttribute("imgpath") !== path || el.querySelector("img")) return;
      const img = document.createElement("img");
      img.src = url;
      img.alt = "";
      img.loading = "lazy";
      img.addEventListener("error", () => { el.classList.add("broken"); img.remove(); });
      el.appendChild(img);
    });
  }

  /** Title without the values that are shown separately. */
  _label(e) {
    const base = e.label || e.title || "";
    const kind = e.data?.kind;
    if (catOf(e) === "ai") return e.data?.name || base.split(":")[0];
    if (kind === "run" || kind === "rain") return base.split(" · ")[0];
    return base;
  }

  _desc(e) {
    const c = catOf(e);
    if (c === "ai") return e.data?.text || (e.description || "").split("\n\n")[0];
    if (c === "other" || e.origin === "manual" || e.origin === "service") return e.description || "";
    return "";
  }

  _icon(e) {
    return KIND_ICON[e.data?.kind] || CAT[catOf(e)].icon;
  }

  _moreInfo(entityId) {
    if (!entityId) return;
    this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId }, bubbles: true, composed: true }));
  }

  _haptic(type = "selection") {
    window.dispatchEvent(new CustomEvent("haptic", { detail: type }));
  }

  // ---------- data ----------

  async _load(force = false) {
    if (!this._hass || !this._config || (this._loading && !force)) return;
    this._loading = true;
    this._render();
    const start = startOfDay(new Date(Date.now() - (this._days - 1) * 86400_000));
    const end = new Date(Date.now() + 60_000);
    try {
      const res = await this._hass.callWS({
        type: "chronik/events",
        start: start.toISOString(),
        end: end.toISOString(),
        ...(this._config.entry_id ? { entry_id: this._config.entry_id } : {}),
      });
      const only = this._config.categories;
      this._events = (res.events || [])
        .filter((e) => !only || only.includes(e.category))
        .sort((a, b) => new Date(b.start) - new Date(a.start));
      this._categories = (res.categories || []).filter((c) => !only || only.includes(c));
      this._error = "";
    } catch (err) {
      this._error = err?.message || String(err);
    }
    this._loading = false;
    this._loaded = true;
    this._render();
  }

  _visible() {
    return this._events.filter(
      (e) => (this._filter === "all" || catOf(e) === this._filter) && (!this._day || dayKey(new Date(e.start)) === this._day)
    );
  }

  _stats(events) {
    const s = {};
    for (const e of events) {
      const c = catOf(e);
      const x = (s[c] ||= { n: 0, mm: 0, sec: 0, liters: 0, runs: 0, unit: "mm" });
      x.n += 1;
      if (c === "rain") { x.mm += Number(e.data?.mm || 0); x.unit = e.data?.unit || "mm"; }
      if (e.data?.kind === "run") { x.runs += 1; x.sec += this._seconds(e); x.liters += Number(e.data?.liters || 0); }
    }
    return s;
  }

  // ---------- render ----------

  _renderStats(stats) {
    const cats = [...new Set([...this._categories, ...Object.keys(stats)])].sort((a, b) => CAT_ORDER.indexOf(a) - CAT_ORDER.indexOf(b));
    if (!cats.length) return "";
    const tile = (c) => {
      const x = stats[c] || { n: 0, mm: 0, sec: 0, liters: 0, runs: 0, unit: "mm" };
      let big = String(x.n);
      let unit = "";
      let sub = this._t(`stat_${c}`);
      if (c === "rain") { big = this._num(x.mm); unit = x.unit; }
      else if (c === "irrigation") {
        if (x.liters) { big = this._num(x.liters, 0); unit = "L"; } else { big = String(Math.round(x.sec / 60)); unit = "min"; }
        sub = x.runs === 1 ? this._t("stat_irrigation1") : this._t("stat_irrigation", x.runs);
      } else if (c === "mowing") {
        big = x.sec >= 3600 ? this._num(x.sec / 3600) : String(Math.round(x.sec / 60));
        unit = x.sec >= 3600 ? "h" : "min";
        sub = this._t("stat_mowing", x.runs);
      } else if (c === "pool" || c === "alarm") { unit = "×"; }
      const sel = this._filter === c;
      return `<button class="stat ${sel ? "sel" : ""} ${x.n ? "" : "zero"}" style="--cc:${CAT[c].color}" data-filter="${c}" aria-pressed="${sel}">
        <span class="s-icon"><ha-icon icon="${CAT[c].icon}"></ha-icon></span>
        <span class="s-val"><b>${esc(big)}</b><small>${esc(unit)}</small></span>
        <span class="s-sub">${esc(sub)}</span>
      </button>`;
    };
    return `<div class="stats">${cats.map(tile).join("")}</div>`;
  }

  _renderWeek() {
    const today = startOfDay(new Date());
    const n = Math.min(7, this._days);
    const days = Array.from({ length: n }, (_, i) => new Date(today.getTime() - (n - 1 - i) * 86400_000));
    const byDay = {};
    for (const e of this._events) (byDay[dayKey(new Date(e.start))] ||= []).push(e);
    const rain = days.map((d) => (byDay[dayKey(d)] || []).filter((e) => e.category === "rain").reduce((a, e) => a + Number(e.data?.mm || 0), 0));
    const maxRain = Math.max(1, ...rain);
    return `<div class="week" style="--n:${n}">${days.map((d, i) => {
      const key = dayKey(d);
      const list = byDay[key] || [];
      const cats = CAT_ORDER.filter((c) => c !== "rain" && list.some((e) => catOf(e) === c));
      const sel = this._day === key;
      const isToday = i === n - 1;
      const h = rain[i] ? Math.max(4, (rain[i] / maxRain) * 30) : 0;
      return `<button class="wd ${sel ? "sel" : ""} ${isToday ? "today" : ""}" data-day="${key}" aria-pressed="${sel}">
        <span class="wd-name">${esc(d.toLocaleDateString(this._lang, { weekday: "short" }).replace(".", ""))}</span>
        <span class="wd-num">${d.getDate()}</span>
        <span class="wd-rain" title="${rain[i] ? esc(this._num(rain[i])) + " mm" : ""}">
          ${rain[i] ? `<small>${esc(this._num(rain[i]))}</small>` : ""}
          <span class="bar" style="height:${h}px"></span>
        </span>
        <span class="wd-dots">${cats.slice(0, 4).map((c) => `<i style="--cc:${CAT[c].color}"><ha-icon icon="${CAT[c].icon}"></ha-icon></i>`).join("")}</span>
      </button>`;
    }).join("")}</div>`;
  }

  _renderFilters() {
    const base = this._events.filter((e) => !this._day || dayKey(new Date(e.start)) === this._day);
    const counts = {};
    for (const e of base) counts[catOf(e)] = (counts[catOf(e)] || 0) + 1;
    const cats = CAT_ORDER.filter((c) => counts[c]);
    if (cats.length < 2 && !this._day && this._filter === "all") return "";
    const chip = (key, n) => {
      const sel = this._filter === key;
      const meta = key === "all" ? { icon: "mdi:format-list-bulleted", color: "var(--primary-color)" } : CAT[key];
      return `<button class="chip ${sel ? "sel" : ""}" style="--cc:${meta.color}" data-filter="${key}" aria-pressed="${sel}">
        <ha-icon icon="${meta.icon}"></ha-icon><span>${esc(this._t(key === "all" ? "all" : `cat_${key}`))}</span><small>${n}</small></button>`;
    };
    const day = this._day
      ? `<button class="chip day sel" data-day="${this._day}"><ha-icon icon="mdi:calendar"></ha-icon><span>${esc(this._dayLabel(new Date(this._day + "T12:00:00")))}</span><ha-icon icon="mdi:close"></ha-icon></button>`
      : "";
    return `<div class="chips">${day}${chip("all", base.length)}${cats.map((c) => chip(c, counts[c])).join("")}</div>`;
  }

  _daySummary(list) {
    const s = this._stats(list);
    const parts = [];
    for (const c of CAT_ORDER) {
      const x = s[c];
      if (!x) continue;
      let text = String(x.n);
      if (c === "rain") text = `${this._num(x.mm)} ${x.unit}`;
      else if (c === "irrigation" || c === "mowing") text = x.runs ? this._dur(x.sec) : String(x.n);
      parts.push(`<span class="ds" style="--cc:${CAT[c].color}"><ha-icon icon="${CAT[c].icon}"></ha-icon>${esc(text)}</span>`);
    }
    return parts.join("");
  }

  _renderTimeline(list) {
    if (!list.length) {
      return `<div class="empty"><ha-icon icon="mdi:calendar-blank-outline"></ha-icon><span>${esc(this._loaded ? this._t("empty") : this._t("loading"))}</span></div>`;
    }
    const shown = list.slice(0, this._shown);
    const groups = [];
    for (const e of shown) {
      const key = dayKey(new Date(e.start));
      let g = groups[groups.length - 1];
      if (!g || g.key !== key) groups.push((g = { key, date: startOfDay(new Date(e.start)), items: [] }));
      g.items.push(e);
    }
    const all = {};
    for (const e of list) (all[dayKey(new Date(e.start))] ||= []).push(e);
    let idx = 0;
    return `<div class="timeline">${groups.map((g) => `<div class="day">
      <div class="day-head"><span>${esc(this._dayLabel(g.date))}</span><span class="day-sum">${this._daySummary(all[g.key])}</span></div>
      ${g.items.map((e) => {
        const c = catOf(e);
        const value = this._value(e);
        const range = e.end && e.end !== e.start ? `${this._time(e.start)}–${this._time(e.end)}` : this._time(e.start);
        const desc = this._desc(e);
        const imgs = this._images(e);
        const thumb = imgs.length
          ? `<span class="thumb-wrap">${this._imgSlot(imgs[imgs.length - 1], "thumb")}${imgs.length > 1 ? `<span class="t-count"><ha-icon icon="mdi:image-multiple"></ha-icon>${imgs.length}</span>` : ""}</span>`
          : "";
        return `<button class="item ${e.running ? "running" : ""} ${imgs.length ? "has-img" : ""}" style="--cc:${CAT[c].color};--i:${idx++}" data-uid="${esc(e.uid)}">
          <span class="rail"><span class="dot"><ha-icon icon="${this._icon(e)}"></ha-icon></span></span>${thumb}
          <span class="i-text">
            <span class="i-head"><b>${esc(this._label(e))}</b>${value ? `<span class="pill">${esc(value)}</span>` : ""}</span>
            <span class="i-meta"><time>${esc(e.running ? `${this._t("since")} ${this._time(e.start)}` : range)}</time></span>
            ${desc ? `<span class="i-desc">${esc(desc)}</span>` : ""}
          </span>
        </button>`;
      }).join("")}
    </div>`).join("")}
    ${list.length > this._shown ? `<button class="more" data-more="1"><ha-icon icon="mdi:chevron-down"></ha-icon>${esc(this._t("more", list.length - this._shown))}</button>` : ""}
    </div>`;
  }

  _renderBanner() {
    const running = this._events.filter((e) => e.running);
    if (!running.length) return "";
    return running.map((e) => {
      const c = catOf(e);
      return `<button class="banner" style="--cc:${CAT[c].color}" data-uid="${esc(e.uid)}">
        <span class="b-icon"><ha-icon icon="${this._icon(e)}"></ha-icon></span>
        <span class="b-text"><b>${esc(this._label(e))}</b><small>${esc(this._t("since"))} ${esc(this._time(e.start))} · ${esc(this._dur(this._seconds(e)))}</small></span>
        <span class="live"></span>
      </button>`;
    }).join("");
  }

  _renderDetail() {
    const e = this._open;
    if (!e) return "";
    const c = catOf(e);
    const d = e.data || {};
    const date = new Date(e.start).toLocaleDateString(this._lang, { weekday: "long", day: "numeric", month: "long" });
    const range = e.end && e.end !== e.start ? `${this._time(e.start)}–${this._time(e.end)}` : this._time(e.start);
    const facts = [];
    if (d.kind === "run") facts.push([this._t("duration"), e.running ? `${this._t("running")} · ${this._dur(this._seconds(e))}` : this._dur(this._seconds(e))]);
    if (c === "rain" && d.mm != null) facts.push([this._t("amount"), `${this._num(d.mm)} ${d.unit || "mm"}`]);
    if (d.liters) facts.push([this._t("water"), `${this._num(d.liters, 0)} L`]);
    if (d.counter_before != null) facts.push([this._t("counter"), `${this._num(d.counter_before)} ${d.counter_unit || ""}`.trim()]);
    const text = this._desc(e);
    const source = e.source && this._hass?.states[e.source];
    const imgs = this._images(e);
    const close = `<button class="d-close" data-close="1" aria-label="${esc(this._t("close"))}"><ha-icon icon="mdi:close"></ha-icon></button>`;
    const head = imgs.length
      ? `<div class="d-gal">
          <div class="slides">${imgs.map((p, i) => `<button class="slide" data-full="${i + 1}" aria-label="${esc(this._t("zoom"))}">${this._imgSlot(p, "d-pic")}<span class="ph-icon"><ha-icon icon="${this._icon(e)}"></ha-icon></span></button>`).join("")}</div>
          ${imgs.length > 1 ? `<button class="g-nav prev" data-gal="-1" aria-label="‹"><ha-icon icon="mdi:chevron-left"></ha-icon></button>
            <button class="g-nav next" data-gal="1" aria-label="›"><ha-icon icon="mdi:chevron-right"></ha-icon></button>
            <span class="g-count">1 / ${imgs.length}</span>` : ""}
          <span class="g-zoom"><ha-icon icon="mdi:arrow-expand"></ha-icon></span>
          ${close}
        </div>`
      : `<div class="d-head"><span class="d-icon"><ha-icon icon="${this._icon(e)}"></ha-icon></span>${close}</div>`;
    return `<dialog class="detail" style="--cc:${CAT[c].color}">
      ${head}
      <div class="d-body">
        <span class="badge"><ha-icon icon="${CAT[c].icon}"></ha-icon>${esc(this._t(`cat_${c}`))}</span>
        <h3>${esc(this._label(e))}</h3>
        <div class="d-meta"><ha-icon icon="mdi:clock-outline"></ha-icon>${esc(date)}, ${esc(range)} · ${esc(this._rel(e.start))}</div>
        ${facts.length ? `<div class="facts">${facts.map(([k, v]) => `<div class="fact"><small>${esc(k)}</small><b>${esc(v)}</b></div>`).join("")}</div>` : ""}
        ${text ? `<p>${esc(text)}</p>` : ""}
        ${source ? `<button class="d-src" data-entity="${esc(e.source)}"><ha-icon icon="mdi:information-outline"></ha-icon><span>${esc(source.attributes.friendly_name || e.source)}</span><small>${esc(this._t("source"))}</small><ha-icon icon="mdi:chevron-right"></ha-icon></button>` : ""}
      </div>
    </dialog>`;
  }

  _render(force = false) {
    if (!this._config) return;
    const root = this.shadowRoot;
    // Do not rebuild while the detail dialog is open (keeps gallery/zoom state).
    if (!force && this._open && root.querySelector("dialog.detail[open]")) return;
    if (this._error && !this._events.length) {
      root.innerHTML = `<style>${STYLES}</style><ha-card><div class="missing"><ha-icon icon="mdi:alert-circle-outline"></ha-icon>${esc(this._t("missing"))}<small>${esc(this._error)}</small></div></ha-card>`;
      return;
    }
    const list = this._visible();
    const latest = this._events[0];
    const today = dayKey(new Date());
    const todayCount = this._events.filter((e) => dayKey(new Date(e.start)) === today).length;
    const accent = latest ? CAT[catOf(latest)].color : "var(--primary-color)";
    const sub = latest
      ? `${todayCount ? this._t("today_count", todayCount) : this._t("today_none")} · ${this._t("last")} ${this._rel(latest.start)}`
      : this._loaded ? this._t("no_entries") : this._t("loading");
    const range = [7, 30].map((n) => `<button class="seg ${this._days === n ? "sel" : ""}" data-days="${n}">${esc(this._t("days", n))}</button>`).join("");
    const statsEvents = this._events.filter((e) => !this._day || dayKey(new Date(e.start)) === this._day);
    const anim = this._config.animations ?? "full";
    const intro = this._loaded && !this._introDone;
    if (intro) this._introDone = true;

    root.innerHTML = `<style>${STYLES}</style>
      <ha-card class="anim-${esc(anim)} ${intro ? "intro" : ""}" style="--accent:${accent}">
        <div class="glow"><div class="blob b1"></div><div class="blob b2"></div></div>
        <div class="header">
          <span class="h-icon ${this._events.some((e) => e.running) ? "active" : ""}"><ha-icon icon="mdi:calendar-clock"></ha-icon></span>
          <span class="head-text"><span class="h-title">${esc(this._config.title ?? this._t("title"))}</span><span class="h-sub">${esc(sub)}</span></span>
          <span class="segs">${range}</span>
          <button class="refresh ${this._loading ? "spin" : ""}" data-refresh="1" aria-label="${esc(this._t("refresh"))}"><ha-icon icon="mdi:refresh"></ha-icon></button>
        </div>
        ${this._renderBanner()}
        ${this._config.show_stats !== false ? this._renderStats(this._stats(statsEvents)) : ""}
        ${this._config.show_week !== false ? this._renderWeek() : ""}
        ${this._config.show_filters !== false ? this._renderFilters() : ""}
        ${this._renderTimeline(list)}
        ${this._renderDetail()}
      </ha-card>`;

    root.querySelector("ha-card").addEventListener("click", (ev) => this._onClick(ev));
    const dlg = root.querySelector("dialog.detail");
    if (dlg) {
      dlg.addEventListener("close", () => { this._open = null; this._render(true); });
      dlg.addEventListener("click", (ev) => { if (ev.target === dlg) dlg.close(); });
      const slides = dlg.querySelector(".slides");
      const count = dlg.querySelector(".g-count");
      if (slides && count) {
        slides.addEventListener("scroll", () => {
          const i = Math.round(slides.scrollLeft / Math.max(1, slides.clientWidth));
          count.textContent = `${i + 1} / ${slides.children.length}`;
        }, { passive: true });
      }
      if (!dlg.open) dlg.showModal?.();
    }
    const paths = list.slice(0, this._shown).flatMap((e) => this._images(e).slice(-1));
    if (this._open) paths.push(...this._images(this._open));
    this._resolveImages(paths);
  }

  _openLightbox(index) {
    const imgs = this._images(this._open);
    const url = this._urls[imgs[index]];
    const dlg = this.shadowRoot.querySelector("dialog.detail");
    if (!url || !dlg) return;
    const lb = document.createElement("div");
    lb.className = "lightbox";
    lb.innerHTML = `<img src="${esc(url)}" alt="">
      <a class="lb-btn open" href="${esc(url)}" target="_blank" rel="noopener" aria-label="${esc(this._t("open_image"))}"><ha-icon icon="mdi:open-in-new"></ha-icon></a>
      <button class="lb-btn close" aria-label="${esc(this._t("close"))}"><ha-icon icon="mdi:close"></ha-icon></button>`;
    lb.addEventListener("click", (ev) => {
      ev.stopPropagation();
      if (!ev.composedPath().some((n) => n.classList?.contains("open"))) lb.remove();
    });
    dlg.appendChild(lb);
  }

  _onClick(ev) {
    const el = ev.composedPath().find((n) => n instanceof HTMLElement && n.dataset && Object.keys(n.dataset).length);
    if (!el) return;
    const ds = el.dataset;
    if (ds.refresh) { this._haptic("light"); this._load(true); return; }
    if (ds.days) { this._haptic(); this._days = Number(ds.days); this._day = null; this._load(true); return; }
    if (ds.filter) { this._haptic(); this._filter = this._filter === ds.filter && ds.filter !== "all" ? "all" : ds.filter; this._shown = Number(this._config.limit) || 25; this._render(true); return; }
    if (ds.day) { this._haptic(); this._day = this._day === ds.day ? null : ds.day; this._render(true); return; }
    if (ds.more) { this._shown += Number(this._config.limit) || 25; this._render(true); return; }
    if (ds.close) { this.shadowRoot.querySelector("dialog.detail")?.close(); return; }
    if (ds.gal) {
      const slides = this.shadowRoot.querySelector("dialog.detail .slides");
      slides?.scrollBy({ left: Number(ds.gal) * slides.clientWidth, behavior: "smooth" });
      return;
    }
    if (ds.full) { this._haptic("light"); this._openLightbox(Number(ds.full) - 1); return; }
    if (ds.entity) { const id = ds.entity; this.shadowRoot.querySelector("dialog.detail")?.close(); this._moreInfo(id); return; }
    if (ds.uid) { this._haptic("light"); this._open = this._events.find((e) => e.uid === ds.uid) || null; this._render(true); }
  }
}

const STYLES = `
  :host { display: block; }
  button { font: inherit; color: inherit; }
  ha-card {
    --ease-out: cubic-bezier(0.22, 1, 0.36, 1);
    --inner: calc(var(--ha-card-border-radius, 16px) * 0.85);
    position: relative; overflow: hidden; padding: 16px; box-sizing: border-box; height: 100%;
    display: flex; flex-direction: column; gap: 14px; isolation: isolate; container-type: inline-size;
    font-variant-numeric: tabular-nums; transition: background 0.4s;
  }
  ha-card.anim-reduced .blob, ha-card.anim-off .blob, ha-card.anim-off .item, ha-card.anim-off .live,
  ha-card.anim-reduced .live, ha-card.anim-off .h-icon.active::after, ha-card.anim-reduced .h-icon.active::after { animation: none !important; }
  .missing { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 12px; text-align: center; color: var(--error-color, #e53935); }
  .missing small { color: var(--secondary-text-color); }

  .glow { position: absolute; inset: 0; pointer-events: none; z-index: -1; overflow: hidden; }
  .blob { position: absolute; border-radius: 50%; will-change: transform; }
  .b1 { width: 115%; aspect-ratio: 1; left: -8%; top: -62%;
    background: radial-gradient(closest-side, color-mix(in srgb, var(--accent) 26%, transparent), transparent 72%); animation: drift1 18s ease-in-out infinite; }
  .b2 { width: 80%; aspect-ratio: 1; right: -38%; top: -18%;
    background: radial-gradient(closest-side, color-mix(in srgb, var(--accent) 16%, color-mix(in srgb, #fff 5%, transparent)), transparent 70%); animation: drift2 23s ease-in-out infinite; }
  @keyframes drift1 { 0%, 100% { transform: translate(0, 0) scale(1); } 50% { transform: translate(6%, 4%) scale(1.08); } }
  @keyframes drift2 { 0%, 100% { transform: translate(0, 0) scale(1); } 50% { transform: translate(-10%, 8%) scale(0.92); } }

  /* Header */
  .header { display: flex; align-items: center; gap: 10px; }
  .h-icon { position: relative; flex: none; width: 42px; height: 42px; border-radius: 50%; display: grid; place-items: center;
    color: var(--accent); background: color-mix(in srgb, var(--accent) 18%, transparent); transition: background 0.4s, color 0.4s; }
  .h-icon ha-icon { --mdc-icon-size: 24px; }
  .h-icon.active::after { content: ""; position: absolute; inset: 0; border-radius: 50%; animation: ring 2.6s ease-out infinite; }
  @keyframes ring { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 45%, transparent); } 100% { box-shadow: 0 0 0 10px transparent; } }
  .head-text { display: flex; flex-direction: column; min-width: 0; flex: 1; }
  .h-title { font-size: 17px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .h-sub { font-size: 13px; font-weight: 600; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .segs { flex: none; display: flex; padding: 3px; border-radius: 999px; background: rgba(127,127,127,0.12); }
  .seg { border: none; background: none; padding: 5px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; cursor: pointer; color: var(--secondary-text-color);
    transition: background 0.25s, color 0.25s; }
  .seg.sel { background: var(--card-background-color, var(--ha-card-background, #1c1c1c)); color: var(--primary-text-color); box-shadow: 0 1px 4px rgba(0,0,0,0.25); }
  .refresh { flex: none; width: 34px; height: 34px; border-radius: 50%; border: none; padding: 0; display: grid; place-items: center; cursor: pointer;
    background: rgba(127,127,127,0.1); color: var(--secondary-text-color); }
  .refresh ha-icon { --mdc-icon-size: 18px; }
  .refresh.spin ha-icon { animation: spin 1s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* Running banner */
  .banner { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border: none; border-radius: var(--inner); cursor: pointer; text-align: left;
    background: color-mix(in srgb, var(--cc) 16%, transparent); animation: slide-in 0.45s var(--ease-out) both; }
  .b-icon { flex: none; width: 32px; height: 32px; border-radius: 50%; display: grid; place-items: center; color: #fff; background: var(--cc); }
  .b-icon ha-icon { --mdc-icon-size: 18px; }
  .b-text { flex: 1; min-width: 0; display: flex; flex-direction: column; }
  .b-text b { font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .b-text small { font-size: 12px; color: var(--secondary-text-color); }
  .live { flex: none; width: 10px; height: 10px; border-radius: 50%; background: var(--cc); animation: pulse 1.4s ease-in-out infinite; }
  @keyframes pulse { 0%, 100% { opacity: 0.35; transform: scale(0.8); } 50% { opacity: 1; transform: scale(1.15); } }
  @keyframes slide-in { from { opacity: 0; transform: translateY(-6px) scale(0.98); } to { opacity: 1; transform: none; } }

  /* Stats */
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(96px, 1fr)); gap: 8px; }
  .stat { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; padding: 10px 11px; border: none; border-radius: var(--inner); cursor: pointer; text-align: left;
    background: color-mix(in srgb, var(--cc) 11%, rgba(127,127,127,0.06)); transition: background 0.25s, transform 0.2s, box-shadow 0.25s; min-width: 0; }
  .stat:hover { transform: translateY(-1px); }
  .stat.sel { background: color-mix(in srgb, var(--cc) 26%, transparent); box-shadow: inset 0 0 0 2px var(--cc); }
  .stat.zero { opacity: 0.55; }
  .s-icon { width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center; color: #fff; background: var(--cc); margin-bottom: 4px; }
  .s-icon ha-icon { --mdc-icon-size: 16px; }
  .s-val { display: flex; align-items: baseline; gap: 3px; }
  .s-val b { font-size: 22px; font-weight: 500; line-height: 1.1; letter-spacing: -0.01em; }
  .s-val small { font-size: 12px; font-weight: 600; color: var(--secondary-text-color); }
  .s-sub { font-size: 11.5px; font-weight: 600; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }

  /* Week strip */
  .week { display: grid; grid-template-columns: repeat(var(--n), minmax(0, 1fr)); gap: 6px; }
  .wd { display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 8px 2px 7px; border: none; border-radius: 14px; cursor: pointer;
    background: rgba(127,127,127,0.07); transition: background 0.25s, box-shadow 0.25s; min-width: 0; }
  .wd.today { background: color-mix(in srgb, var(--primary-color) 12%, transparent); }
  .wd.sel { box-shadow: inset 0 0 0 2px var(--primary-color); }
  .wd-name { font-size: 10.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: var(--secondary-text-color); }
  .wd-num { font-size: 15px; font-weight: 600; }
  .wd-rain { width: 100%; height: 44px; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; gap: 2px; }
  .wd-rain .bar { width: 10px; max-height: 30px; border-radius: 5px 5px 3px 3px; background: linear-gradient(180deg, #64b5f6, #1e88e5); transition: height 0.6s var(--ease-out); }
  .wd-rain small { font-size: 9.5px; font-weight: 700; line-height: 1; color: #64b5f6; }
  .wd-dots { display: flex; flex-wrap: wrap; justify-content: center; gap: 2px; min-height: 16px; }
  .wd-dots i { width: 16px; height: 16px; border-radius: 50%; display: grid; place-items: center; color: #fff; background: var(--cc); }
  .wd-dots ha-icon { --mdc-icon-size: 11px; }
  @container (max-width: 360px) { .wd-dots i { width: 12px; height: 12px; } .wd-dots ha-icon { display: none; } .wd-num { font-size: 13px; } }

  /* Chips */
  .chips { display: flex; gap: 6px; overflow-x: auto; scrollbar-width: none; padding-bottom: 1px; }
  .chips::-webkit-scrollbar { display: none; }
  .chip { --cc: var(--primary-color); flex: none; display: inline-flex; align-items: center; gap: 5px; padding: 6px 10px 6px 8px; border: none; border-radius: 999px;
    cursor: pointer; font-size: 12.5px; font-weight: 600; background: rgba(127,127,127,0.1); transition: background 0.25s, color 0.25s; }
  .chip ha-icon { --mdc-icon-size: 16px; color: var(--cc); }
  .chip small { font-weight: 700; color: var(--secondary-text-color); }
  .chip.sel { color: #fff; background: var(--cc); }
  .chip.sel ha-icon, .chip.sel small { color: #fff; }

  /* Timeline */
  .timeline { display: flex; flex-direction: column; gap: 12px; }
  .day { display: flex; flex-direction: column; }
  .day-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 0 2px 6px; }
  .day-head > span:first-child { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: var(--secondary-text-color); white-space: nowrap; }
  .day-sum { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 4px; }
  .ds { display: inline-flex; align-items: center; gap: 3px; padding: 2px 7px 2px 5px; border-radius: 999px; font-size: 11px; font-weight: 700;
    color: var(--cc); background: color-mix(in srgb, var(--cc) 13%, transparent); }
  .ds ha-icon { --mdc-icon-size: 13px; }
  .item { display: grid; grid-template-columns: 28px minmax(0, 1fr); align-items: start; gap: 10px; padding: 7px 8px 7px 0; border: none; background: none;
    cursor: pointer; text-align: left; border-radius: 12px; transition: background 0.2s; }
  ha-card.intro .item { animation: fade-up 0.4s var(--ease-out) both; animation-delay: calc(min(var(--i), 12) * 25ms); }
  .item:hover { background: rgba(127,127,127,0.07); }
  .item.has-img { grid-template-columns: 28px 72px minmax(0, 1fr); }
  .thumb-wrap { position: relative; width: 72px; height: 54px; }
  .thumb { display: block; width: 100%; height: 100%; border-radius: 10px; overflow: hidden;
    background: color-mix(in srgb, var(--cc) 14%, rgba(127,127,127,0.08)); }
  .thumb img, .d-pic img { display: block; width: 100%; height: 100%; object-fit: cover; animation: img-in 0.35s ease both; }
  @keyframes img-in { from { opacity: 0; } to { opacity: 1; } }
  .t-count { position: absolute; right: 4px; bottom: 4px; display: inline-flex; align-items: center; gap: 2px; padding: 1px 5px 1px 4px; border-radius: 999px;
    font-size: 10.5px; font-weight: 700; color: #fff; background: rgba(0,0,0,0.55); backdrop-filter: blur(4px); }
  .t-count ha-icon { --mdc-icon-size: 12px; }
  @container (max-width: 340px) { .item.has-img { grid-template-columns: 24px 56px minmax(0, 1fr); } .thumb-wrap { width: 56px; height: 42px; } }
  @keyframes fade-up { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
  .rail { position: relative; align-self: stretch; display: flex; justify-content: center; }
  .rail::before { content: ""; position: absolute; top: -7px; bottom: -7px; width: 2px; background: rgba(127,127,127,0.2); }
  .day .item:first-of-type .rail::before { top: 14px; }
  .day .item:last-of-type .rail::before { bottom: calc(100% - 14px); }
  .day .item:only-of-type .rail::before { display: none; }
  .dot { position: relative; margin-top: 1px; width: 28px; height: 28px; border-radius: 50%; display: grid; place-items: center; color: #fff; background: var(--cc);
    box-shadow: 0 0 0 3px var(--card-background-color, var(--ha-card-background, #1c1c1c)); }
  .dot ha-icon { --mdc-icon-size: 16px; }
  .item.running .dot::after { content: ""; position: absolute; inset: -3px; border-radius: 50%; border: 2px solid var(--cc); animation: pulse 1.4s ease-in-out infinite; }
  .i-text { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .i-head { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .i-head b { flex: 1; min-width: 0; font-size: 14px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .pill { flex: none; padding: 2px 8px; border-radius: 999px; font-size: 11.5px; font-weight: 700; color: var(--cc);
    background: color-mix(in srgb, var(--cc) 14%, transparent); white-space: nowrap; }
  .item.running .pill { color: #fff; background: var(--cc); }
  .i-meta { font-size: 12px; font-weight: 600; color: var(--secondary-text-color); }
  .i-desc { font-size: 12.5px; line-height: 1.35; color: var(--secondary-text-color); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .more { display: flex; align-items: center; justify-content: center; gap: 6px; padding: 9px; border: none; border-radius: 12px; cursor: pointer;
    font-size: 13px; font-weight: 600; background: rgba(127,127,127,0.08); color: var(--secondary-text-color); }
  .more ha-icon { --mdc-icon-size: 18px; }
  .empty { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 18px 8px; font-size: 13px; color: var(--secondary-text-color); text-align: center; }
  .empty ha-icon { --mdc-icon-size: 32px; opacity: 0.6; }

  /* Detail */
  dialog.detail { width: min(94vw, 520px); max-height: 92dvh; padding: 0; border: none; border-radius: var(--ha-card-border-radius, 16px); overflow: auto;
    color: var(--primary-text-color); background: var(--card-background-color, var(--ha-card-background, #1c1c1c)); }
  dialog.detail::backdrop { background: rgba(0,0,0,0.6); backdrop-filter: blur(3px); }
  .d-gal { position: relative; aspect-ratio: 16 / 9; background: #0d0d0d; }
  .slides { display: flex; width: 100%; height: 100%; overflow-x: auto; scroll-snap-type: x mandatory; scrollbar-width: none; }
  .slides::-webkit-scrollbar { display: none; }
  .slide { position: relative; flex: 0 0 100%; height: 100%; padding: 0; border: none; background: none; scroll-snap-align: center; cursor: zoom-in; }
  .d-pic { position: absolute; inset: 0; z-index: 1; }
  .d-pic img { object-fit: contain; }
  .d-pic:has(img) { background: #0d0d0d; }
  .d-pic.broken { display: none; }
  .ph-icon { position: absolute; inset: 0; display: grid; place-items: center;
    background: radial-gradient(120% 120% at 30% 10%, color-mix(in srgb, var(--cc) 45%, #222), #121212); }
  .ph-icon ha-icon { --mdc-icon-size: 56px; color: color-mix(in srgb, var(--cc) 70%, #fff); opacity: 0.6; }
  .g-nav { position: absolute; top: 50%; transform: translateY(-50%); z-index: 2; width: 36px; height: 36px; border-radius: 50%; border: none; padding: 0;
    display: grid; place-items: center; cursor: pointer; color: #fff; background: rgba(0,0,0,0.45); backdrop-filter: blur(4px); }
  .g-nav.prev { left: 10px; } .g-nav.next { right: 10px; }
  .g-nav ha-icon { --mdc-icon-size: 22px; }
  .g-count, .g-zoom { position: absolute; bottom: 10px; z-index: 2; padding: 3px 9px; border-radius: 999px; font-size: 11.5px; font-weight: 700; color: #fff;
    background: rgba(0,0,0,0.5); backdrop-filter: blur(4px); pointer-events: none; }
  .g-count { left: 10px; }
  .g-zoom { right: 10px; display: grid; place-items: center; padding: 5px; }
  .g-zoom ha-icon { --mdc-icon-size: 16px; }
  .d-gal .d-close { z-index: 3; }
  .lightbox { position: fixed; inset: 0; z-index: 10; display: grid; place-items: center; background: rgba(0,0,0,0.92); cursor: zoom-out;
    animation: img-in 0.25s ease both; }
  .lightbox img { max-width: 100vw; max-height: 100dvh; object-fit: contain; }
  .lb-btn { position: absolute; top: 14px; width: 40px; height: 40px; border-radius: 50%; border: none; padding: 0; display: grid; place-items: center;
    cursor: pointer; color: #fff; background: rgba(255,255,255,0.14); text-decoration: none; }
  .lb-btn.close { right: 14px; } .lb-btn.open { right: 62px; }
  .lb-btn ha-icon { --mdc-icon-size: 22px; }
  .d-head { position: relative; height: 110px; display: grid; place-items: center;
    background: radial-gradient(120% 120% at 30% 10%, color-mix(in srgb, var(--cc) 55%, #222), color-mix(in srgb, var(--cc) 12%, #121212)); }
  .d-icon { width: 64px; height: 64px; border-radius: 50%; display: grid; place-items: center; color: #fff; background: color-mix(in srgb, var(--cc) 80%, #000);
    box-shadow: 0 6px 22px color-mix(in srgb, var(--cc) 50%, transparent); }
  .d-icon ha-icon { --mdc-icon-size: 34px; }
  .d-close { position: absolute; top: 10px; right: 10px; width: 36px; height: 36px; border-radius: 50%; border: none; padding: 0; display: grid; place-items: center;
    cursor: pointer; color: #fff; background: rgba(0,0,0,0.35); backdrop-filter: blur(4px); }
  .d-close ha-icon { --mdc-icon-size: 20px; }
  .d-close:focus:not(:focus-visible) { outline: none; }
  .d-body { display: flex; flex-direction: column; align-items: flex-start; gap: 10px; padding: 14px 16px 16px; }
  .badge { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px 4px 7px; border-radius: 999px; font-size: 11.5px; font-weight: 700; color: #fff; background: var(--cc); }
  .badge ha-icon { --mdc-icon-size: 15px; }
  .d-body h3 { margin: 0; font-size: 19px; line-height: 1.25; }
  .d-meta { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; font-size: 12.5px; color: var(--secondary-text-color); }
  .d-meta ha-icon { --mdc-icon-size: 15px; }
  .facts { align-self: stretch; display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 8px; }
  .fact { display: flex; flex-direction: column; gap: 2px; padding: 9px 11px; border-radius: 12px; background: color-mix(in srgb, var(--cc) 10%, rgba(127,127,127,0.06)); }
  .fact small { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: var(--secondary-text-color); }
  .fact b { font-size: 16px; font-weight: 600; }
  .d-body p { margin: 0; font-size: 14.5px; line-height: 1.5; white-space: pre-line; }
  .d-src { align-self: stretch; display: flex; align-items: center; gap: 10px; padding: 10px 12px; border: none; border-radius: 12px; cursor: pointer; text-align: left;
    font-size: 14px; font-weight: 600; background: rgba(127,127,127,0.1); }
  .d-src span { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .d-src small { color: var(--secondary-text-color); font-weight: 500; }
  .d-src ha-icon { --mdc-icon-size: 20px; color: var(--secondary-text-color); }
`;

if (!customElements.get("chronik-card")) {
  customElements.define("chronik-card", ChronikCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "chronik-card",
    name: "Chronik",
    description: "Was ist im Garten passiert? Kennzahlen, Wochenstreifen und Zeitleiste aus der Chronik-Integration.",
    preview: true,
  });
  console.info(`%c CHRONIK-CARD %c ${CARD_VERSION} `, "color:#fff;background:#26c6da;font-weight:700", "color:#26c6da;background:#1c1c1c");
}

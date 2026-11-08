"use strict";
/* =========================================================================================
   GrantBridge (Federal Funds Matchmaker) · front end
   - All text from the API is escaped with esc() before it is placed in HTML.
   - Everything a user types is sent to the server, which screens it with the privacy filter
     before it is saved, sent to an AI model or put into a download. The server's verdict is shown.
   ========================================================================================= */

const App = { agency: null, meta: null, matches: null, sort: { key: "rank", asc: true }, reduced: false };
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const safeUrl = (u) => (/^https?:\/\//i.test(String(u || "")) ? esc(u) : "#");
const money = (v) => (v ? (v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : `$${Math.round(v / 1e3)}K`) : "—");
const nice = (iso) => { if (!iso) return "Not listed"; const d = new Date(`${iso}T12:00:00`); return isNaN(d) ? iso : d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }); };
/* Every time of day is shown in North Carolina time (EST/EDT), whatever the viewer's computer is set to. */
const et = (iso, withYear = false) => { if (!iso) return ""; const d = new Date(iso); return isNaN(d) ? String(iso) : d.toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", ...(withYear ? { year: "numeric" } : {}), hour: "numeric", minute: "2-digit", timeZoneName: "short" }); };
const due = (r) => (!r.close_date ? "Not listed" : r.days_left != null && r.days_left >= 0 ? `${nice(r.close_date)} · ${r.days_left}d` : `${nice(r.close_date)} · closed`);

/* ---------------------------------------------------------------- API helper */
class ApiError extends Error { constructor(message, status, data) { super(message); this.status = status; this.data = data; } }
async function api(path, { method = "GET", body, raw = false } = {}) {
  const res = await fetch(path, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
  if (raw && res.ok) return res;
  let data = null;
  try { data = await res.json(); } catch { /* empty */ }
  if (!res.ok) throw new ApiError((data && (data.message || data.detail)) || `Request failed (${res.status})`, res.status, data);
  return data;
}

/* ---------------------------------------------------------------- toasts + privacy notices */
function toast(message, kind = "ok") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`; el.textContent = message;
  $(".toast-stack").appendChild(el);
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 320); }, 4200);
}
function privacyNotice(p) {
  if (!p || !p.changed) return "";
  return `<div class="notice screened"><span class="notice-icon">✓</span><div><b>Screened before use.</b> ${esc(p.summary)}
    <br>Used as: <code>${esc(p.text)}</code></div></div>`;
}
function blockedNotice(message) {
  return `<div class="notice blocked"><span class="notice-icon">!</span><div><b>Not saved or sent.</b> ${esc(message)}</div></div>`;
}

/* ---------------------------------------------------------------- shared UI (in the spirit of the reference site) */
function initTheme() {
  const root = document.documentElement;
  let saved = null; try { saved = localStorage.getItem("ffm-theme"); } catch { /* storage unavailable */ }
  root.setAttribute("data-theme", saved || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"));
  $$(".theme-toggle").forEach((b) => b.addEventListener("click", toggleTheme));
}
function toggleTheme() {
  const root = document.documentElement, next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
  root.setAttribute("data-theme", next); try { localStorage.setItem("ffm-theme", next); } catch { /* ignore */ }
}
function initHeader() {
  const header = $(".site-header"), bar = $(".scroll-progress");
  const update = () => {
    header?.classList.toggle("scrolled", scrollY > 12);
    const h = document.documentElement.scrollHeight - innerHeight;
    if (bar) bar.style.width = `${h > 0 ? (scrollY / h) * 100 : 0}%`;
  };
  update(); addEventListener("scroll", update, { passive: true });
  const btn = $(".mobile-menu-button"), nav = $(".mobile-navigation");
  btn?.addEventListener("click", () => { const open = nav.classList.toggle("open"); btn.classList.toggle("active", open); btn.setAttribute("aria-expanded", String(open)); });
  $$(".back-to-top").forEach((b) => b.addEventListener("click", () => scrollTo({ top: 0, behavior: "smooth" })));
  $$(".current-year").forEach((e) => (e.textContent = String(new Date().getFullYear())));
}
function initCursorGlow() {
  const glow = $(".cursor-glow");
  if (!glow || App.reduced || matchMedia("(pointer: coarse)").matches) return;
  // the glow eases toward the pointer and the animation loop stops once it arrives (no idle CPU use)
  let x = innerWidth / 2, y = innerHeight / 2, cx = x, cy = y, running = false;
  const loop = () => {
    cx += (x - cx) * 0.14; cy += (y - cy) * 0.14;
    glow.style.transform = `translate(${cx - 210}px, ${cy - 210}px)`;
    if (Math.abs(x - cx) + Math.abs(y - cy) > 0.5) requestAnimationFrame(loop); else running = false;
  };
  document.addEventListener("mousemove", (e) => {
    x = e.clientX; y = e.clientY; glow.style.opacity = "1";
    if (!running) { running = true; requestAnimationFrame(loop); }
  }, { passive: true });
  document.addEventListener("mouseleave", () => (glow.style.opacity = "0"));
}
const revealObserver = "IntersectionObserver" in window ? new IntersectionObserver((entries) => entries.forEach((e) => {
  if (e.isIntersecting) { e.target.classList.add("visible"); revealObserver.unobserve(e.target); }
}), { threshold: 0.1, rootMargin: "0px 0px -40px 0px" }) : null;
function reveal(root = document) {
  $$(".reveal:not(.visible)", root).forEach((el, i) => {
    if (!revealObserver || App.reduced) { el.classList.add("visible"); return; }
    el.style.transitionDelay = `${Math.min(i % 4, 3) * 70}ms`; revealObserver.observe(el);
  });
}
function countUp(el, target) {
  target = Number(target) || 0;
  if (App.reduced) { el.textContent = target.toLocaleString(); return; }
  const start = performance.now(), dur = 1400;
  const step = (now) => { const p = Math.min((now - start) / dur, 1), e = 1 - Math.pow(1 - p, 4); el.textContent = Math.round(target * e).toLocaleString(); if (p < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
}
function counters(values, root = document) {
  $$(".counter[data-key]", root).forEach((el) => { if (el.dataset.key in values) countUp(el, values[el.dataset.key]); });
}
function initMagnetic(root = document) {
  if (App.reduced || matchMedia("(pointer: coarse)").matches) return;
  $$(".magnetic", root).forEach((el) => {
    el.addEventListener("mousemove", (e) => { const b = el.getBoundingClientRect(); el.style.transform = `translate(${(e.clientX - b.left - b.width / 2) * 0.08}px, ${(e.clientY - b.top - b.height / 2) * 0.08}px)`; });
    el.addEventListener("mouseleave", () => (el.style.transform = ""));
  });
}
function initCommandMenu() {
  const overlay = $(".command-overlay"); if (!overlay) return;
  const input = $("input", overlay);
  let idx = 0;
  const items = () => $$(".command-item", overlay).filter((i) => i.style.display !== "none");
  const mark = () => items().forEach((it, i) => it.classList.toggle("command-selected", i === idx));
  const open = () => { overlay.classList.add("open"); overlay.setAttribute("aria-hidden", "false"); document.body.classList.add("modal-open"); idx = 0; mark(); setTimeout(() => input?.focus(), 60); };
  const close = () => { overlay.classList.remove("open"); overlay.setAttribute("aria-hidden", "true"); document.body.classList.remove("modal-open"); input.value = ""; $$(".command-item", overlay).forEach((i) => (i.style.display = "")); };
  App.closeCommand = close;
  $(".command-button")?.addEventListener("click", open);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
  input?.addEventListener("input", () => { const q = input.value.toLowerCase().trim(); $$(".command-item", overlay).forEach((i) => (i.style.display = i.textContent.toLowerCase().includes(q) ? "" : "none")); idx = 0; mark(); });
  overlay.addEventListener("click", (e) => {
    const a = e.target.closest(".command-action"); if (!a) return;
    close(); runAction(a.dataset.action, a.dataset.agency);
  });
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); overlay.classList.contains("open") ? close() : open(); return; }
    if (!overlay.classList.contains("open")) return;
    const list = items();
    if (e.key === "Escape") close();
    if (e.key === "ArrowDown") { e.preventDefault(); idx = (idx + 1) % Math.max(list.length, 1); mark(); }
    if (e.key === "ArrowUp") { e.preventDefault(); idx = (idx - 1 + list.length) % Math.max(list.length, 1); mark(); }
    if (e.key === "Enter" && list[idx]) { e.preventDefault(); list[idx].click(); }
  });
}
function runAction(action, value) {
  if (action === "theme") toggleTheme();
  if (action === "survey") openSurvey();
  if (action === "clear-survey") clearSurveyNow();
  if (action === "refresh") doRefresh();
  if (action === "agency" && value) setAgency(value);
}
function initSettings() {
  const panel = $(".settings-panel"), btn = $(".settings-button"), name = $("#user-name");
  const close = () => { panel.classList.remove("open"); panel.setAttribute("aria-hidden", "true"); btn.setAttribute("aria-expanded", "false"); };
  btn?.addEventListener("click", (e) => { e.stopPropagation(); const open = panel.classList.toggle("open"); panel.setAttribute("aria-hidden", String(!open)); btn.setAttribute("aria-expanded", String(open)); });
  document.addEventListener("click", (e) => { if (panel.classList.contains("open") && !panel.contains(e.target)) close(); });
  try { name.value = localStorage.getItem("ffm-user") || ""; } catch { /* ignore */ }
  name?.addEventListener("change", () => { try { localStorage.setItem("ffm-user", name.value.slice(0, 60)); } catch { /* ignore */ } });
  $$(".edit-survey-action").forEach((b) => b.addEventListener("click", () => { close(); openSurvey(); }));
  $$(".refresh-action").forEach((b) => b.addEventListener("click", () => { close(); doRefresh(); }));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
}
async function doRefresh() {
  toast("Pulling the latest notices from Grants.gov… this can take a minute.");
  try { const r = await api("/api/refresh", { method: "POST" }); toast(r.message, r.ok ? "ok" : "err"); if (r.ok) location.reload(); }
  catch (e) { toast(e.message, "err"); }
}

/* ---------------------------------------------------------------- meta, agency, data label */
function getAgency() {
  const fromUrl = new URLSearchParams(location.search).get("agency");
  let saved = null; try { saved = localStorage.getItem("ffm-agency"); } catch { /* ignore */ }
  const ids = App.meta.agencies.map((a) => a.id);
  return [fromUrl, saved, "deq"].find((a) => a && ids.includes(a)) || ids[0];
}
function setAgency(id) {
  try { localStorage.setItem("ffm-agency", id); } catch { /* ignore */ }
  const url = new URL(location.href); url.searchParams.set("agency", id); location.href = url.toString();
}
async function loadMeta() {
  App.meta = await api("/api/meta");
  App.agency = getAgency();
  const sel = $("#agency-select");
  sel.innerHTML = App.meta.agencies.map((a) => `<option value="${esc(a.id)}"${a.id === App.agency ? " selected" : ""}>${esc(a.short)} · ${esc(a.name.replace("NC Department of ", ""))}</option>`).join("");
  sel.addEventListener("change", () => setAgency(sel.value));
  $(".agency-commands").innerHTML = App.meta.agencies.map((a) => `<button class="command-item command-action" data-action="agency" data-agency="${esc(a.id)}" type="button"><span class="command-item-icon">${esc(a.short.slice(0, 2))}</span><span><strong>${esc(a.short)}</strong><small>${esc(a.name)}</small></span><kbd>↵</kbd></button>`).join("");
  const d = App.meta.data;
  $$(".data-label").forEach((e) => (e.textContent = d.label));
  $$(".status-dot").forEach((e) => e.classList.add(d.level));
  $$(".data-pill").forEach((e) => { e.textContent = { live: "Live", cached: "Cached", snapshot: "Snapshot", none: "No data" }[d.level]; e.classList.add(d.level); });
  const when = d.last_success ? et(d.last_success) : "";
  const short = { live: `Live from Grants.gov · updated ${when}`, cached: `Cached data from ${when} · last refresh failed`, snapshot: "Snapshot replay · not live", none: "No data yet · refresh to load" }[d.level];
  $$(".data-short").forEach((e) => (e.textContent = `${short}${d.count ? ` · ${d.count.toLocaleString()} notices` : ""}`));
}

/* ---------------------------------------------------------------- reusable renderers */
const RING_C = 2 * Math.PI * 36;
function ring(score) {
  const off = RING_C * (1 - Math.max(0, Math.min(100, score)) / 100);
  return `<div class="score-ring" aria-label="Fit score ${Math.round(score)} out of 100"><svg viewBox="0 0 86 86"><circle class="track" cx="43" cy="43" r="36"></circle>
    <circle class="value" cx="43" cy="43" r="36" stroke-dasharray="${RING_C.toFixed(1)}" stroke-dashoffset="${RING_C.toFixed(1)}" data-offset="${off.toFixed(1)}"></circle></svg>
    <div class="label"><div><strong>${Math.round(score)}</strong><small>fit score</small></div></div></div>`;
}
function animateRings(root = document) {
  $$(".score-ring .value", root).forEach((c, i) => setTimeout(() => (c.style.strokeDashoffset = c.dataset.offset), App.reduced ? 0 : 200 + i * 90));
}
const tags = (list) => (list || []).map((t) => `<span class="tag ${esc(t.tone)}">${esc(t.text)}</span>`).join("");
function card(m, rank, opts = {}) {
  const q = m.quote && !opts.noQuote ? `<p class="match-quote">“${esc(m.quote.length > 230 ? `${m.quote.slice(0, 230).replace(/\s\S*$/, "")}…` : m.quote)}”</p>` : "";
  return `<article class="match-card reveal" data-id="${esc(m.id)}" tabindex="0" aria-label="${esc(m.title)}: open details">
    <div class="match-rank">${rank ? String(rank).padStart(2, "0") : "—"}</div>
    <div class="match-body">
      <div class="match-kicker">${esc(m.agency)} · ${esc(m.number)}${opts.match ? ` · project match ${Number(m.match).toFixed(2)}` : ""}</div>
      <h3 class="match-title">${esc(m.title)}</h3>
      <div class="match-facts"><div><small>Award</small>${esc(m.funding)}</div><div><small>Due</small>${esc(due(m))}</div><div><small>Effort</small>${esc(m.effort)}</div></div>
      <div class="match-supports"><b>${esc(m.supports.id || "Supports")}</b>${esc(m.supports.text)}</div>
      ${q}<div class="match-tags">${tags(m.tags)}</div>
      <div class="match-actions"><span class="text-link">Evidence, eligibility, effort and brief <span>↗</span></span></div>
    </div>${ring(m.score)}</article>`;
}
function bindCards(root) {
  $$(".match-card", root).forEach((c) => {
    c.addEventListener("click", () => openDrawer(c.dataset.id));
    c.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDrawer(c.dataset.id); } });
    c.addEventListener("mousemove", (e) => { const b = c.getBoundingClientRect(); c.style.setProperty("--mx", `${e.clientX - b.left}px`); c.style.setProperty("--my", `${e.clientY - b.top}px`); });
  });
  reveal(root); animateRings(root);
}

/* ---------------------------------------------------------------- MATCHES page */
async function pageMatches() {
  const list = $(".match-list");
  let data;
  try { data = await api(`/api/matches/${App.agency}`); }
  catch (e) { list.innerHTML = `<div class="empty-state"><strong>Couldn't load matches.</strong>${esc(e.message)}</div>`; return; }
  App.matches = data;
  renderAlerts();
  const a = data.agency;
  $$(".agency-name-heading").forEach((e) => (e.textContent = a.name.replace("NC Department of ", "")));
  $$(".agency-address").forEach((e) => (e.textContent = `matchmaker / ${a.id}`));
  $$(".agency-plan-link").forEach((e) => (e.innerHTML = `the <a href="${safeUrl(a.plan_url)}" target="_blank" rel="noopener">${esc(a.plan)}</a>`));
  counters(data.stats);
  $$(".plural[data-for]").forEach((e) => (e.textContent = data.stats[e.dataset.for] === 1 ? "notice" : "notices"));
  $(".eligible-note").textContent = data.stats.shortlist ? `${Math.round((100 * data.stats.eligible) / data.stats.shortlist)}% eligible` : "—";
  setTimeout(() => ($(".eligible-bar").style.width = `${data.stats.shortlist ? (100 * data.stats.eligible) / data.stats.shortlist : 0}%`), 300);
  const bars = (data.charts.runway || []).slice(0, 14).map((r) => Math.max(8, r.score));
  $(".mini-bars-live").innerHTML = (bars.length ? bars : [20, 30, 25, 40]).map((h, i) => `<span style="height:${h}%;animation-delay:${i * 60}ms"></span>`).join("");
  const top = data.top[0];
  $(".hero-top-title").textContent = top ? top.title : "Nothing passed your filters yet";
  $(".hero-top-score").textContent = top ? `${Math.round(top.score)}/100` : "—";
  $(".hero-best-score").textContent = top ? `${Math.round(top.score)} / 100` : "—";
  $(".hero-top-meta").innerHTML = top ? tags(top.tags.slice(0, 3)) : "";
  $(".top-note").insertAdjacentHTML("beforeend", ` Showing your top ${data.top.length} of ${data.stats.shortlist.toLocaleString()} (based on capacity: ${esc(data.survey.capacity)} this month).`);

  list.innerHTML = data.top.length ? data.top.map((m, i) => card(m, i + 1)).join("")
    : `<div class="empty-state"><strong>${data.stats.reviewed ? "Nothing passed your filters." : "No opportunities loaded yet."}</strong>${data.stats.reviewed ? "See “Set aside” below, or loosen your answers." : "Use Settings → Refresh from Grants.gov, or wait for the 6 AM refresh."}</div>`;
  bindCards(list);

  $(".due-list").innerHTML = data.due_soon.length ? data.due_soon.map((d) => `<div class="due-item" data-id="${esc(d.id)}" role="button" tabindex="0">
      <div class="due-days ${d.days <= 14 ? "hot" : ""}">${esc(d.days)}<small>DAYS</small></div><div><div class="due-title">${esc(d.title)}</div><div class="due-next">${esc(d.next)}</div></div></div>`).join("")
    : `<p class="due-next">Nothing on your shortlist closes in the next 30 days.</p>`;
  $$(".due-item").forEach((el) => { el.addEventListener("click", () => openDrawer(el.dataset.id)); el.addEventListener("keydown", (e) => { if (e.key === "Enter") openDrawer(el.dataset.id); }); });
  $(".set-aside-counts").innerHTML = data.set_aside_counts.length ? data.set_aside_counts.map(([k, v]) => `<div class="kv-row"><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join("") : `<div class="kv-row"><span>Nothing set aside</span><b>0</b></div>`;
  const s = data.survey;
  $(".survey-summary").innerHTML = [["Applications this month", s.capacity], ["Minimum award", s.min_award], ["Can provide match", s.cost_share], ["Prep time needed", s.prep_time], ["Matching method", data.method], ["AI explanations", data.ai ? "On, verified" : "Off (rules)"]]
    .map(([k, v]) => `<div class="kv-row"><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join("");

  chartGoals(data.charts.by_goal); chartRunway(data.charts.runway);
  initTable(data.shortlist);
  const asideRow = (r) => `<tr><td class="num">${esc(r.score)}</td><td class="title-cell"><a href="${safeUrl(r.url)}" target="_blank" rel="noopener">${esc(r.title)}</a></td><td>${esc(r.why_set_aside)}</td><td class="num">${esc(r.close_date || "—")}</td></tr>`;
  const drawAside = (n) => {
    $(".setaside-table tbody").innerHTML = (data.set_aside.slice(0, n).map(asideRow).join("") || `<tr><td colspan="4">Nothing set aside.</td></tr>`)
      + (data.set_aside.length > n ? `<tr><td colspan="4" class="more-cell"><button type="button" class="secondary-button small more-aside">Show more (${(data.set_aside.length - n).toLocaleString()} left)</button></td></tr>` : "");
    $(".more-aside")?.addEventListener("click", () => drawAside(n + TABLE_PAGE));
  };
  drawAside(TABLE_PAGE);
  initSearch();
  reveal();
  if (!data.has_survey) setTimeout(openSurvey, 600);
  bindClearSurvey($(".aside-card .clear-survey-action"));
  offerSurveyUndo();
  const hash = new URLSearchParams(location.search).get("open");
  if (hash && /^\d+$/.test(hash)) openDrawer(hash);
}

/* charts: hand-built SVG, one hue, hover tooltips, table fallback */
function svgDefs() {
  if ($("#ffm-defs")) return;
  document.body.insertAdjacentHTML("beforeend", `<svg id="ffm-defs" width="0" height="0" style="position:absolute" aria-hidden="true"><defs>
    <linearGradient id="scoreGradient" x1="0" x2="1" y1="0" y2="1"><stop offset="0%" stop-color="#ab92ff"/><stop offset="55%" stop-color="#7a65ff"/><stop offset="100%" stop-color="#4fd8ff"/></linearGradient>
    <linearGradient id="barGradient" x1="0" x2="1"><stop offset="0%" stop-color="#7a65ff"/><stop offset="100%" stop-color="#4fd8ff"/></linearGradient></defs></svg>`);
}
function tooltip(box) {
  let tip = $(".chart-tooltip", box);
  if (!tip) { tip = document.createElement("div"); tip.className = "chart-tooltip"; box.appendChild(tip); }
  return {
    show(html, ev) { tip.innerHTML = html; const b = box.getBoundingClientRect(); tip.style.left = `${Math.min(ev.clientX - b.left + 14, b.width - 270)}px`; tip.style.top = `${ev.clientY - b.top + 14}px`; tip.classList.add("show"); },
    hide() { tip.classList.remove("show"); },
  };
}
function chartGoals(rows) {
  const box = $(".chart-goals"); if (!box) return;
  if (!rows.length) { box.innerHTML = `<p class="field-hint">No shortlisted notices to chart yet.</p>`; return; }
  const W = 560, rowH = 34, left = 210, H = rows.length * rowH + 10, max = Math.max(...rows.map((r) => r[1]));
  const bars = rows.map(([k, v], i) => {
    const w = Math.max(4, ((W - left - 40) * v) / max), y = i * rowH + 6;
    return `<text class="cat-label" x="${left - 10}" y="${y + 15}" text-anchor="end">${esc(k.length > 34 ? `${k.slice(0, 33)}…` : k)}</text>
      <rect class="bar" data-k="${esc(k)}" data-v="${v}" x="${left}" y="${y}" width="${w}" height="20" rx="4" style="transform-origin:${left}px 0;animation:growX 1s ${0.1 + i * 0.07}s cubic-bezier(.16,1,.3,1) both"></rect>
      <text class="bar-label" x="${left + w + 8}" y="${y + 15}">${v}</text>`;
  }).join("");
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="presentation">${bars}</svg>`;
  const tip = tooltip(box);
  $$(".bar", box).forEach((b) => { b.addEventListener("mousemove", (e) => tip.show(`<b>${esc(b.dataset.k)}</b>${esc(b.dataset.v)} shortlisted notices`, e)); b.addEventListener("mouseleave", tip.hide); });
  $(".chart-goals-table").innerHTML = `<table class="data-table"><tr><th>Plan goal</th><th>Shortlisted</th></tr>${rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("")}</table>`;
}
function chartRunway(points) {
  const box = $(".chart-runway"); if (!box) return;
  if (!points.length) { box.innerHTML = `<p class="field-hint">No shortlisted notices with a deadline yet.</p>`; return; }
  const W = 560, H = 260, l = 40, r = 16, t = 14, b = 34, maxD = 180;
  const x = (d) => l + ((W - l - r) * Math.min(d, maxD)) / maxD, y = (s) => t + ((H - t - b) * (100 - s)) / 100;
  const grid = [0, 25, 50, 75, 100].map((s) => `<line class="grid" x1="${l}" x2="${W - r}" y1="${y(s)}" y2="${y(s)}"></line><text x="${l - 8}" y="${y(s) + 4}" text-anchor="end">${s}</text>`).join("")
    + [0, 30, 60, 90, 120, 150, 180].map((d) => `<text x="${x(d)}" y="${H - 12}" text-anchor="middle">${d}${d === 180 ? "+" : ""}</text>`).join("");
  const zone = `<rect class="zone" x="${x(0)}" y="${t}" width="${x(14) - x(0)}" height="${H - t - b}"></rect><line class="zone-line" x1="${x(14)}" x2="${x(14)}" y1="${t}" y2="${H - b}"></line><text class="zone-text" x="${x(14) + 6}" y="${t + 12}">due within 14 days</text>`;
  const dots = points.map((p, i) => `<circle class="dot" data-id="${esc(p.id)}" data-t="${esc(p.title)}" data-d="${p.days}" data-s="${p.score}" cx="${x(p.days)}" cy="${y(p.score)}" r="0" style="transition:r .5s ${0.2 + i * 0.02}s cubic-bezier(.16,1,.3,1)"></circle>`).join("");
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="presentation">${grid}${zone}${dots}<text x="${(W + l) / 2}" y="${H}" text-anchor="middle">days left to apply</text></svg>`;
  requestAnimationFrame(() => $$(".dot", box).forEach((d) => d.setAttribute("r", "6")));
  const tip = tooltip(box);
  $$(".dot", box).forEach((d) => {
    d.addEventListener("mousemove", (e) => tip.show(`<b>${esc(d.dataset.t)}</b>Fit ${esc(d.dataset.s)}/100 · ${esc(d.dataset.d)} days left<br><small>Click to open</small>`, e));
    d.addEventListener("mouseleave", tip.hide); d.addEventListener("click", () => openDrawer(d.dataset.id));
  });
  $(".chart-runway-table").innerHTML = `<table class="data-table"><tr><th>Notice</th><th>Days left</th><th>Fit</th></tr>${points.map((p) => `<tr><td>${esc(p.title)}</td><td>${esc(p.days)}</td><td>${esc(p.score)}</td></tr>`).join("")}</table>`;
}

/* shortlist table: filter, sort, export */
const TABLE_PAGE = 200;
function initTable(rows) {
  // called again after every decision with fresh rows: handlers are bound only once (no double CSV downloads)
  App.tableData = rows; App.tableLimit = TABLE_PAGE;
  if (!App.tableBound) bindTable();
  drawTable();
}
function tableFilters() {
  return { score: $(".f-score"), out: $(".f-score-out"), due: $(".f-due"), fund: $(".f-fund"), dec: $(".f-decision"), text: $(".f-text") };
}
function drawTable() {
  const tbody = $(".shortlist-table tbody"), count = $(".shortlist-section .table-count"), f = tableFilters(), rows = App.tableData || [];
  const q = f.text.value.toLowerCase();
  const list = rows.filter((r) => {
    if (r.score < Number(f.score.value)) return false;
    if (f.due.value && (r.days_left == null || r.days_left > Number(f.due.value))) return false;
    if (Number(f.fund.value) && (!r.award_ceiling || r.award_ceiling < Number(f.fund.value))) return false;
    if (f.dec.value ? r.decision !== f.dec.value : r.decision === "Pass") return false;
    if (q && !r.title.toLowerCase().includes(q)) return false;
    return true;
  }).sort((a, b) => { const k = App.sort.key, av = a[k] ?? 1e12, bv = b[k] ?? 1e12; return (av > bv ? 1 : av < bv ? -1 : 0) * (App.sort.asc ? 1 : -1); });
  f.out.textContent = f.score.value;
  const shown = list.slice(0, App.tableLimit);
  tbody.innerHTML = (shown.map((r) => `<tr class="clickable" tabindex="0" data-id="${esc(r.id)}" aria-label="Open ${esc(r.title)}"><td class="num">${esc(r.rank)}</td>
    <td><span class="mini-score">${esc(r.score)}<i><b style="width:${Math.max(0, Math.min(100, r.score))}%"></b></i></span></td>
    <td class="title-cell">${esc(r.title)}</td><td>${esc(r.agency)}</td><td>${esc(r.eligibility)}</td>
    <td class="num">${esc(r.close_date ? due(r) : "Not listed")}</td><td class="num">${esc(money(r.award_ceiling))}</td><td>${esc(r.decision)}</td></tr>`).join("")
    || `<tr><td colspan="8">No notices match these filters.</td></tr>`)
    + (list.length > shown.length ? `<tr><td colspan="8" class="more-cell"><button type="button" class="secondary-button small show-more-rows">Show ${Math.min(TABLE_PAGE, list.length - shown.length)} more (${(list.length - shown.length).toLocaleString()} left)</button></td></tr>` : "");
  count.textContent = `${list.length.toLocaleString()} of ${rows.length.toLocaleString()} shortlisted notices${list.length > shown.length ? ` · showing ${shown.length.toLocaleString()}` : ""}`;
  App.tableRows = list;  // CSV export always includes every matching row, not only the ones drawn
}
function bindTable() {
  App.tableBound = true;
  const f = tableFilters(), tbody = $(".shortlist-table tbody");
  Object.values(f).forEach((el) => el?.addEventListener("input", () => { App.tableLimit = TABLE_PAGE; drawTable(); }));
  // one delegated listener for every row, by mouse or keyboard
  tbody.addEventListener("click", (e) => {
    if (e.target.closest(".show-more-rows")) { App.tableLimit += TABLE_PAGE; drawTable(); return; }
    const tr = e.target.closest("tr.clickable"); if (tr) openDrawer(tr.dataset.id);
  });
  tbody.addEventListener("keydown", (e) => {
    const tr = e.target.closest("tr.clickable");
    if (tr && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openDrawer(tr.dataset.id); }
  });
  $$(".shortlist-table th[data-sort]").forEach((th) => {
    const label = th.textContent;
    th.innerHTML = `<button type="button" class="sort-button">${esc(label)}</button>`;
    th.setAttribute("aria-sort", th.dataset.sort === App.sort.key ? (App.sort.asc ? "ascending" : "descending") : "none");
    th.querySelector("button").addEventListener("click", () => {
      const k = th.dataset.sort; App.sort = { key: k, asc: App.sort.key === k ? !App.sort.asc : k === "rank" || k === "title" || k === "days_left" };
      $$(".shortlist-table th[data-sort]").forEach((h) => { h.classList.remove("sorted", "asc"); h.setAttribute("aria-sort", "none"); });
      th.classList.add("sorted"); if (App.sort.asc) th.classList.add("asc");
      th.setAttribute("aria-sort", App.sort.asc ? "ascending" : "descending"); drawTable();
    });
  });
  $(".export-csv")?.addEventListener("click", () => {
    const cols = ["rank", "score", "title", "agency", "eligibility", "close_date", "days_left", "award_ceiling", "decision", "url"];
    const csv = [cols.join(",")].concat((App.tableRows || []).map((r) => cols.map((c) => `"${String(r[c] ?? "").replace(/"/g, '""')}"`).join(","))).join("\n");
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" })); a.download = `${App.agency}_shortlist.csv`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  });
}

/* keep keyboard focus inside an open drawer or dialog (Tab / Shift+Tab cycle within it) */
function trapFocus() {
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;
    const box = $(".drawer.open .drawer-panel") || $(".survey-modal.open .survey-panel") || $(".command-overlay.open .command-panel");
    if (!box) return;
    const items = $$('a[href], button:not([disabled]), input:not([disabled]):not([type=hidden]), select, textarea, [tabindex]:not([tabindex="-1"])', box)
      .filter((el) => el.offsetParent !== null || el === document.activeElement);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (!box.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
    else if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
}

/* project search — the query is screened on the server before searching */
function initSearch() {
  const form = $(".project-search"); if (!form) return;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = $("#project-q").value.trim(), out = $(".search-results"), note = $(".search-privacy");
    if (!q) return;
    out.innerHTML = `<div class="skeleton-card"></div>`; note.innerHTML = "";
    try {
      const r = await api(`/api/search/${App.agency}`, { method: "POST", body: { q } });
      note.innerHTML = privacyNotice(r.privacy);
      out.innerHTML = r.results.length ? r.results.map((m) => card(m, m.rank, { match: true })).join("") : `<div class="empty-state"><strong>No close matches.</strong>Try different words.</div>`;
      bindCards(out);
    } catch (err) {
      out.innerHTML = ""; note.innerHTML = err.status === 422 ? blockedNotice(err.message) : `<div class="notice blocked"><span class="notice-icon">!</span><div>${esc(err.message)}</div></div>`;
    }
  });
}

/* ---------------------------------------------------------------- detail drawer */
function closeDrawer() {
  const d = $(".drawer"); d.classList.remove("open"); d.setAttribute("aria-hidden", "true"); document.body.classList.remove("modal-open");
  const url = new URL(location.href); url.searchParams.delete("open"); history.replaceState(null, "", url);
  App.lastFocus?.focus?.();
}
function initDrawer() {
  $(".drawer-close")?.addEventListener("click", closeDrawer);
  $(".drawer-backdrop")?.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && $(".drawer")?.classList.contains("open")) closeDrawer(); });
}
async function openDrawer(id, agency = App.agency, preloaded = null) {
  App.lastFocus = document.activeElement;
  const drawer = $(".drawer"), content = $(".drawer-content");
  drawer.classList.add("open"); drawer.setAttribute("aria-hidden", "false"); document.body.classList.add("modal-open");
  content.innerHTML = `<div class="skeleton-card"></div><div class="skeleton-card" style="margin-top:14px;height:320px"></div>`;
  if (!preloaded) { const url = new URL(location.href); url.searchParams.set("open", id); history.replaceState(null, "", url); }
  try {
    const d = preloaded || await api(`/api/opportunity/${agency}/${id}`);
    content.innerHTML = detailHtml(d);
    wireDetail(d, agency, content);
    $(".drawer-close").focus();
  } catch (e) { content.innerHTML = `<div class="empty-state"><strong>Couldn't load this notice.</strong>${esc(e.message)}</div>`; }
}
function detailHtml(d) {
  const ex = d.explanation, el = d.eligibility_detail, est = d.estimate, f = d.feasibility_detail;
  const confTone = { high: "ok", medium: "info", low: "warn" }[ex.confidence] || "";
  const cites = (list) => (list || []).map((c) => `<div class="cite">“${esc(c.quote)}”<small>${esc(c.source)}</small></div>`).join("");
  const cond = el.conditions;
  const condBlocks = [["Matching funds", cond.matching], ["No match required", cond.no_match], ["Partners and letters", cond.partnership], ["Other conditions", cond.other]]
    .filter(([, l]) => l && l.length).map(([t, l]) => `<span class="kicker">${esc(t)}</span>${cites(l)}`).join("");
  const feasTone = { feasible: "ok", tight: "warn", not_enough: "hot" }[f.status] || "";
  return `<div class="drawer-head">
      <div class="match-kicker">${esc(d.agency)} · ${esc(d.number)} · ${esc(d.data_label)}</div>
      <div class="drawer-summary">${ring(d.score)}<div><h2>${esc(d.title)}</h2><div class="match-tags">${tags(d.tags)}</div></div></div>
      <div class="fact-grid">${Object.entries(d.facts).map(([k, v]) => `<div><b>${esc(k)}</b>${esc(v)}</div>`).join("")}</div>
      <div class="callout info" style="margin-top:16px"><b>Recommended next action</b>${esc(d.next_action)}</div>
    </div>
    <div class="tabs" role="tablist">${["Why it fits", "Eligibility", "Effort & timing", "Brief", "Decision"].map((t, i) => `<button class="tab" role="tab" id="tab-${i}" aria-controls="panel-${i}" aria-selected="${i === 0}" data-i="${i}">${t}</button>`).join("")}</div>

    <section class="tab-panel" id="panel-0" role="tabpanel" aria-labelledby="tab-0"><div class="panel-cols">
      <div><span class="kicker">Score breakdown · a priority score, not a probability of winning</span>
        <div class="bars">${d.components.map((c) => `<div class="bar-row"><div class="bar-head">${esc(c.name)}<span>${esc(c.points)} / ${esc(c.max)}</span></div><div class="bar-track"><span class="bar-fill" data-w="${(100 * c.points) / c.max}"></span></div><p>${esc(c.why)}</p></div>`).join("")}</div>
        ${d.feedback ? `<div class="callout ${d.feedback.points > 0 ? "info" : "warn"} feedback-note"><b>Learned from your team: ${d.feedback.points > 0 ? "+" : ""}${esc(d.feedback.points)} points</b><small>${esc(d.feedback.why)}. Plan-based score ${esc(d.base_score)} → ${esc(d.score)}. Feedback can move a score by at most 8 points.</small></div>` : ""}</div>
      <div><span class="kicker">Strategic objective</span><div class="callout info"><b>${esc(ex.matched_label)}</b><small>${esc(ex.objective_citation)}${ex.objective_url ? ` · <a href="${safeUrl(ex.objective_url)}" target="_blank" rel="noopener">open plan</a>` : ""}</small></div>
        ${d.program ? `<span class="kicker">Related agency program</span><div class="callout ok"><b>${esc(d.program.label)}</b>${d.program.url ? `<small><a href="${safeUrl(d.program.url)}" target="_blank" rel="noopener">source</a></small>` : ""}</div>` : ""}
        <span class="kicker">Confidence</span><div class="callout ${confTone}"><b>${esc((ex.confidence || "").replace(/^./, (c) => c.toUpperCase()))}${d.needs_review ? " · needs a second look" : ""}</b><small>${esc(ex.source)}</small></div></div>
    </div>
      <span class="kicker">Evidence</span>
      <div class="cite">“${esc(d.plan_text)}”<small>Strategic plan objective (close summary of the plan wording; verify in the cited section)</small></div>
      <div class="cite">“${esc(ex.grant_evidence_quote)}”<small>Federal notice, quoted word for word</small></div>
      <span class="kicker">Reasons</span><ul class="list">${(ex.reasons || []).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
      ${(ex.notes || []).map((n) => `<div class="notice info"><span class="notice-icon">i</span><div><b>Check:</b> ${esc(n)}</div></div>`).join("")}
      ${d.other_objectives.length ? `<p class="field-hint">Other related objectives: ${d.other_objectives.map((o) => `${esc(o.id)} (${esc(o.fit)})`).join(", ")}</p>` : ""}
    </section>

    <section class="tab-panel" id="panel-1" role="tabpanel" aria-labelledby="tab-1" hidden>
      <div class="callout ${{ "Appears Eligible": "ok", "Needs Human Verification": "warn", "Partnership Opportunity": "info", "Not Eligible for Direct Application": "hot" }[el.label] || ""}"><b>${esc(el.label)}</b>${el.reasons.map((r) => esc(r)).join("<br>")}<br><small>${esc(el.method)}</small></div>
      ${el.citations.length ? `<span class="kicker">From the notice</span>${cites(el.citations)}` : ""}
      ${condBlocks}
      ${el.open_questions.length ? `<span class="kicker">Questions for a person to resolve</span><ul class="list">${el.open_questions.map((q) => `<li>${esc(q)}</li>`).join("")}</ul>` : ""}
      ${d.flags.length ? `<span class="kicker">Flags</span><div class="match-tags">${d.flags.map((x) => `<span class="tag warn">${esc(x)}</span>`).join("")}</div>` : ""}
    </section>

    <section class="tab-panel" id="panel-2" role="tabpanel" aria-labelledby="tab-2" hidden>
      <div class="callout ${feasTone}"><b>${esc(est.level)} effort · ${esc(f.text || "")}</b>${esc(est.summary)}<br><small>${esc(est.label)} · based on ${esc(est.basis)}</small></div>
      ${est.drivers.length ? `<span class="kicker">What drives the effort</span>${est.drivers.map((x) => `<div class="cite">“${esc(x.quote)}”<small>${esc(x.detail)} (+${esc(x.points)}) · ${esc(x.source)}</small></div>`).join("")}` : ""}
      ${d.nofo && d.nofo.source ? `<p class="field-hint">Full notice PDF read: ${esc(d.nofo.source)}</p>` : d.nofo && d.nofo.error && d.nofo.error !== "not attempted" ? `<p class="field-hint">Full notice PDF not read: ${esc(d.nofo.error)}</p>` : ""}
      ${est.rejected ? `<p class="field-hint">${esc(est.rejected)} AI-suggested driver(s) were dropped because their quote was not in the notice.</p>` : ""}
      <span class="kicker">What to gather</span><ul class="list">${d.gather.map((g) => `<li>${esc(g)}</li>`).join("")}</ul>
    </section>

    <section class="tab-panel" id="panel-3" role="tabpanel" aria-labelledby="tab-3" hidden>
      <div class="form-field"><label for="brief-notes">Notes to include in the brief <small>(optional)</small></label>
        <textarea id="brief-notes" maxlength="1000" placeholder="Context for your team (public information only)"></textarea>
        <p class="field-hint"><span class="shield">✓</span> Screened on the server before it is added to any copy or download.</p></div>
      <div class="button-row"><button class="primary-button small brief-pdf" type="button">Download PDF ↓</button>
        <button class="secondary-button small brief-text" type="button">Preview &amp; copy text</button>
        <a class="secondary-button small" href="${safeUrl(d.url)}" target="_blank" rel="noopener">Official listing ↗</a></div>
      <div class="brief-privacy"></div><pre class="brief-box">${esc(d.brief_text)}</pre>
    </section>

    <section class="tab-panel" id="panel-4" role="tabpanel" aria-labelledby="tab-4" hidden>
      ${d.review ? `<div class="callout info"><b>Last decision: ${esc(d.review.action)}</b>${esc(d.review.relevance || "no relevance mark")} · ${esc(d.review.user || "unknown")} · ${esc(et(d.review.at, true))}<br><small>Reason: ${esc(d.review.reason || "—")} · Note: ${esc(d.review.note || "—")}</small></div>` : ""}
      <form class="decision-form" autocomplete="off">
        <div class="form-field"><label>Decision</label><div class="pill-group">${["Pursue", "Maybe", "Pass"].map((a, i) => `<input type="radio" name="action" id="act-${a}" value="${a}"${i === 1 ? " checked" : ""}><label for="act-${a}">${a}</label>`).join("")}</div></div>
        <div class="form-field"><label>Relevance</label><div class="pill-group">${[["relevant", "Relevant"], ["irrelevant", "Not relevant"], ["needs investigation", "Needs investigation"], ["", "Skip"]].map(([v, l], i) => `<input type="radio" name="relevance" id="rel-${i}" value="${v}"${i === 3 ? " checked" : ""}><label for="rel-${i}">${l}</label>`).join("")}</div></div>
        <div class="form-field"><label for="d-reason">Reason <small>(required to pass)</small></label><input id="d-reason" type="text" maxlength="300"></div>
        <div class="form-field"><label for="d-note">Note <small>(optional)</small></label><input id="d-note" type="text" maxlength="500"></div>
        <p class="field-hint"><span class="shield">✓</span> Reason, note and your initials are screened on the server for personal or internal information before saving.</p>
        <div class="button-row"><button class="primary-button small" type="submit">Save decision →</button></div>
        <div class="decision-privacy"></div>
      </form>
    </section>`;
}
function wireDetail(d, agency, root) {
  $$(".tab", root).forEach((t) => t.addEventListener("click", () => {
    $$(".tab", root).forEach((x) => x.setAttribute("aria-selected", String(x === t)));
    $$(".tab-panel", root).forEach((p, i) => (p.hidden = String(i) !== t.dataset.i));
    if (t.dataset.i === "0") setTimeout(() => $$(".bar-fill", root).forEach((b) => (b.style.width = `${b.dataset.w}%`)), 40);
  }));
  setTimeout(() => $$(".bar-fill", root).forEach((b) => (b.style.width = `${b.dataset.w}%`)), 120);
  animateRings(root);
  const notes = $("#brief-notes", root), bp = $(".brief-privacy", root);
  $(".brief-text", root)?.addEventListener("click", async () => {
    try {
      const r = await api(`/api/brief/${agency}/${d.id}`, { method: "POST", body: { notes: notes.value, format: "text" } });
      bp.innerHTML = privacyNotice(r.privacy); $(".brief-box", root).textContent = r.text;
      try { await navigator.clipboard.writeText(r.text); toast("Brief copied to your clipboard."); } catch { toast("Brief ready below. Select and copy it."); }
    } catch (e) { bp.innerHTML = e.status === 422 ? blockedNotice(e.message) : blockedNotice(e.message); }
  });
  $(".brief-pdf", root)?.addEventListener("click", async (ev) => {
    const btn = ev.currentTarget; btn.disabled = true;
    try {
      const res = await api(`/api/brief/${agency}/${d.id}`, { method: "POST", body: { notes: notes.value, format: "pdf" }, raw: true });
      const summary = res.headers.get("X-Privacy-Summary");
      bp.innerHTML = summary ? privacyNotice({ changed: true, summary, text: "(applied to the notes in your PDF)" }) : "";
      const a = document.createElement("a"); a.href = URL.createObjectURL(await res.blob()); a.download = `brief_${d.number || d.id}.pdf`; a.click(); URL.revokeObjectURL(a.href);
      toast("Brief downloaded.");
    } catch (e) { bp.innerHTML = blockedNotice(e.message); } finally { btn.disabled = false; }
  });
  $(".decision-form", root)?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.currentTarget, out = $(".decision-privacy", root);
    const body = { action: form.action.value, relevance: form.relevance.value, reason: $("#d-reason", root).value, note: $("#d-note", root).value, user: $("#user-name")?.value || "" };
    if (body.action === "Pass" && !body.reason.trim()) { out.innerHTML = blockedNotice("A reason is required to pass."); return; }
    try {
      const r = await api(`/api/decision/${agency}/${d.id}`, { method: "POST", body });
      out.innerHTML = Object.values(r.privacy || {}).map(privacyNotice).join("") + `<div class="notice screened"><span class="notice-icon">✓</span><div><b>Saved: ${esc(r.entry.action)}.</b> Recorded with the score at the time (${esc(r.entry.score_at_review)}).</div></div>`;
      toast(`Decision saved: ${r.entry.action}`);
      if (document.body.dataset.page === "matches") setTimeout(() => pageMatchesRefresh(), 600);
    } catch (err) { out.innerHTML = blockedNotice(err.message); }
  });
}
/* Deadline alerts (stretch goal 2): banner for tracked grants closing soon + calendar file + Teams status. */
async function renderAlerts() {
  const box = $(".alert-banner"); if (!box) return;
  $$(".calendar-link").forEach((a) => { a.href = `/api/alerts/${App.agency}/calendar.ics`; });
  let r; try { r = await api(`/api/alerts/${App.agency}`); } catch { return; }
  if (!r.soon.length) { box.hidden = true; return; }
  const teams = r.webhook_configured ? `Teams / Slack reminders are on (${r.alert_days.join(", ")} days before).`
    : "Teams / Slack reminders are off; your administrator can turn them on.";
  box.innerHTML = `<div class="alert-head"><span class="alert-icon" aria-hidden="true">⏰</span><div><h3>${r.soon.length} ${r.soon.length === 1 ? "opportunity closes" : "opportunities close"} within ${r.window} days</h3>
      <p>Grants your team marked Pursue or Maybe, and your current top picks. ${teams}</p></div>
      <a class="secondary-button small" href="/api/alerts/${esc(App.agency)}/calendar.ics" download>Add all to my calendar ↓</a></div>
    <ul class="alert-list">${r.soon.map((a) => `<li><button type="button" class="alert-item" data-id="${esc(a.id)}"><b class="${a.days <= 7 ? "hot" : "warn"}">${a.days === 0 ? "Today" : a.days === 1 ? "Tomorrow" : `${a.days} days`}</b>
      <span>${esc(a.title)}</span><small>${esc(a.text)} · ${esc(a.because)}</small></button></li>`).join("")}</ul>`;
  box.hidden = false;
  $$(".alert-item", box).forEach((b) => b.addEventListener("click", () => openDrawer(b.dataset.id)));
}
async function pageMatchesRefresh() {
  renderAlerts();
  try { const data = await api(`/api/matches/${App.agency}`); App.matches = data; const list = $(".match-list"); list.innerHTML = data.top.map((m, i) => card(m, i + 1)).join(""); bindCards(list); initTable(data.shortlist); } catch { /* keep current view */ }
}

/* ---------------------------------------------------------------- survey dialog */
async function openSurvey() {
  const modal = $(".survey-modal"), box = $(".survey-content");
  modal.classList.add("open"); modal.setAttribute("aria-hidden", "false"); document.body.classList.add("modal-open");
  box.innerHTML = `<div class="skeleton-card"></div>`;
  let s;
  try { s = await api(`/api/survey/${App.agency}`); } catch (e) { box.innerHTML = blockedNotice(e.message); return; }
  const a = s.answers, ag = App.meta.agencies.find((x) => x.id === App.agency);
  const pills = (name, opts, cur) => `<div class="pill-group">${opts.map((o, i) => `<input type="radio" name="${name}" id="${name}-${i}" value="${esc(o)}"${o === cur ? " checked" : ""}><label for="${name}-${i}">${esc(o)}</label>`).join("")}</div>`;
  box.innerHTML = `<span class="page-label"><span class="status-dot"></span>Quick setup · about 60 seconds</span>
    <h2 id="survey-title">Sixty seconds to <span class="gradient-text">better matches.</span></h2>
    <p class="hero-description">Six quick questions tell the matcher what matters to ${esc(ag.short)} right now. Change them any time.</p>
    <div class="survey-progress"><span></span></div>
    <form class="survey-form" autocomplete="off">
      <div class="q-block"><div class="q-head"><span class="q-num">01</span><span class="q-title">Agency: ${esc(ag.name)}</span><span class="q-sub">change it in the header</span></div></div>
      <div class="q-block" data-q="2"><div class="q-head"><span class="q-num">02</span><span class="q-title">What is your team focused on right now?</span><span class="q-sub">from <a href="${safeUrl(s.plan.url)}" target="_blank" rel="noopener">your plan</a>; picks get a boost</span></div>
        ${s.goals.map((g) => `<details class="goal-acc"><summary>Goal ${esc(g.id)}: ${esc(g.title)}<span class="count" data-goal="${esc(g.id)}"></span></summary>
          ${g.objectives.map((o) => `<label class="check"><input type="checkbox" name="obj" value="${esc(o.id)}" data-goal="${esc(g.id)}"${a.focus_objectives.includes(o.id) ? " checked" : ""}><span><b>${esc(o.id)}</b>${esc(o.text)}</span></label>`).join("")}</details>`).join("")}
        ${s.strength === "weak" ? `<div class="notice info"><span class="notice-icon">i</span><div><b>Profile weak:</b> ${esc(s.strength_reasons.join("; "))}. Pick from the standard NC topic list too.</div></div>
          <div class="pill-group" style="margin-top:12px">${s.topics.map((t, i) => `<input type="checkbox" name="topic" id="topic-${i}" value="${esc(t)}"${a.focus_topics.includes(t) ? " checked" : ""}><label for="topic-${i}">${esc(t)}</label>`).join("")}</div>` : ""}
        <div class="form-field"><label for="other-priority">Other current priority or project <small>(optional)</small></label>
          <input id="other-priority" type="text" maxlength="300" value="${esc(a.other_priority)}" placeholder="e.g. stream restoration and flood resilience">
          <p class="field-hint"><span class="shield">✓</span> Public information only. Screened on the server before it is saved or used for matching.</p></div>
      </div>
      <div class="q-block"><div class="q-head"><span class="q-num">03</span><span class="q-title">How many applications can you take on this month?</span><span class="q-sub">sets how many top matches you see</span></div>${pills("capacity", s.options.capacity, a.capacity)}</div>
      <div class="q-block"><div class="q-head"><span class="q-num">04</span><span class="q-title">What is the smallest award worth your time?</span></div>${pills("min_award", s.options.min_award, a.min_award)}</div>
      <div class="q-block"><div class="q-head"><span class="q-num">05</span><span class="q-title">Can you provide a cost share or match?</span></div>${pills("cost_share", s.options.cost_share, a.cost_share)}</div>
      <div class="q-block"><div class="q-head"><span class="q-num">06</span><span class="q-title">How much lead time do you need to apply?</span></div>${pills("prep_time", s.options.prep_time, a.prep_time)}</div>
      <div class="survey-privacy"></div>
      <div class="survey-footer"><p>Your answers are saved for ${esc(ag.short)} and can be edited any time.</p><div class="survey-actions"><button class="secondary-button clear-survey-action" type="button">Clear answers</button><button class="primary-button" type="submit">Save and show my matches →</button></div></div>
    </form>`;
  const form = $(".survey-form", box), bar = $(".survey-progress span", box);
  const progress = () => {
    let done = 1 + (form.querySelectorAll("input[name=obj]:checked").length || $("#other-priority", form).value.trim() ? 1 : 0);
    ["capacity", "min_award", "cost_share", "prep_time"].forEach((n) => { if (form.querySelector(`input[name=${n}]:checked`)) done++; });
    bar.style.width = `${(done / 6) * 100}%`;
    $$(".count", form).forEach((c) => { const n = form.querySelectorAll(`input[name=obj][data-goal="${CSS.escape(c.dataset.goal)}"]:checked`).length; c.textContent = n ? `${n} selected` : ""; });
  };
  form.addEventListener("input", progress); setTimeout(progress, 80);
  bindClearSurvey($(".clear-survey-action", form));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = { focus_objectives: $$("input[name=obj]:checked", form).map((i) => i.value), focus_topics: $$("input[name=topic]:checked", form).map((i) => i.value),
      other_priority: $("#other-priority", form).value, capacity: form.capacity.value, min_award: form.min_award.value, cost_share: form.cost_share.value, prep_time: form.prep_time.value };
    const btn = $("button[type=submit]", form); btn.disabled = true;
    try {
      const r = await api(`/api/survey/${App.agency}`, { method: "POST", body });
      if (r.privacy && r.privacy.changed) { $(".survey-privacy", form).innerHTML = privacyNotice(r.privacy); await new Promise((ok) => setTimeout(ok, 1800)); }
      toast("Answers saved. Re-ranking your matches…");
      location.reload();
    } catch (err) { $(".survey-privacy", form).innerHTML = blockedNotice(err.message); btn.disabled = false; $(".survey-privacy", form).scrollIntoView({ behavior: "smooth", block: "center" }); }
  });
}
/* Clear the survey ("filter"): two clicks, then the page re-ranks with neutral answers. Undo puts the old answers back
   (they go through the same server-side privacy filter again). */
const UNDO_KEY = "gb-survey-undo";
function bindClearSurvey(btn) {
  if (!btn || btn.dataset.bound) return;
  btn.dataset.bound = "1";
  const label = btn.textContent; let armed = null;
  const reset = () => { btn.textContent = label; btn.classList.remove("danger"); armed = null; };
  btn.addEventListener("click", async () => {
    if (!armed) { btn.textContent = "Click again to clear"; btn.classList.add("danger"); armed = setTimeout(reset, 5000); return; }
    clearTimeout(armed); btn.disabled = true;
    try {
      const r = await api(`/api/survey/${App.agency}/reset`, { method: "POST", body: {} });
      try { if (r.previous) sessionStorage.setItem(UNDO_KEY, JSON.stringify({ agency: App.agency, answers: r.previous })); } catch { /* storage unavailable: no undo */ }
      toast(r.message); setTimeout(() => location.reload(), 500);
    } catch (e) { toast(e.message, "err"); btn.disabled = false; reset(); }
  });
}
async function clearSurveyNow() {  // from the command menu: one deliberate choice, still undoable
  try {
    const r = await api(`/api/survey/${App.agency}/reset`, { method: "POST", body: {} });
    try { if (r.previous) sessionStorage.setItem(UNDO_KEY, JSON.stringify({ agency: App.agency, answers: r.previous })); } catch { /* no undo */ }
    toast(r.message); setTimeout(() => location.reload(), 500);
  } catch (e) { toast(e.message, "err"); }
}
function offerSurveyUndo() {
  let u = null;
  try { u = JSON.parse(sessionStorage.getItem(UNDO_KEY) || "null"); sessionStorage.removeItem(UNDO_KEY); } catch { return; }
  if (!u || u.agency !== App.agency) return;
  const el = document.createElement("div");
  el.className = "toast ok undo-toast";
  el.innerHTML = `Survey answers cleared. <button class="text-button" type="button">Undo</button>`;
  $(".toast-stack").appendChild(el);
  const gone = setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 320); }, 10000);
  $("button", el).addEventListener("click", async () => {
    clearTimeout(gone); el.remove();
    try { await api(`/api/survey/${App.agency}`, { method: "POST", body: u.answers }); toast("Previous answers restored."); setTimeout(() => location.reload(), 500); }
    catch (e) { toast(e.message, "err"); }
  }, { once: true });
}
function initSurveyModal() {
  const modal = $(".survey-modal");
  const close = () => { modal.classList.remove("open"); modal.setAttribute("aria-hidden", "true"); document.body.classList.remove("modal-open"); };
  $(".survey-close")?.addEventListener("click", close); $(".survey-backdrop")?.addEventListener("click", close);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && modal.classList.contains("open")) close(); });
}

/* ---------------------------------------------------------------- DECISIONS page */
async function pageDecisions() {
  const tbody = $(".decisions-table tbody");
  try {
    const r = await api(`/api/decisions/${App.agency}`);
    counters({ reviewed: r.items.length, ...r.counts });
    tbody.innerHTML = r.items.map((v) => `<tr class="clickable" data-id="${esc(v.opp_id)}"><td class="num">${esc(et(v.at, true))}</td><td><span class="tag ${{ Pursue: "ok", Maybe: "info", Pass: "hot" }[v.action] || ""}">${esc(v.action)}</span></td>
      <td>${esc(v.relevance || "—")}</td><td class="title-cell">${esc(v.title)}</td><td>${esc(v.reason || "—")}</td><td>${esc(v.note || "—")}</td><td>${esc(v.user || "—")}</td><td class="num">${esc(Math.round(v.score_at_review))}</td></tr>`).join("")
      || `<tr><td colspan="8">No decisions yet. Open any match on the Matches page and record Pursue, Maybe or Pass.</td></tr>`;
    $(".table-count").textContent = r.total_actions ? `${r.total_actions} actions recorded in total.` : "";
    $$("tr.clickable", tbody).forEach((tr) => tr.addEventListener("click", () => openDrawer(tr.dataset.id)));
    const btn = $(".clear-decisions");
    if (btn) { btn.hidden = !r.total_actions; if (!btn.dataset.bound) bindClear(btn); }
    const rb = $(".restore-decisions"); if (rb && !rb.dataset.bound) { rb.dataset.bound = "1"; rb.addEventListener("click", restoreDecisions); }
  } catch (e) { tbody.innerHTML = `<tr><td colspan="8">${esc(e.message)}</td></tr>`; }
}

/* Clear all decisions: two clicks (the second confirms), no browser pop-up. The server archives a copy first. */
function bindClear(btn) {
  btn.dataset.bound = "1";
  let armed = null;
  const reset = () => { btn.textContent = "Clear all decisions"; btn.classList.remove("danger"); armed = null; };
  btn.addEventListener("click", async () => {
    const status = $(".clear-status");
    if (!armed) {
      btn.textContent = "Click again to clear everything"; btn.classList.add("danger");
      armed = setTimeout(reset, 5000);  // the confirmation expires if not used
      return;
    }
    clearTimeout(armed); btn.disabled = true;
    try {
      const r = await api(`/api/decisions/${App.agency}/clear`, { method: "POST", body: { confirm: "CLEAR" } });
      status.innerHTML = `<div class="notice screened"><span class="notice-icon">✓</span><div><b>Cleared.</b> ${esc(r.message)} <button class="text-button undo-clear" type="button">Undo</button></div></div>`;
      $(".undo-clear", status)?.addEventListener("click", restoreDecisions, { once: true });
      toast(r.message); await pageDecisions();
    } catch (e) { status.innerHTML = blockedNotice(e.message); }
    finally { btn.disabled = false; reset(); }
  });
}

/* Undo the last clear (the archive is put back in front of anything recorded since). */
async function restoreDecisions() {
  const status = $(".clear-status");
  try {
    const r = await api(`/api/decisions/${App.agency}/restore`, { method: "POST", body: {} });
    status.innerHTML = `<div class="notice screened"><span class="notice-icon">↺</span><div><b>${r.restored ? "Restored." : "Nothing to restore."}</b> ${esc(r.message)}</div></div>`;
    toast(r.message); await pageDecisions();
  } catch (e) { status.innerHTML = blockedNotice(e.message); }
}

/* ---------------------------------------------------------------- EVALUATION page */
const ICONS = { good: "✓", check: "!", bad: "✕", wait: "…" };
const SCORECARD = [["screening", "Screening & time saved"], ["reach", "Reach"], ["score_by_decision", "Score by decision"],
  ["top5", "Top-5 accuracy"], ["position", "Average position of good grants"], ["ordering", "Ranking agreement"],
  ["ai", "AI accuracy"], ["privacy", "Privacy filter in real use"]];
function renderEval(res) {
  const set = (sel, html) => { const el = $(sel); if (el) el.innerHTML = html; };
  if (!res || res.version !== 4) {
    $(".eval-meta").textContent = res && res.run_at ? "The saved result is from an older version. Run the evaluation to update it." : "";
    set(".scorecard", `<div class="empty-state" style="grid-column:1/-1"><strong>${res && res.run_at ? "Run the evaluation to see the new scorecard." : "No evaluation has been run for this agency yet."}</strong>Click “Run evaluation” above. It looks only at the agency picked in the header and usually takes under a minute. You can pause or stop it.</div>`);
    ["learning-box", "reach-box", "check-list", "problem-list", "safety-list"].forEach((c) => set(`.${c}`, ""));
    $(".safety-summary").textContent = "Safety checks";
    return;
  }
  $(".eval-meta").textContent = `Last run ${et(res.run_at, true)} · ${res.data} · ${Number(res.records).toLocaleString()} grants`;
  const sc = res.scorecard || {};
  set(".scorecard", SCORECARD.filter(([k]) => sc[k]).map(([k, title]) => { const c = sc[k];
    return `<article class="score-tile ${c.status} reveal"><div class="score-tile-head"><span class="answer-icon" aria-hidden="true">${ICONS[c.status]}</span><h3>${title}</h3></div>
      <strong class="score-tile-value">${c.value ? esc(c.value) : "—"}</strong><p>${esc(c.text)}</p></article>`; }).join("")
    + `<article class="score-tile ${res.safety.status} reveal"><div class="score-tile-head"><span class="answer-icon" aria-hidden="true">${ICONS[res.safety.status]}</span><h3>Safety rules</h3></div>
      <strong class="score-tile-value">${res.safety.passed}/${res.safety.passed + res.safety.failed}</strong><p>${esc(res.safety.text)}</p></article>`);
  const L = res.learning, pc = (v) => (v == null ? "—" : `${Math.round(v * 100)}%`);
  set(".learning-box", L ? `<div class="learning reveal"><h3>Learning from your team</h3>
      <p>GrantBridge nudges grants that resemble ones you pursued up, and ones that resemble poor fits down (at most 8 points). ${L.paused
        ? "<b>Learning is paused for now:</b> on your decisions so far it did not rank your own judged grants better than the plan alone, so the app is using the plan-only ranking. It switches back on automatically once it helps."
        : `${L.nudged} grant${L.nudged === 1 ? "" : "s"} on your list ${L.nudged === 1 ? "was" : "were"} nudged.`}</p>
      <div class="learning-grid"><div><span>Top-5 accuracy</span><b>${pc(L.before.top5)} → ${pc(L.after.top5)}</b></div><div><span>Ranking agreement</span><b>${pc(L.before.order)} → ${pc(L.after.order)}</b></div></div>
      <p class="field-hint">Before = plan only · after = plan + your feedback. A grant is never moved by its own decision.</p></div>`
    : `<p class="field-hint learning-empty">Once your team has made a few decisions, this shows how much learning from them improves the ranking.</p>`);
  const R = res.reach;
  set(".reach-box", R ? `<div class="reach reveal"><div class="reach-funnel">
      <div><b>${R.reviewed.toLocaleString()}</b><span>grants reviewed</span></div><span class="arrow">→</span>
      <div><b>${R.possible.toLocaleString()}</b><span>possible</span></div><span class="arrow">→</span>
      <div><b>${R.recommended}</b><span>recommended</span></div></div>
      <ul class="check-list"><li class="${R.likely_missed ? "good" : "check"}"><span class="answer-icon">${R.likely_missed ? "✓" : "!"}</span><span>${R.likely_missed} of your top ${R.top} would likely be missed by manual monitoring (an unusual funder <i>and</i> outside your own search words).</span></li>
      <li class="good"><span class="answer-icon">✓</span>${R.outside_usual} of your top ${R.top} come from federal agencies outside your usual partners${R.funders.length ? `, e.g. ${esc(R.funders.slice(0, 3).join(", "))}` : ""}.</li>
      <li class="good"><span class="answer-icon">✓</span>${R.not_own_search} of your top ${R.top} were found by searches beyond your agency's own keywords.</li>
      <li class="good"><span class="answer-icon">✓</span>${R.set_aside.toLocaleString()} grants were set aside automatically, each with a reason.</li>
      ${R.reported_missed.length ? `<li class="${R.reported_caught === R.reported_missed.length ? "good" : "check"}"><span class="answer-icon">${R.reported_caught === R.reported_missed.length ? "✓" : "!"}</span>Grants your team found elsewhere: ${R.reported_missed.length} reported, ${R.reported_caught} already in GrantBridge's top 25.</li>` : ""}</ul></div>` : "");
  const tq = $$(".check-list").find((el) => !el.closest(".reach"));
  if (tq) tq.innerHTML = (res.checklist || []).map((c) => `<li class="${c.status}"><span class="answer-icon" aria-hidden="true">${ICONS[c.status]}</span>${esc(c.text)}</li>`).join("")
    || `<li class="wait"><span class="answer-icon">…</span>No grants to check yet.</li>`;
  set(".problem-list", (res.problems || []).map((p) => `<article class="problem reveal"><h3>${p.url ? `<a href="${safeUrl(p.url)}" target="_blank" rel="noopener">${esc(p.title)} ↗</a>` : esc(p.title)}</h3>
    <p>${esc(p.text)}</p><p class="problem-advice"><b>What to do:</b> ${esc(p.advice)}</p></article>`).join("")
    || `<div class="answer good"><span class="answer-icon">✓</span><div><h3>Nothing to review</h3><p>No grant where the app and your team disagree.</p></div></div>`);
  const s = res.safety;
  $(".safety-summary").textContent = `Safety checks: ${s.passed} passed${s.failed ? `, ${s.failed} failed` : ""}${s.skipped ? `, ${s.skipped} skipped` : ""}`;
  if (s.failed) $(".safety-summary").parentElement.open = true;
  set(".safety-list", res.tests.map((t) => `<div class="safety-row"><span class="test-badge ${esc(t.result)}">${esc(t.result)}</span>
    <div><h3>${esc(t.test)}</h3><p>${esc(t.what)}</p><p class="field-hint">Result: ${esc(t.detail)}</p></div></div>`).join(""));
  reveal();
}
function bindMissed() {
  const f = $(".missed-form"); if (!f || f.dataset.bound) return; f.dataset.bound = "1";
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const out = $(".missed-result", f), v = $("#missed-grant", f).value.trim(); if (!v) return;
    try { const r = await api(`/api/missed/${App.agency}`, { method: "POST", body: { grant: v } }); out.textContent = `${r.message} It will be counted in the next evaluation.`; $("#missed-grant", f).value = ""; }
    catch (err) { out.textContent = err.message; }
  });
}
/* Evaluation runs on the server in the background for the agency picked in the header.
   The page polls its progress and offers Pause / Resume / Stop. */
async function pageEvaluation() {
  const ag = App.meta.agencies.find((x) => x.id === App.agency);
  const short = (id) => (App.meta.agencies.find((x) => x.id === id) || {}).short || String(id || "").toUpperCase();
  $$(".eval-agency").forEach((e) => (e.textContent = ag ? ag.short : "your agency"));
  bindMissed();
  const run = $(".run-eval"), pause = $(".pause-eval"), stop = $(".stop-eval"), box = $(".eval-progress");
  const bar = $(".eval-progress-bar"), fill = $(".eval-progress-bar span"), line = $(".eval-progress-text");
  const ACTIVE = ["running", "paused", "stopping"];
  pause.hidden = stop.hidden = false;   // always shown; greyed out when nothing is running
  let timer = null, lastState = null, note = "";
  const show = (job) => {
    const st = job?.state || "idle", active = ACTIVE.includes(st);
    const mine = !job?.agency || job.agency === App.agency;
    run.disabled = active;
    pause.disabled = stop.disabled = !active || st === "stopping";
    pause.textContent = st === "paused" ? "Resume" : "Pause";
    const pct = job?.total ? Math.round((job.done / job.total) * 100) : 0;
    bar.classList.toggle("paused", st === "paused");
    bar.classList.toggle("done", st === "finished");
    bar.classList.toggle("failed", st === "failed" || st === "stopped");
    box.hidden = st === "idle" && !note;
    if (st === "idle") { fill.style.width = "0%"; line.textContent = note; return st; }
    const who = mine ? "" : ` for ${short(job.agency)}`;
    if (active) {
      fill.style.width = `${pct}%`;
      line.textContent = `${{ running: "Running", paused: "Paused", stopping: "Stopping" }[st]}${who} · step ${job.done} of ${job.total} · ${job.text}`;
    } else if (st === "finished") {
      fill.style.width = "100%";
      line.textContent = mine ? `Finished · step ${job.total} of ${job.total} · results updated below`
        : `The last evaluation was for ${short(job.agency)}. Click “Run evaluation” to evaluate ${ag ? ag.short : "this agency"}.`;
      if (!mine) fill.style.width = "0%";
    } else {
      fill.style.width = `${pct}%`;
      line.textContent = `${st === "stopped" ? "Stopped" : "Failed"}${who} at step ${job.done} of ${job.total}. ${job.text}`;
    }
    if (note) line.textContent = `${note} ${line.textContent}`;
    return st;
  };
  const poll = async () => {
    try {
      const r = await api(`/api/evaluation/${App.agency}`);
      const st = show(r.job);
      if (ACTIVE.includes(st)) { timer = setTimeout(poll, st === "paused" ? 2000 : 1000); }
      else {
        timer = null;
        if (lastState && ACTIVE.includes(lastState)) {
          if (st === "finished") toast(r.job.agency === App.agency ? "Evaluation finished. Results updated." : `The evaluation for ${short(r.job.agency)} finished.`);
          else if (st === "stopped") toast("Evaluation stopped. The previous result is kept.");
          else if (st === "failed") toast(r.job.text, "err");
        }
        renderEval(r.result && r.result.run_at ? r.result : null);
      }
      lastState = st;
    } catch (e) { toast(e.message, "err"); timer = null; }
  };
  run.addEventListener("click", async () => {
    run.disabled = true; note = "";
    try {
      const r = await api(`/api/evaluation/${App.agency}/run`, { method: "POST", body: {} });
      if (r.error) {             // blocked: say why right under the button, not only in a toast
        note = r.error; toast(r.error, "err"); run.disabled = false; show(r.job);
        setTimeout(() => { note = ""; }, 8000);
        if (!timer && ACTIVE.includes(r.job?.state)) { lastState = r.job.state; poll(); }
        return;
      }
      show(r.job); lastState = "running"; if (!timer) poll();
    } catch (e) { toast(e.message, "err"); run.disabled = false; }
  });
  const control = async (action) => {
    try { const r = await api("/api/evaluation/control", { method: "POST", body: { action } }); if (r.error) toast(r.error, "err"); show(r.job); if (!timer) poll(); }
    catch (e) { toast(e.message, "err"); }
  };
  pause.addEventListener("click", () => control(pause.textContent === "Resume" ? "resume" : "pause"));
  stop.addEventListener("click", () => control("stop"));
  poll();
}

/* ---------------------------------------------------------------- boot */
document.addEventListener("DOMContentLoaded", async () => {
  App.reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  svgDefs(); trapFocus(); initTheme(); initHeader(); initCursorGlow(); initCommandMenu(); initSettings(); initDrawer(); initSurveyModal(); initMagnetic(); reveal();
  try { await loadMeta(); } catch (e) { toast(`Couldn't reach the server: ${e.message}`, "err"); return; }
  const page = document.body.dataset.page;
  ({ matches: pageMatches, decisions: pageDecisions, evaluation: pageEvaluation }[page] || (() => {}))();
});

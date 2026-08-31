/* Админ-дашборд модуля мерч-кодов: вход (Google-cookie или PIN), вкладки по ролям.
   Скрытие вкладок — только UX: права на каждую операцию проверяет сервер.
   Общие помощники (monthLabel, esc, $, fmtTime/fmtDate) — common.js. */
"use strict";

let PIN = sessionStorage.getItem("merch_pin") || "";
let ME = null;            // /api/me → auth
let GOOGLE_AUTH = false;  // /api/status → googleAuth
let CURRENT_TAB = null;
let LOG_VIEW = "checks";
let DRAFT = null;         // черновик каталога: правки живут тут до Save
let DIRTY = false;

/* ---------------- transport ---------------- */
async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(PIN ? { "X-Pin": PIN } : {}), ...(opts.headers || {}) };
  let res;
  try { res = await fetch(path, { ...opts, headers }); }
  catch { return { ok: false, error: "network error — check the connection" }; }
  try { return await res.json(); }
  catch { return { ok: false, error: `server error (${res.status})` }; }
}

function setMsg(id, text, kind) {
  const el = $(id);
  el.textContent = text || "";
  el.className = "msg" + (kind ? ` ${kind}` : "");
}

/* ---------------- screens & tabs ---------------- */
const TABS = [
  { id: "overview", roles: ["admin"] },
  { id: "users", roles: ["admin"] },
  { id: "catalog", roles: ["admin", "config"] },
  { id: "journal", roles: ["admin", "ledger"] },
  { id: "discounts", roles: ["admin"] },
  { id: "logs", roles: ["admin"] },
];
const SCREENS = ["login", "norole", "production", ...TABS.map((t) => t.id)];

function showScreen(name) {
  SCREENS.forEach((s) => $(`view-${s}`).classList.toggle("hidden", s !== name));
}

function render() {
  $("boot-msg").classList.add("hidden");
  renderWho();
  const role = ME ? ME.role : null;
  const myTabs = TABS.filter((t) => t.roles.includes(role));
  $("nav").classList.toggle("hidden", !myTabs.length);
  TABS.forEach((t) => $(`tab-${t.id}`).classList.toggle("hidden", !myTabs.includes(t)));
  if (!ME) {
    showScreen("login");
    $("google-block").classList.toggle("hidden", !GOOGLE_AUTH);
    $("pin-btn").classList.toggle("ghost", GOOGLE_AUTH);
    return;
  }
  if (role === "production") { showScreen("production"); return; }
  if (!myTabs.length) { showScreen("norole"); return; } // none и неизвестные роли
  const keep = myTabs.find((t) => t.id === CURRENT_TAB);
  showTab(keep ? keep.id : myTabs[0].id);
}

function renderWho() {
  const box = $("who");
  if (!ME) { box.innerHTML = ""; box.classList.add("hidden"); return; }
  const name = ME.name || ME.email || "PIN session";
  box.innerHTML =
    (ME.picture ? `<img class="avatar" src="${esc(ME.picture)}" alt="">` : "") +
    `<span class="who-name">${esc(name)}</span>` +
    (ME.name && ME.email ? `<span class="who-mail">${esc(ME.email)}</span>` : "") +
    `<span class="role-badge">${esc(ME.role || "—")}</span>` +
    `<button class="logout" id="logout-btn">Log out</button>`;
  $("logout-btn").onclick = logout;
  box.classList.remove("hidden");
}

function showTab(name) {
  CURRENT_TAB = name;
  showScreen(name);
  TABS.forEach((t) => $(`tab-${t.id}`).classList.toggle("active", t.id === name));
  if (name === "overview") loadOverview();
  else if (name === "users") loadUsers();
  else if (name === "catalog") loadCatalog();
  else if (name === "journal") loadJournal();
  else if (name === "discounts") loadDiscounts();
  else if (name === "logs") showLogView(LOG_VIEW);
}

/* ---------------- auth ---------------- */
async function tryPin() {
  const val = $("pin-input").value.trim();
  if (!val) { setMsg("login-msg", "enter the PIN", "err"); return; }
  PIN = val;
  const r = await api("/api/me");
  if (r.ok && r.auth) {
    sessionStorage.setItem("merch_pin", PIN);
    ME = r.auth;
    setMsg("login-msg", "");
    render();
  } else {
    PIN = "";
    sessionStorage.removeItem("merch_pin");
    setMsg("login-msg", r.error || "wrong PIN", "err");
  }
}

async function logout() {
  await api("/api/auth/logout", { method: "POST" });
  sessionStorage.removeItem("merch_pin");
  PIN = "";
  location.reload();
}

/* ---------------- overview ---------------- */
function statCard(value, label, sub = "", cls = "") {
  return `<div class="stat-card"><div class="stat-num${cls ? ` ${cls}` : ""}">${esc(value)}</div>
    <div class="stat-label">${label}</div>${sub ? `<div class="stat-sub">${sub}</div>` : ""}</div>`;
}

async function loadOverview() {
  setMsg("overview-msg", "loading…");
  const r = await api("/api/admin/stats");
  if (!r.ok) { setMsg("overview-msg", r.error || "failed to load", "err"); return; }
  setMsg("overview-msg", "");
  const v = r.verify7d || {};
  const failed = (v.not_issued || 0) + (v.mismatch || 0) + (v.malformed || 0);
  $("stat-grid").innerHTML =
    statCard(r.issued ?? 0, "Issued numbers") +
    statCard(r.registered ?? 0, "Registered owners") +
    statCard(r.checksTotal ?? 0, "Total checks") +
    statCard(failed, "Failed checks · 7d",
      `not issued ${v.not_issued || 0} · mismatch ${v.mismatch || 0} · malformed ${v.malformed || 0}`,
      failed > 0 ? "bad" : "");
  const rows = (r.byProduct || []).map((p) =>
    `<tr><td>${esc(p.product)}</td><td>${esc(p.issued)}</td><td>${esc(p.registered)}</td></tr>`).join("");
  $("stats-products").innerHTML = `<tr><th>Product</th><th>Issued</th><th>Registered</th></tr>` +
    (rows || `<tr><td colspan="3"><span class="dim">nothing issued yet</span></td></tr>`);
  $("stats-meta").innerHTML =
    `service version: ${esc(r.version || "—")} · db schema: ${esc(r.dbSchema ?? "—")}<br>` +
    `key fingerprint: ${esc(r.keyFingerprint || "—")}`;
}

/* ---------------- users ---------------- */
const ROLES_LIST = ["admin", "config", "production", "ledger", "none"];

async function loadUsers() {
  setMsg("users-msg", "loading…");
  const r = await api("/api/admin/users");
  if (!r.ok) { setMsg("users-msg", r.error || "failed to load", "err"); return; }
  setMsg("users-msg", "");
  const rows = (r.users || []).map((u) => `
    <tr${u.active ? "" : ' class="inactive"'}>
      <td><div class="user-cell">
        ${u.picture ? `<img class="avatar" src="${esc(u.picture)}" alt="">` : ""}
        <div>${esc(u.name || "—")}<br><span class="dim">${esc(u.email || "")}</span></div>
      </div></td>
      <td><select class="role-sel" data-id="${esc(u.id)}">
        ${ROLES_LIST.map((x) => `<option value="${x}"${x === u.role ? " selected" : ""}>${x}</option>`).join("")}
      </select></td>
      <td><button class="btn mini ${u.active ? "danger" : "good"} act-btn" data-id="${esc(u.id)}" data-active="${u.active ? "1" : "0"}">
        ${u.active ? "Deactivate" : "Activate"}</button></td>
      <td><span class="dim">${esc(fmtDate(u.lastLoginAt))}</span></td>
    </tr>`).join("");
  $("users-table").innerHTML = `<tr><th>User</th><th>Role</th><th>Status</th><th>Last login</th></tr>` +
    (rows || `<tr><td colspan="4"><span class="dim">no users yet</span></td></tr>`);
  $("users-table").querySelectorAll(".role-sel").forEach((sel) => {
    sel.onchange = () => patchUser(sel.dataset.id, { role: sel.value });
  });
  $("users-table").querySelectorAll(".act-btn").forEach((b) => {
    b.onclick = () => patchUser(b.dataset.id, { active: b.dataset.active !== "1" });
  });
}

async function patchUser(id, patch) {
  const r = await api(`/api/admin/users/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(patch) });
  await loadUsers(); // перечитываем и после ошибки, чтобы вернуть актуальное состояние селектов
  if (!r.ok) setMsg("users-msg", r.error || "failed to update", "err");
}

/* ---------------- catalogue ---------------- */
const SHEETS = ["a5", "a7", "a8"];

async function loadCatalog(force = false) {
  if (DRAFT && DIRTY && !force) { renderCatalog(); return; } // несохранённый черновик не затираем
  setMsg("cat-msg", "loading…");
  const r = await api("/api/catalog");
  if (!r.ok) { setMsg("cat-msg", r.error || "failed to load", "err"); return; }
  if (!r.catalog) { setMsg("cat-msg", "the server did not return the editable catalogue", "err"); return; }
  setMsg("cat-msg", "");
  DRAFT = JSON.parse(JSON.stringify(r.catalog));
  setDirty(false);
  renderCatalog();
}

function setDirty(v) {
  DIRTY = v;
  $("cat-dirty").classList.toggle("hidden", !v);
  $("cat-save").disabled = !v;
}

function renderCatalog() {
  renderPlaces();
  renderTypes();
}

function renderPlaces() {
  const box = $("cat-places");
  box.innerHTML = DRAFT.places.map((p, i) => `
    <div class="cat-row" data-i="${i}">
      <span class="idx">${i}</span>
      <input class="f-name" value="${esc(p.name)}" placeholder="site name">
      <label class="chk"><input type="checkbox" class="f-on"${p.on ? " checked" : ""}> on</label>
    </div>`).join("") || `<div class="msg">no sites yet</div>`;
  box.querySelectorAll(".cat-row").forEach((row) => {
    const i = +row.dataset.i;
    row.querySelector(".f-name").oninput = (e) => { DRAFT.places[i].name = e.target.value; setDirty(true); refreshSiteSelects(); };
    row.querySelector(".f-on").onchange = (e) => { DRAFT.places[i].on = e.target.checked; setDirty(true); };
  });
}

function siteOptions(selected) {
  return [`<option value=""${selected == null ? " selected" : ""}>any site</option>`]
    .concat(DRAFT.places.map((p, i) =>
      `<option value="${i}"${selected === i ? " selected" : ""}>${i} — ${esc(p.name || "unnamed")}</option>`))
    .join("");
}

// обновляет подписи площадок в селектах изделий без полной перерисовки (не сбивает фокус)
function refreshSiteSelects() {
  $("cat-types").querySelectorAll(".f-site").forEach((sel) => {
    const ti = +sel.closest(".cat-type").dataset.i;
    sel.innerHTML = siteOptions(DRAFT.types[ti].site ?? null);
  });
}

function colorRow(c, ci) {
  const hex = String(c.hex || "");
  return `
    <div class="color-row" data-i="${ci}">
      <span class="idx">${ci}</span>
      <input type="color" class="f-pick" value="${esc(pickerHex(hex))}" title="pick colour">
      <input class="f-hex" value="${esc(hex)}" placeholder="#RRGGBB" maxlength="9">
      <input class="f-cname" value="${esc(c.name)}" placeholder="colour name">
      <label class="chk"><input type="checkbox" class="f-con"${c.on ? " checked" : ""}> on</label>
      <button class="del f-cdel" title="Remove colour from the draft">✕</button>
      <input class="f-img" value="${esc(c.img || "")}" placeholder="image URL (optional)">
    </div>`;
}

// input[type=color] принимает только #rrggbb — прочее заменяем нейтральным
function pickerHex(hex) {
  return /^#[0-9a-fA-F]{6}$/.test(hex) ? hex : "#888888";
}

function renderTypes() {
  const box = $("cat-types");
  box.innerHTML = DRAFT.types.map((t, ti) => `
    <div class="card cat-type" data-i="${ti}">
      <div class="cat-type-head">
        <span class="idx">${ti}</span>
        <input class="f-name" value="${esc(t.name)}" placeholder="product name">
        <label class="chk"><input type="checkbox" class="f-on"${t.on ? " checked" : ""}> on</label>
        <button class="del f-del" title="Remove product from the draft">🗑</button>
      </div>
      <div class="cat-grid3">
        <div><label>Certificate sheet</label>
          <select class="f-sheet">${SHEETS.map((s) => `<option value="${s}"${(t.sheet || "a5") === s ? " selected" : ""}>${s}</option>`).join("")}</select></div>
        <div><label>Production site</label>
          <select class="f-site">${siteOptions(t.site ?? null)}</select></div>
        <div><label>Edition size</label>
          <input class="f-edition" type="number" min="1" step="1" value="${t.edition ?? ""}" placeholder="—"></div>
      </div>
      <label>Colours</label>
      <div class="colors">${t.colors.map(colorRow).join("") || `<div class="msg">no colours yet</div>`}</div>
      <button class="btn ghost mini f-addcolor">+ Add colour</button>
    </div>`).join("") || `<div class="msg">no products yet</div>`;
  box.querySelectorAll(".cat-type").forEach(bindTypeCard);
}

function bindTypeCard(card) {
  const ti = +card.dataset.i;
  const t = DRAFT.types[ti];
  card.querySelector(".cat-type-head .f-name").oninput = (e) => { t.name = e.target.value; setDirty(true); };
  card.querySelector(".cat-type-head .f-on").onchange = (e) => { t.on = e.target.checked; setDirty(true); };
  card.querySelector(".cat-type-head .f-del").onclick = () => {
    if (!confirm(`Remove product "${t.name || "unnamed"}" from the draft?`)) return;
    DRAFT.types.splice(ti, 1);
    setDirty(true);
    renderTypes();
  };
  card.querySelector(".f-sheet").onchange = (e) => { t.sheet = e.target.value; setDirty(true); };
  card.querySelector(".f-site").onchange = (e) => { t.site = e.target.value === "" ? null : +e.target.value; setDirty(true); };
  card.querySelector(".f-edition").oninput = (e) => {
    const n = parseInt(e.target.value, 10);
    t.edition = Number.isFinite(n) && n > 0 ? n : null;
    setDirty(true);
  };
  card.querySelector(".f-addcolor").onclick = () => {
    t.colors.push({ name: "", hex: "#888888", on: true, img: null });
    setDirty(true);
    renderTypes();
  };
  card.querySelectorAll(".color-row").forEach((row) => {
    const ci = +row.dataset.i;
    const c = t.colors[ci];
    const pick = row.querySelector(".f-pick");
    const hexIn = row.querySelector(".f-hex");
    row.querySelector(".f-cname").oninput = (e) => { c.name = e.target.value; setDirty(true); };
    pick.oninput = (e) => { c.hex = e.target.value; hexIn.value = e.target.value; setDirty(true); };
    hexIn.oninput = (e) => {
      c.hex = e.target.value.trim();
      if (/^#[0-9a-fA-F]{6}$/.test(c.hex)) pick.value = c.hex;
      setDirty(true);
    };
    row.querySelector(".f-con").onchange = (e) => { c.on = e.target.checked; setDirty(true); };
    row.querySelector(".f-img").oninput = (e) => { c.img = e.target.value.trim() || null; setDirty(true); };
    row.querySelector(".f-cdel").onclick = () => { t.colors.splice(ci, 1); setDirty(true); renderTypes(); };
  });
}

async function saveCatalog() {
  if (!DRAFT) return;
  const cat = JSON.parse(JSON.stringify(DRAFT));
  cat.places.forEach((p) => { p.name = String(p.name || "").trim(); });
  cat.types.forEach((t) => {
    t.name = String(t.name || "").trim();
    t.colors.forEach((c) => {
      c.name = String(c.name || "").trim();
      c.hex = String(c.hex || "").trim();
      c.img = c.img ? String(c.img).trim() : null;
    });
  });
  const btn = $("cat-save");
  btn.disabled = true;
  setMsg("cat-msg", "saving…");
  const r = await api("/api/catalog", { method: "PUT", body: JSON.stringify({ catalog: cat }) });
  if (!r.ok) {
    btn.disabled = false;
    setMsg("cat-msg", r.error || "failed to save", "err");
    return;
  }
  await loadCatalog(true); // перечитываем сохранённую версию с сервера
  setMsg("cat-msg", "Catalogue saved.", "okk");
}

/* ---------------- journal ---------------- */
async function loadJournal() {
  const r = await api("/api/ledger");
  if (!r.ok) { setMsg("journal-msg", r.error || "failed to load", "err"); return; }
  setMsg("journal-msg", "");
  const recs = r.records || [];
  $("journal-count").textContent = `${recs.length} recorded number${recs.length === 1 ? "" : "s"}`;
  const admin = ME && ME.role === "admin";
  $("journal-clear").classList.toggle("hidden", !admin || recs.length === 0);
  const head = `<tr><th>Code</th><th>Product</th><th>№</th><th>Month</th><th>Site</th><th>Checks</th><th>Owner</th><th>Issued by</th>${admin ? "<th></th>" : ""}</tr>`;
  const rows = recs.map((rec) => `
    <tr>
      <td><span class="code">${esc(rec.code)}</span><br><span class="dim">${esc((rec.issuedAt || "").slice(0, 10))}</span></td>
      <td>${esc(rec.product)}<br><span class="dim"><span class="swatch" style="background:${esc(rec.hex || "#888")}"></span>${esc(rec.colorName)}</span></td>
      <td>${String(rec.seq ?? 0).padStart(3, "0")}${rec.edition ? `<br><span class="dim">/ ${esc(rec.edition)}</span>` : ""}</td>
      <td>${esc(rec.monthLabel || (rec.month != null ? monthLabel(rec.month) : "—"))}</td>
      <td>${esc(rec.site)}</td>
      <td>${esc(rec.checks || 0)}</td>
      <td>${rec.owner ? esc(rec.owner.firstName + " " + rec.owner.lastName) : '<span class="dim">—</span>'}</td>
      <td><span class="dim">${esc(rec.issuedBy || "—")}</span></td>
      ${admin ? `<td><button class="del" data-code="${esc(rec.code)}" title="Delete and free the slot">🗑</button></td>` : ""}
    </tr>`).join("");
  $("journal-table").innerHTML = head +
    (rows || `<tr><td colspan="${admin ? 9 : 8}"><span class="dim">nothing recorded yet</span></td></tr>`);
  if (admin) {
    $("journal-table").querySelectorAll(".del").forEach((b) => {
      b.onclick = async () => {
        if (!confirm(`Delete ${b.dataset.code}? The slot becomes free and the same combination can be issued again.`)) return;
        const d = await api(`/api/ledger/${encodeURIComponent(b.dataset.code)}`, { method: "DELETE" });
        if (!d.ok) { setMsg("journal-msg", d.error || "failed", "err"); return; }
        loadJournal();
      };
    });
  }
}

async function clearJournal() {
  if (!confirm("Delete ALL records? This cannot be undone.")) return;
  if (!confirm("Second confirmation: every issued number will be deleted from the register. Continue?")) return;
  const d = await api("/api/ledger?confirm=all", { method: "DELETE" });
  if (!d.ok) { setMsg("journal-msg", d.error || "failed", "err"); return; }
  loadJournal();
}

/* ---------------- discounts ---------------- */
async function loadDiscounts() {
  const r = await api("/api/admin/discounts");
  if (!r.ok) { setMsg("discounts-msg", r.error || "failed to load", "err"); return; }
  setMsg("discounts-msg", "");
  const list = r.discounts || [];
  const active = list.filter((d) => d.status === "active").length;
  $("discounts-count").textContent = `${list.length} discount${list.length === 1 ? "" : "s"} · ${active} active`;
  const head = "<tr><th>Code</th><th>%</th><th>Figurine</th><th>Buyer</th><th>Status</th><th>Email</th><th></th></tr>";
  const rows = list.map((d) => `
    <tr>
      <td><span class="code">${esc(d.token)}</span><br><span class="dim">${esc((d.createdAt || "").slice(0, 10))}</span></td>
      <td>${esc(d.percent)}%</td>
      <td>${d.product ? esc(d.product) + (d.seq != null ? ` <span class="dim">№ ${String(d.seq).padStart(3, "0")}</span>` : "") : `<span class="dim">${esc(d.code)}</span>`}</td>
      <td>${esc(d.email)}</td>
      <td>${d.status === "active"
        ? '<span class="st-ok">ACTIVE</span>'
        : `<span class="dim">USED${d.usedAt ? " · " + esc(d.usedAt.slice(0, 10)) : ""}</span>`}</td>
      <td>${d.emailSent ? '<span class="st-ok">sent</span>' : '<span class="dim">—</span>'}</td>
      <td><button class="btn mini ghost" data-token="${esc(d.token)}" data-next="${d.status === "active" ? "used" : "active"}">
        ${d.status === "active" ? "Mark used" : "Reactivate"}</button></td>
    </tr>`).join("");
  $("discounts-table").innerHTML = head +
    (rows || '<tr><td colspan="7"><span class="dim">no discounts yet — they appear when buyers register figurines</span></td></tr>');
  $("discounts-table").querySelectorAll("button[data-token]").forEach((b) => {
    b.onclick = async () => {
      const d = await api(`/api/admin/discounts/${encodeURIComponent(b.dataset.token)}`, {
        method: "PATCH", body: JSON.stringify({ status: b.dataset.next }),
      });
      if (!d.ok) { setMsg("discounts-msg", d.error || "failed", "err"); return; }
      loadDiscounts();
    };
  });
}

/* ---------------- logs ---------------- */
function showLogView(which) {
  LOG_VIEW = which;
  $("logs-tab-checks").classList.toggle("active", which === "checks");
  $("logs-tab-actions").classList.toggle("active", which === "actions");
  $("logs-checks").classList.toggle("hidden", which !== "checks");
  $("logs-actions").classList.toggle("hidden", which !== "actions");
  if (which === "checks") loadVerifyLog(); else loadAuditLog();
}

async function loadVerifyLog() {
  setMsg("logs-msg", "loading…");
  const st = $("verify-filter").value;
  const q = st && st !== "all" ? `&status=${encodeURIComponent(st)}` : "";
  const r = await api(`/api/admin/verify-log?limit=200${q}`);
  if (!r.ok) { setMsg("logs-msg", r.error || "failed to load", "err"); return; }
  setMsg("logs-msg", "");
  const rows = (r.entries || []).map((e) => `
    <tr>
      <td class="dim">${esc(fmtTime(e.at))}</td>
      <td><span class="code">${esc(e.code)}</span></td>
      <td><span class="${e.status === "issued" ? "st-ok" : "st-bad"}">${esc(e.status)}</span></td>
      <td class="dim">${esc(e.ip || "—")}</td>
    </tr>`).join("");
  $("verify-table").innerHTML = `<tr><th>Time</th><th>Code</th><th>Status</th><th>IP</th></tr>` +
    (rows || `<tr><td colspan="4"><span class="dim">no checks recorded</span></td></tr>`);
}

async function loadAuditLog() {
  setMsg("logs-msg", "loading…");
  const r = await api("/api/admin/audit-log?limit=200");
  if (!r.ok) { setMsg("logs-msg", r.error || "failed to load", "err"); return; }
  setMsg("logs-msg", "");
  const rows = (r.entries || []).map((e) => {
    const det = e.details == null ? "" : (typeof e.details === "object" ? JSON.stringify(e.details) : String(e.details));
    return `
    <tr>
      <td class="dim">${esc(fmtTime(e.at))}</td>
      <td>${esc(e.actor)}</td>
      <td>${esc(e.action)}</td>
      <td class="details">${esc(det)}</td>
    </tr>`;
  }).join("");
  $("audit-table").innerHTML = `<tr><th>Time</th><th>Actor</th><th>Action</th><th>Details</th></tr>` +
    (rows || `<tr><td colspan="4"><span class="dim">no actions recorded</span></td></tr>`);
}

/* ---------------- boot ---------------- */
(async function boot() {
  TABS.forEach((t) => { $(`tab-${t.id}`).onclick = () => showTab(t.id); });
  $("google-btn").onclick = () => { location.href = "/auth/google?mode=staff&next=/admin"; };
  $("pin-btn").onclick = tryPin;
  $("pin-input").addEventListener("keydown", (e) => { if (e.key === "Enter") tryPin(); });
  $("logout-norole").onclick = logout;
  $("logout-production").onclick = logout;
  // экспорт через fetch: заголовок X-Pin при переходе по ссылке не передался бы
  $("journal-export").onclick = async () => {
    const headers = PIN ? { "X-Pin": PIN } : {};
    let res;
    try { res = await fetch("/api/ledger/export.csv", { headers }); }
    catch { setMsg("journal-msg", "network error — check the connection", "err"); return; }
    if (!res.ok) {
      let msg = `export failed (${res.status})`;
      try { msg = (await res.json()).error || msg; } catch {}
      setMsg("journal-msg", msg, "err");
      return;
    }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "catalist-ledger.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  };
  $("journal-clear").onclick = clearJournal;
  $("logs-tab-checks").onclick = () => showLogView("checks");
  $("logs-tab-actions").onclick = () => showLogView("actions");
  $("verify-filter").onchange = loadVerifyLog;
  $("cat-add-place").onclick = () => {
    if (!DRAFT) return;
    DRAFT.places.push({ name: "", on: true });
    setDirty(true);
    renderCatalog();
  };
  $("cat-add-type").onclick = () => {
    if (!DRAFT) return;
    DRAFT.types.push({ name: "", on: true, sheet: "a5", site: null, edition: null, colors: [] });
    setDirty(true);
    renderTypes();
  };
  $("cat-save").onclick = saveCatalog;

  const st = await api("/api/status");
  GOOGLE_AUTH = !!(st && st.googleAuth);
  const me = await api("/api/me");
  if (me.ok && me.auth) {
    ME = me.auth;
  } else {
    ME = null;
    // сохранённый PIN больше не подходит — забываем, чтобы не слать его впустую
    if (PIN) { PIN = ""; sessionStorage.removeItem("merch_pin"); }
    if (!me.ok && me.error) setMsg("login-msg", me.error, "err");
  }
  render();
})();

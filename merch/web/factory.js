/* Рабочее место производства (/factory): выпуск номеров, журнал выпуска,
   печать сертификатов. Вход — сессия Google или PIN (X-Pin на каждый запрос).
   Общие помощники (monthLabel, normalize, esc, $) — common.js;
   оверлей сертификата — cert.js (openCertificate). */
"use strict";

let PIN = sessionStorage.getItem("merch_pin") || "";
let ROLE = null;
let AUTH = null;        // /api/me: {kind, role, email, name} или null
let GOOGLE_AUTH = false;
let CATALOG = null;
let CURRENT_MONTH = 0;
let PREVIEW = null;     // { code, req }
let SAVED_CODE = null;  // последний записанный номер — для печати сертификата

// какие роли открывают вкладку (admin проходит всюду)
const TAB_ROLES = { gen: ["production", "admin"], journal: ["production", "ledger", "admin"] };

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  if (PIN) headers["X-Pin"] = PIN;
  let res;
  try { res = await fetch(path, { ...opts, headers }); }
  catch { return { ok: false, error: "network error — check the connection" }; }
  try { return await res.json(); }
  catch { return { ok: false, error: `server error (${res.status})` }; }
}
window.merchApi = api; // cert.js ходит в API с теми же учётными данными

/* ---------------- tabs ---------------- */
const tabs = ["generate", "journal"];
function showTab(name) {
  tabs.forEach((t) => {
    $(`view-${t}`).classList.toggle("hidden", t !== name);
    $(`tab-${t}`).classList.toggle("active", t === name);
  });
  if (name === "generate") enterStaff("gen");
  if (name === "journal") enterStaff("journal");
}
tabs.forEach((t) => { $(`tab-${t}`).onclick = () => showTab(t); });

/* ---------------- сессия персонала: Google или PIN ---------------- */
async function resolveRole() {
  const st = await api("/api/status");
  CURRENT_MONTH = st.currentMonth ?? 0;
  ROLE = st.role || null;
  GOOGLE_AUTH = !!st.googleAuth;
  const meResp = await api("/api/me");
  AUTH = meResp.auth || null;
  renderSessionFooter();
  return st;
}
function renderSessionFooter() {
  const box = $("foot-session");
  if (!box) return;
  const authed = AUTH && AUTH.kind === "user";
  box.classList.toggle("hidden", !authed);
  if (authed) $("foot-who").textContent = `${AUTH.email} (${AUTH.role})`;
}
function roleAllows(which) {
  return ROLE && (ROLE === "admin" || TAB_ROLES[which].includes(ROLE));
}
async function enterStaff(which) {
  if (!ROLE) await resolveRole();
  document.querySelectorAll(".google-btn").forEach((b) => b.classList.toggle("hidden", !GOOGLE_AUTH || !!ROLE));
  document.querySelectorAll(".or-sep").forEach((b) => b.classList.toggle("hidden", !GOOGLE_AUTH || !!ROLE));
  const allowed = roleAllows(which);
  const deniedMsg = ROLE && !allowed
    ? (ROLE === "none"
        ? "Your account has no role yet — ask the administrator to assign one."
        : `Your role (${ROLE}) does not open this module.`)
    : "";
  if (which === "gen") {
    $("gen-login").classList.toggle("hidden", allowed);
    $("gen-app").classList.toggle("hidden", !allowed);
    $("pin-msg").textContent = deniedMsg;
    $("pin-msg").className = "msg err";
    if (allowed) loadCatalog();
  } else {
    $("journal-login").classList.toggle("hidden", allowed);
    $("journal-app").classList.toggle("hidden", !allowed);
    $("pin-msg2").textContent = deniedMsg;
    $("pin-msg2").className = "msg err";
    if (allowed) loadJournal();
  }
}
document.querySelectorAll(".google-btn").forEach((b) => {
  b.onclick = () => { location.href = "/auth/google?mode=staff&next=" + encodeURIComponent(b.dataset.next || "/factory"); };
});
const footLogout = $("foot-logout");
if (footLogout) footLogout.onclick = async (e) => {
  e.preventDefault();
  await api("/api/auth/logout", { method: "POST" });
  sessionStorage.removeItem("merch_pin");
  location.href = "/factory";
};
async function tryPin(inputId, msgId) {
  const el = $(msgId);
  PIN = $(inputId).value.trim();
  if (!PIN) { el.textContent = "enter the PIN"; el.className = "msg err"; return; }
  const st = await resolveRole();
  if (!ROLE) {
    PIN = "";
    el.textContent = st.error || "wrong PIN";
    el.className = "msg err";
    return;
  }
  sessionStorage.setItem("merch_pin", PIN);
  el.textContent = "";
  enterStaff("gen"); enterStaff("journal");
}
$("pin-btn").onclick = () => tryPin("pin-input", "pin-msg");
$("pin-btn2").onclick = () => tryPin("pin-input2", "pin-msg2");
$("pin-input").addEventListener("keydown", (e) => { if (e.key === "Enter") tryPin("pin-input", "pin-msg"); });
$("pin-input2").addEventListener("keydown", (e) => { if (e.key === "Enter") tryPin("pin-input2", "pin-msg2"); });

/* ---------------- generate ---------------- */
async function loadCatalog() {
  const r = await api("/api/catalog");
  if (!r.ok) { $("gen-msg").textContent = r.error || "failed to load the catalogue"; $("gen-msg").className = "msg err"; return; }
  CATALOG = r;
  CURRENT_MONTH = r.currentMonth ?? CURRENT_MONTH;
  const place = $("gen-place");
  place.innerHTML = r.places.map((p) => `<option value="${p.i}">${esc(p.name)}</option>`).join("");
  const monthSel = $("gen-month");
  monthSel.innerHTML = Array.from({ length: 256 }, (_, m) => `<option value="${m}">${monthLabel(m)}</option>`).join("");
  monthSel.value = String(CURRENT_MONTH);
  fillTypes();
}
function fillTypes() {
  const placeI = +$("gen-place").value;
  const types = CATALOG.types.filter((t) => t.site === undefined || t.site === null || t.site === placeI);
  $("gen-type").innerHTML = types.length
    ? types.map((t) => `<option value="${t.i}">${esc(t.name)}</option>`).join("")
    : `<option value="">— no products for this site —</option>`;
  fillColors();
}
function fillColors() {
  const t = CATALOG.types.find((x) => x.i === +$("gen-type").value);
  $("gen-color").innerHTML = t && t.colors.length
    ? t.colors.map((c) => `<option value="${c.j}">${esc(c.name)}</option>`).join("")
    : `<option value="">— no colours —</option>`;
  refreshSeq();
}
async function refreshSeq() {
  clearPreview();
  const req = currentReq();
  if (req == null) { $("gen-seq-hint").textContent = ""; return; }
  const r = await api(`/api/issue/next-seq?type=${req.type}&color=${req.color}&month=${req.month}&place=${req.place}`);
  if (r.ok) {
    $("gen-seq").value = r.seq;
    $("gen-seq-hint").textContent = `next free edition number: ${r.seq} · already issued for this selection: ${r.used}`;
  }
}
function currentReq() {
  const type = $("gen-type").value, color = $("gen-color").value;
  if (type === "" || color === "") return null;
  return {
    type: +type, color: +color,
    month: +$("gen-month").value, place: +$("gen-place").value,
    seq: Math.max(0, Math.min(4095, +$("gen-seq").value || 0)),
  };
}
function clearPreview() {
  PREVIEW = null;
  SAVED_CODE = null;
  $("gen-preview").classList.add("hidden");
  $("gen-saved").classList.add("hidden");
  $("gen-save").classList.remove("hidden");
  $("gen-msg").textContent = "";
}
$("gen-place").onchange = fillTypes;
$("gen-type").onchange = fillColors;
$("gen-color").onchange = refreshSeq;
$("gen-month").onchange = refreshSeq;
$("gen-seq").oninput = clearPreview;

function renderPlate(elId, code) {
  $(elId).innerHTML = [...code].map((ch) => `<div>${esc(ch)}</div>`).join("");
}
$("gen-btn").onclick = async () => {
  const msg = $("gen-msg");
  const req = currentReq();
  if (!req) { msg.textContent = "pick a product and a colour"; msg.className = "msg err"; return; }
  const r = await api("/api/issue/preview", { method: "POST", body: JSON.stringify(req) });
  if (!r.ok) {
    clearPreview();
    msg.className = "msg err";
    msg.textContent = r.code
      ? `Serial number already exists. This product, colour, month and edition number were issued as ${r.code}. Change the edition number.`
      : (r.error || "failed");
    return;
  }
  PREVIEW = { code: r.code, req };
  renderPlate("gen-plate", r.code);
  $("gen-preview").classList.remove("hidden");
  $("gen-saved").classList.add("hidden");
  $("gen-save").classList.remove("hidden");
  msg.textContent = ""; msg.className = "msg";
};
$("gen-save").onclick = async () => {
  if (!PREVIEW) return;
  const msg = $("gen-msg");
  const r = await api("/api/issue/confirm", {
    method: "POST",
    body: JSON.stringify({ ...PREVIEW.req, expectedCode: PREVIEW.code }),
  });
  if (!r.ok) {
    msg.className = "msg err";
    msg.textContent = r.code ? `already issued as ${r.code} — generate again` : (r.error || "failed");
    return;
  }
  SAVED_CODE = r.code;
  $("gen-save").classList.add("hidden");
  $("gen-saved").classList.remove("hidden");
  $("gen-saved-msg").textContent = `Recorded. ${r.code} is now in the register.`;
  $("gen-cert").onclick = () => openCertificate(SAVED_CODE);
  $("gen-copy").onclick = () => navigator.clipboard.writeText(r.code);
  $("gen-copy-url").onclick = () => navigator.clipboard.writeText(r.verifyUrl || location.origin + "/" + r.code);
  msg.textContent = "";
};

/* ---------------- journal ---------------- */
async function loadJournal() {
  const r = await api("/api/ledger");
  const msg = $("journal-msg");
  if (!r.ok) { msg.textContent = r.error || "failed to load"; msg.className = "msg err"; return; }
  msg.textContent = "";
  $("journal-count").textContent = `${r.records.length} recorded number${r.records.length === 1 ? "" : "s"}`;
  const admin = ROLE === "admin";
  $("journal-clear").classList.toggle("hidden", !admin || r.records.length === 0);
  const head = `<tr><th>Code</th><th>Product</th><th>№</th><th>Month</th><th>Site</th><th>Checks</th><th>Owner</th>${admin ? "<th></th>" : ""}</tr>`;
  // кнопка сертификата — в первой колонке: на телефоне таблица скроллится
  // вбок, и главное действие производства должно быть видно без прокрутки
  const rows = r.records.map((rec) => `
    <tr>
      <td><span class="code">${esc(rec.code)}</span><br><span class="dim">${esc((rec.issuedAt || "").slice(0, 10))}</span><br>
        <button class="cert-open" data-code="${esc(rec.code)}" title="Print the certificate">Certificate</button></td>
      <td>${esc(rec.product)}<br><span class="dim"><span class="swatch" style="background:${esc(rec.hex || "#888")}"></span>${esc(rec.colorName)}</span></td>
      <td>${String(rec.seq).padStart(3, "0")}${rec.edition ? `<br><span class="dim">/ ${rec.edition}</span>` : ""}</td>
      <td>${esc(rec.monthLabel || monthLabel(rec.month))}</td>
      <td>${esc(rec.site)}</td>
      <td>${rec.checks || 0}</td>
      <td>${rec.owner ? esc(rec.owner.firstName + " " + rec.owner.lastName) : '<span class="dim">—</span>'}</td>
      ${admin ? `<td class="cell-actions"><button class="del" data-code="${esc(rec.code)}" title="Delete and free the slot">🗑</button></td>` : ""}
    </tr>`).join("");
  $("journal-table").innerHTML = head + rows;
  $("journal-table").querySelectorAll(".cert-open").forEach((b) => {
    b.onclick = () => openCertificate(b.dataset.code);
  });
  if (admin) {
    $("journal-table").querySelectorAll(".del").forEach((b) => {
      b.onclick = async () => {
        if (!confirm(`Delete ${b.dataset.code}? The slot becomes free and the same combination can be issued again.`)) return;
        const d = await api(`/api/ledger/${b.dataset.code}`, { method: "DELETE" });
        if (!d.ok) { msg.textContent = d.error || "failed"; msg.className = "msg err"; return; }
        loadJournal();
      };
    });
    $("journal-clear").onclick = async () => {
      if (!confirm("Delete ALL records? This cannot be undone.")) return;
      const d = await api("/api/ledger?confirm=all", { method: "DELETE" });
      if (!d.ok) { msg.textContent = d.error || "failed"; msg.className = "msg err"; return; }
      loadJournal();
    };
  }
}

/* ---------------- boot ---------------- */
(async function boot() {
  await resolveRole();
  showTab("generate");
})();

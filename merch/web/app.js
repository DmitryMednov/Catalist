/* Клиент модуля мерч-кодов: проверка публичная, выдача и журнал — по сессии
   Google или PIN. Общие помощники (monthLabel, normalize, esc, $) — common.js. */
"use strict";

let PIN = sessionStorage.getItem("merch_pin") || "";
let ROLE = null;
let AUTH = null;        // /api/me: {kind, role, email, name} или null
let GOOGLE_AUTH = false;
let CATALOG = null;
let CURRENT_MONTH = 0;
let PREVIEW = null; // { code, req }

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

/* ---------------- tabs ---------------- */
const tabs = ["check", "generate", "journal"];
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
  b.onclick = () => { location.href = "/auth/google?mode=staff&next=" + encodeURIComponent(b.dataset.next || "/"); };
});
const footLogout = $("foot-logout");
if (footLogout) footLogout.onclick = async (e) => {
  e.preventDefault();
  await api("/api/auth/logout", { method: "POST" });
  sessionStorage.removeItem("merch_pin");
  location.href = "/";
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
  $("gen-save").classList.add("hidden");
  $("gen-saved").classList.remove("hidden");
  $("gen-saved-msg").textContent = `Recorded. ${r.code} is now in the register.`;
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
  const rows = r.records.map((rec) => `
    <tr>
      <td><span class="code">${esc(rec.code)}</span><br><span class="dim">${esc((rec.issuedAt || "").slice(0, 10))}</span></td>
      <td>${esc(rec.product)}<br><span class="dim"><span class="swatch" style="background:${esc(rec.hex || "#888")}"></span>${esc(rec.colorName)}</span></td>
      <td>${String(rec.seq).padStart(3, "0")}${rec.edition ? `<br><span class="dim">/ ${rec.edition}</span>` : ""}</td>
      <td>${esc(rec.monthLabel || monthLabel(rec.month))}</td>
      <td>${esc(rec.site)}</td>
      <td>${rec.checks || 0}</td>
      <td>${rec.owner ? esc(rec.owner.firstName + " " + rec.owner.lastName) : '<span class="dim">—</span>'}</td>
      ${admin ? `<td><button class="del" data-code="${esc(rec.code)}" title="Delete and free the slot">🗑</button></td>` : ""}
    </tr>`).join("");
  $("journal-table").innerHTML = head + rows;
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

/* ---------------- check ---------------- */
function statusCard(kind, title, sub, extra = "") {
  return `<div class="status-card ${kind}"><div class="status-title">${title}</div>
    <div class="status-sub">${sub}</div>${extra}</div>`;
}
async function runCheck() {
  const msg = $("check-msg");
  const box = $("check-result");
  const code = normalize($("check-input").value);
  $("check-input").value = code;
  box.innerHTML = "";
  if (code.length !== 8) { msg.textContent = "the number is 8 characters long"; msg.className = "msg err"; return; }
  msg.textContent = "checking…"; msg.className = "msg";
  const r = await api("/api/verify", { method: "POST", body: JSON.stringify({ code }) });
  msg.textContent = "";
  if (r.status === "malformed") {
    box.innerHTML = statusCard("warn", "Mistyped number",
      "This combination cannot be a Catalist serial number — one of the characters is off. Compare with the certificate or the engraving and try again.");
    return;
  }
  if (r.status === "not_issued") {
    box.innerHTML = statusCard("bad", "Never issued",
      `The number ${esc(r.code)} is formatted correctly but was never issued by Catalist. If it is printed on a product, the item is not genuine.`);
    return;
  }
  if (r.status === "mismatch") {
    box.innerHTML = statusCard("bad", "Does not match the record",
      "The number decodes to a different product than the one on record. Please contact Catalist.");
    return;
  }
  if (r.status !== "issued") {
    box.innerHTML = statusCard("warn", "Try later", esc(r.error || "the service is busy"));
    return;
  }
  const kv = (k, v) => `<div class="kv"><div class="k">${k}</div><div class="v">${v}</div></div>`;
  let details = kv("Product", esc(r.product))
    + kv("Colour", `<span class="swatch" style="background:${esc(r.hex || "#888")}"></span>${esc(r.color)}`)
    + kv("Edition", `№ ${String(r.seq).padStart(3, "0")}${r.edition ? ` / ${r.edition}` : ""}`)
    + kv("Manufactured", esc(r.monthLabel || monthLabel(r.month)))
    + kv("Site", esc(r.site))
    + kv("Checks so far", String(r.checks));
  if (r.img) details += `<img class="product-photo" src="${esc(r.img)}" alt="${esc(r.product)}">`;
  let regBlock;
  if (r.registered) {
    regBlock = `<div class="msg okk">Registered to ${esc(r.owner.firstName)} ${esc(r.owner.lastName)}.</div>`;
  } else {
    regBlock = `
      <div class="card" id="reg-card">
        <div class="status-sub"><b>Register this piece.</b> Registration is possible once per number and ties it to its owner.</div>
        <div class="row">
          <div><label>First name</label><input id="reg-first" autocomplete="given-name"></div>
          <div><label>Last name</label><input id="reg-last" autocomplete="family-name"></div>
        </div>
        <label>Date of birth</label><input id="reg-dob" type="date">
        <label>Email</label><input id="reg-email" type="email" autocomplete="email" placeholder="you@example.com">
        ${GOOGLE_AUTH ? '<button class="btn ghost" id="reg-google">Fill from Google</button>' : ""}
        <button class="btn" id="reg-btn">Register</button>
        <div class="msg" id="reg-msg"></div>
      </div>`;
  }
  box.innerHTML = statusCard("genuine", "Genuine",
    `Serial number ${esc(r.code)} was issued by ${esc((r.certificate && r.certificate.brand) || "Catalist")} and matches the record.`,
    details) + regBlock;
  const gbtn = $("reg-google");
  if (gbtn) gbtn.onclick = () => {
    location.href = "/auth/google?mode=buyer&next=" + encodeURIComponent("/" + code);
  };
  // после возврата из Google данные лежат в короткоживущей cookie
  if ($("reg-first")) {
    const pf = await api("/api/me/prefill");
    if (pf.ok && pf.prefill) {
      $("reg-first").value = $("reg-first").value || pf.prefill.firstName;
      $("reg-last").value = $("reg-last").value || pf.prefill.lastName;
      $("reg-email").value = $("reg-email").value || pf.prefill.email;
    }
  }
  const btn = $("reg-btn");
  if (btn) btn.onclick = async () => {
    const rm = $("reg-msg");
    const body = {
      code, firstName: $("reg-first").value, lastName: $("reg-last").value,
      dob: $("reg-dob").value, email: $("reg-email").value,
    };
    const res = await api("/api/register", { method: "POST", body: JSON.stringify(body) });
    if (!res.ok) { rm.textContent = res.error || "failed"; rm.className = "msg err"; return; }
    $("reg-card").outerHTML = `<div class="msg okk">Registered to ${esc(res.owner.firstName)} ${esc(res.owner.lastName)}. Thank you!</div>`;
  };
}
$("check-btn").onclick = runCheck;
$("check-input").addEventListener("keydown", (e) => { if (e.key === "Enter") runCheck(); });

/* ---------------- boot: deep link /XXXXXXXX from the QR code ---------------- */
(async function boot() {
  await resolveRole();
  const path = normalize(decodeURIComponent(location.pathname.slice(1)));
  showTab("check");
  if (path.length === 8) {
    $("check-input").value = path;
    history.replaceState(null, "", "/" + path);
    runCheck();
  }
})();

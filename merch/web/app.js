/* Клиентская страница: проверка номера и регистрация владельца.
   Выпуск номеров и журнал — на /factory, дашборд — на /admin.
   Общие помощники (monthLabel, normalize, esc, $) — common.js. */
"use strict";

let AUTH = null;        // /api/me: {kind, role, email, name} или null
let GOOGLE_AUTH = false;

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  let res;
  try { res = await fetch(path, { ...opts, headers }); }
  catch { return { ok: false, error: "network error — check the connection" }; }
  try { return await res.json(); }
  catch { return { ok: false, error: `server error (${res.status})` }; }
}

async function resolveSession() {
  const st = await api("/api/status");
  GOOGLE_AUTH = !!st.googleAuth;
  const meResp = await api("/api/me");
  AUTH = meResp.auth || null;
  const box = $("foot-session");
  if (box) {
    const authed = AUTH && AUTH.kind === "user";
    box.classList.toggle("hidden", !authed);
    if (authed) $("foot-who").textContent = `${AUTH.email} (${AUTH.role})`;
  }
}
const footLogout = $("foot-logout");
if (footLogout) footLogout.onclick = async (e) => {
  e.preventDefault();
  await api("/api/auth/logout", { method: "POST" });
  location.href = "/";
};

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
  let details = "";
  if (r.img) details += `<img class="product-photo" src="${esc(r.img)}" alt="${esc(r.product)} — ${esc(r.color)}">`;
  details += kv("Product", esc(r.product))
    + kv("Colour", `<span class="swatch" style="background:${esc(r.hex || "#888")}"></span>${esc(r.color)}`)
    + kv("Edition", `№ ${String(r.seq).padStart(3, "0")}${r.edition ? ` / ${r.edition}` : ""}`)
    + kv("Manufactured", esc(r.monthLabel || monthLabel(r.month)))
    + kv("Site", esc(r.site))
    + kv("Checks so far", String(r.checks));
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
  const seal = `<span class="seal"><svg width="34" height="34" viewBox="0 0 34 34" fill="none" aria-hidden="true">
      <path d="M17 1l3.2 3 4.3-1 1.4 4.2 4.2 1.4-1 4.3 3 3.1-3 3.1 1 4.3-4.2 1.4-1.4 4.2-4.3-1-3.2 3-3.2-3-4.3 1-1.4-4.2-4.2-1.4 1-4.3-3-3.1 3-3.1-1-4.3 4.2-1.4L9.5 3l4.3 1z" fill="currentColor"/>
      <path d="M11.5 17.5l3.5 3.5 7-7" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>
    </svg></span>`;
  box.innerHTML = statusCard("genuine", seal + "Genuine",
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
    const d = res.discount;
    $("reg-card").outerHTML = `
      <div class="discount-card">
        <div class="dc-title">${d ? esc(String(d.percent)) + "% OFF" : "Registered"}</div>
        <div class="dc-sub">Registered to ${esc(res.owner.firstName)} ${esc(res.owner.lastName)}.
          ${d ? "Your loyalty discount is saved to your collection — show its QR code at checkout." : ""}</div>
        ${res.emailQueued ? '<div class="dc-note">A confirmation email with your sign-in link is on its way.</div>' : ""}
        <a class="btn light" href="${esc(res.cabinetUrl || "/my")}">Open my collection</a>
      </div>`;
  };
}
$("check-btn").onclick = runCheck;
$("check-input").addEventListener("keydown", (e) => { if (e.key === "Enter") runCheck(); });

/* ---------------- boot: deep link /XXXXXXXX from the QR code ---------------- */
(async function boot() {
  await resolveSession();
  const path = normalize(decodeURIComponent(location.pathname.slice(1)));
  if (path.length === 8) {
    $("check-input").value = path;
    history.replaceState(null, "", "/" + path);
    runCheck();
  }
})();

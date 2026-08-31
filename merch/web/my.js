/* Личный кабинет покупателя (/my): вход по email-ссылке или через Google,
   список зарегистрированных фигурок и QR персональной скидки.
   Страница самодостаточна — общие помощники продублированы локально. */
"use strict";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const day = (iso) => String(iso || "").slice(0, 10);

/* декоративная «искра» рядом с главным заголовком (по фирменным макетам) */
const SPARK = '<svg class="spark" viewBox="0 0 24 24" fill="none" aria-hidden="true">'
  + '<path d="M12 9V2M5.5 11 2 6.5M18.5 11 22 6.5" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>';

let GOOGLE_AUTH = false;

/* fetch с cookie того же источника; всегда { status, data } (status 0 — сеть недоступна) */
async function fetchJson(path, opts = {}) {
  let res;
  try { res = await fetch(path, { credentials: "same-origin", ...opts }); }
  catch { return { status: 0, data: null }; }
  let data = null;
  try { data = await res.json(); } catch { /* ответ без JSON */ }
  return { status: res.status, data };
}

const postJson = (path, body) => fetchJson(path, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

/* ---------------- экраны ---------------- */

function renderLoading() {
  $("main").innerHTML = `<div class="page-loading">Loading&hellip;</div>`;
}

function renderError() {
  $("main").innerHTML = `
    <div class="pcard">
      <p class="lead">Could not load your collection — try again.</p>
      <button class="pill pill-secondary" id="retry-btn">Retry</button>
    </div>`;
  $("retry-btn").onclick = boot;
}

/* ---------------- вход ---------------- */

function renderLogin() {
  const google = GOOGLE_AUTH ? `
      <button class="pill pill-primary" id="google-btn">Sign in with Google</button>
      <div class="or-line">— or —</div>` : "";
  $("main").innerHTML = `
    <h1>Your Catalist <b>collection</b>${SPARK}</h1>
    <div class="pcard">
      ${google}
      <p class="lead">Enter the email you used when registering your figurine — we will send you a sign-in link.</p>
      <label for="email-input">Email</label>
      <input id="email-input" type="email" autocomplete="email" inputmode="email"
             autocapitalize="off" spellcheck="false" placeholder="you@example.com">
      <button class="pill pill-primary" id="link-btn">Email me a sign-in link</button>
      <div class="note" id="login-msg"></div>
    </div>`;
  const gbtn = $("google-btn");
  if (gbtn) gbtn.onclick = () => { location.href = "/auth/google?mode=cabinet&next=/my"; };
  $("link-btn").onclick = sendLink;
  $("email-input").addEventListener("keydown", (e) => { if (e.key === "Enter") sendLink(); });
}

async function sendLink() {
  const msg = $("login-msg");
  const btn = $("link-btn");
  const email = $("email-input").value.trim();
  if (!email) { msg.textContent = "Enter your email."; msg.className = "note err"; return; }
  msg.textContent = "Sending…"; msg.className = "note";
  btn.disabled = true;
  const r = await postJson("/api/my/link", { email });
  btn.disabled = false;
  if (r.status === 200 && r.data && r.data.ok) {
    msg.textContent = r.data.message || "Check your inbox.";
    msg.className = "note okk";
  } else if (r.status === 429) {
    msg.textContent = (r.data && r.data.error) || "Too many requests — try again in a minute.";
    msg.className = "note err";
  } else {
    msg.textContent = (r.data && r.data.error) || "Could not send the link — try again.";
    msg.className = "note err";
  }
}

/* ---------------- кабинет ---------------- */

function discountBlock(d) {
  const used = d.status === "used";
  const note = used
    ? "This discount has already been used."
    : "Show this QR code at checkout to get your discount.";
  return `
    <div class="discount${used ? " discount-used" : ""}">
      <div class="discount-head">
        <div class="discount-title">${esc(String(d.percent))}% loyalty discount</div>
        <span class="badge ${used ? "badge-used" : "badge-active"}">${used ? "USED" : "ACTIVE"}</span>
      </div>
      <div class="qr-box">
        <img src="/api/my/qr/${encodeURIComponent(d.token)}" alt="Discount QR" style="width:100%;max-width:260px">
      </div>
      <div class="discount-token mono">${esc(d.token)}</div>
      <div class="discount-note">${esc(note)}</div>
    </div>`;
}

function figurineCard(f) {
  const kv = (k, v) => `<div class="kvr"><div class="k">${k}</div><div class="v">${v}</div></div>`;
  const photo = f.img
    ? `<img class="fig-photo" src="${esc(f.img)}" alt="${esc(f.product)}">`
    : `<div class="fig-stub" style="background:${esc(f.hex || "#B9AF98")}"></div>`;
  const rows = kv("Edition", `№ ${esc(String(f.seq).padStart(3, "0"))}${f.edition ? ` / ${esc(String(f.edition))}` : ""}`)
    + kv("Manufactured", esc(f.monthLabel))
    + kv("Site", esc(f.site))
    + kv("Serial", `<span class="mono serial">${esc(f.code)}</span>`)
    + kv("Registered", esc(day(f.registeredAt)));
  return `
    <div class="pcard fig-card">
      ${photo}
      <div class="fig-body">
        <div class="fig-name">${esc(f.product)}</div>
        <div class="fig-color"><span class="swatch2" style="background:${esc(f.hex || "#B9AF98")}"></span><span>${esc(f.color)}</span></div>
        <div class="fig-rows">${rows}</div>
        ${f.discount ? discountBlock(f.discount) : ""}
      </div>
    </div>`;
}

function renderCabinet(data) {
  const figs = data.figurines || [];
  const cards = figs.length
    ? figs.map(figurineCard).join("")
    : `
    <div class="pcard">
      <p class="lead">No registered figurines yet. Check your figurine's serial number and register it to get your loyalty discount.</p>
      <a class="pill pill-primary" href="/">Check a serial number</a>
    </div>`;
  $("main").innerHTML = `
    <h1>My <b>collection</b>${SPARK}</h1>
    <div class="session-row">
      <div class="who">Signed in as <b>${esc(data.email)}</b></div>
      <button class="linklike" id="logout-btn">Log out</button>
    </div>
    ${cards}`;
  $("logout-btn").onclick = async () => {
    await fetchJson("/api/my/logout", { method: "POST" });
    location.reload();
  };
}

/* ---------------- загрузка ---------------- */

async function boot() {
  renderLoading();
  const [my, st] = await Promise.all([fetchJson("/api/my"), fetchJson("/api/status")]);
  GOOGLE_AUTH = !!(st.data && st.data.googleAuth);
  if (my.status === 200 && my.data && my.data.ok) { renderCabinet(my.data); return; }
  if (my.status === 401) { renderLogin(); return; }
  renderError();
}

boot();

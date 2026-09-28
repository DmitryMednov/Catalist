/* Бургер-меню разделов: единое для всех страниц модуля.
   Скрипт сам вставляет кнопку в шапку (.brand или .topbar-in) и
   стеклянный оверлей в body — страницам достаточно подключить файл.

   Пункты зависят от роли: гость и покупатель видят только клиентские
   разделы; Factory и Admin появляются после входа по PIN или Google
   (доступ к данным всё равно закрыт ролями на API — меню лишь не
   показывает лишнего). */
"use strict";
(function () {
  const LINKS_BASE = [
    ["Check <b>authenticity</b>", "/"],
    ["My <b>collection</b>", "/my"],
  ];
  // какие роли открывают служебные разделы (совпадает с проверками API)
  const LINKS_STAFF = [
    ["Factory <b>issuing</b>", "/factory", ["production", "ledger", "admin"]],
    ["Admin <b>dashboard</b>", "/admin", ["admin", "config", "ledger"]],
  ];
  const LINK_SITE = ["catalist<b>.world</b>", "https://catalist.world"];

  const host = document.querySelector(".brand") || document.querySelector(".topbar-in");
  if (!host) return;

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "burger";
  btn.setAttribute("aria-label", "Menu");
  btn.setAttribute("aria-expanded", "false");
  btn.innerHTML = "<span></span><span></span><span></span>";
  host.appendChild(btn);

  const ov = document.createElement("div");
  ov.className = "menu-overlay";
  ov.hidden = true;
  document.body.appendChild(ov);

  const here = location.pathname.replace(/\/+$/, "") || "/";
  function render(role) {
    const links = LINKS_BASE
      .concat(LINKS_STAFF.filter(([, , roles]) => role && roles.includes(role)))
      .concat([LINK_SITE]);
    ov.innerHTML = '<nav class="menu-panel" aria-label="Catalist sections">'
      + links.map(([label, href], i) => {
          const current = href === here ? ' class="current" aria-current="page"' : "";
          return `<a href="${href}" style="--i:${i}"${current}>${label}</a>`;
        }).join("")
      + '<div class="menu-copy">© 2026 Catalist · Special edition</div></nav>';
  }
  render(null);

  // роль текущей сессии: cookie Google уходит сама, PIN — из sessionStorage
  (async function resolveRole() {
    try {
      const headers = {};
      const pin = sessionStorage.getItem("merch_pin");
      if (pin) headers["X-Pin"] = pin;
      const r = await fetch("/api/me", { headers });
      const j = await r.json();
      if (j && j.auth && j.auth.role) render(j.auth.role);
    } catch { /* нет сети — остаются клиентские пункты */ }
  })();

  function setOpen(open) {
    ov.hidden = !open;
    btn.classList.toggle("open", open);
    btn.setAttribute("aria-expanded", String(open));
    document.documentElement.classList.toggle("menu-lock", open);
    if (open) {
      const a = ov.querySelector("a:not(.current)");
      if (a) a.focus({ preventScroll: true });
    }
  }
  btn.addEventListener("click", () => setOpen(ov.hidden));
  ov.addEventListener("click", (e) => { if (e.target === ov) setOpen(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !ov.hidden) setOpen(false); });
})();

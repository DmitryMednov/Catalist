/* Бургер-меню разделов: единое для всех страниц модуля.
   Скрипт сам вставляет кнопку в шапку (.brand или .topbar-in) и
   стеклянный оверлей в body — страницам достаточно подключить файл. */
"use strict";
(function () {
  const LINKS = [
    ["Check <b>authenticity</b>", "/"],
    ["My <b>collection</b>", "/my"],
    ["Admin <b>dashboard</b>", "/admin"],
    ["catalist<b>.world</b>", "https://catalist.world"],
  ];
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
  const here = location.pathname.replace(/\/+$/, "") || "/";
  ov.innerHTML = '<nav class="menu-panel" aria-label="Catalist sections">'
    + LINKS.map(([label, href], i) => {
        const current = href === here ? ' class="current" aria-current="page"' : "";
        return `<a href="${href}" style="--i:${i}"${current}>${label}</a>`;
      }).join("")
    + '<div class="menu-copy">© 2026 Catalist · Special edition</div></nav>';
  document.body.appendChild(ov);

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

/* Сертификат подлинности: оверлей предпросмотра + печать (window.print).
   Портирует Certificate/CertificateSheet из прототипа hallmarksuite.tsx:
   A5 — полноформатный лист; A7/A8 — «бирка», печатается на листе A4
   в реальном размере, пунктир — линия реза. Точный размер на бумаге
   даёт transform: scale(мм/px) в @media print.

   Использование: openCertificate("XXXXXXXX") на странице, где определён
   window.merchApi (fetch с PIN/сессией). Данные — GET /api/cert/<код>. */
"use strict";

const CERT_SHEETS = {
  a3: { page: "A3 portrait", margin: "18mm", width: 700, mmWidth: 265, tier: "large" },
  a4: { page: "A4 portrait", margin: "14mm", width: 620, mmWidth: 185, tier: "large" },
  a5: { page: "A5 portrait", margin: "10mm", width: 460, mmWidth: 130, tier: "medium" },
  a6: { page: "A6 portrait", margin: "6mm", width: 330, mmWidth: 95, tier: "small" },
  a7: { page: "A4 portrait", margin: "12mm", width: 300, mmWidth: 74, tier: "tag" },
  a8: { page: "A4 portrait", margin: "12mm", width: 300, mmWidth: 52, tier: "tag" },
};
// px макета → мм на бумаге (96 dpi: 1px = 25.4/96 мм)
const certPrintScale = (f) => CERT_SHEETS[f].mmWidth / (CERT_SHEETS[f].width / 96 * 25.4);

function certPlate(code, big) {
  const cells = [...(code || "········")]
    .map((ch) => `<div class="cp-cell${big ? " big" : ""}">${esc(ch)}</div>`).join("");
  return `<div class="cert-plate">${cells}</div>`;
}

function certSheetHtml(r, format) {
  const sheet = CERT_SHEETS[format] || CERT_SHEETS.a5;
  const seqStr = `№ ${String(r.seq).padStart(3, "0")}`;
  const editionStr = r.edition ? `<span class="of"> / ${esc(String(r.edition))}</span>` : "";
  const photo = r.img
    ? `<img src="${esc(r.img)}" alt="${esc(r.product)}">`
    : `<span class="cert-nophoto">no photo</span>`;
  const signs = `
    <div class="cert-signs">
      <img class="sig1" src="/static/img/sign1.png" alt="">
      <img class="sig2" src="/static/img/sign2.png" alt="">
    </div>`;

  if (sheet.tier === "tag") {
    // A7/A8: бирка — всё по центру, фото и QR рядом; внешний пунктир = линия реза
    return `
    <div id="cert-print" class="cert-sheet tag ${format}">
      <div class="cert-frame">
        <img class="cert-logo" src="/static/img/logo-cert.png" alt="Catalist">
        <div class="cert-eyebrow">Special edition</div>
        <div class="cert-title">Certificate of Authenticity</div>
        <div class="cert-rule"></div>
        <div class="cert-product">${esc(r.product)}</div>
        <div class="cert-seq">${seqStr}${editionStr}</div>
        ${certPlate(r.code)}
        <div class="cert-media">
          <div class="cert-photo">${photo}</div>
          <div class="cert-qr">${r.qrSvg}</div>
        </div>
        <div class="cert-caption">Scan the code and enter this number to confirm the piece is genuine.</div>
        ${signs}
      </div>
    </div>`;
  }

  const big = sheet.tier === "large";
  // A5 (и крупнее): двойная рамка, угловые засечки, фото над названием,
  // QR с подписью в строку, две подписи внизу
  return `
  <div id="cert-print" class="cert-sheet ${big ? "large" : "medium"} ${format}">
    <div class="cert-outer">
      <div class="cert-frame">
        <span class="tick tl"></span><span class="tick tr"></span>
        <span class="tick bl"></span><span class="tick br"></span>
        <img class="cert-logo" src="/static/img/logo-cert.png" alt="Catalist">
        <div class="cert-eyebrow"><span class="line"></span>Special edition<span class="line"></span></div>
        <div class="cert-title">Certificate of Authenticity</div>
        <div class="cert-photo">${photo}</div>
        <div class="cert-product">${esc(r.product)}</div>
        <div class="cert-seq">${seqStr}${editionStr}</div>
        <div class="cert-label">Serial number</div>
        ${certPlate(r.code, big)}
        <div class="cert-media">
          <div class="cert-qr">${r.qrSvg}</div>
          <div class="cert-caption">Scan the code and enter the serial number to confirm the piece is genuine.</div>
        </div>
        ${signs}
      </div>
    </div>
  </div>`;
}

// Размеры страницы печати, мм (бирки A7/A8 печатаются на листе A4)
const CERT_PAGES = { a3: [297, 420], a4: [210, 297], a5: [148, 210],
                     a6: [105, 148], a7: [210, 297], a8: [210, 297] };
const MM_PER_PX = 25.4 / 96;

function certPrintCss(format, sheetHeightPx) {
  const sheet = CERT_SHEETS[format];
  const margin = parseFloat(sheet.margin);
  const printableW = CERT_PAGES[format][0] - 2 * margin;
  const printableH = CERT_PAGES[format][1] - 2 * margin;
  // целевой масштаб — точная ширина в мм (для бирок это истинный размер A7/A8);
  // затем прижимаем к печатной области, чтобы лист не разъезжался на 2 страницы
  // 0.98 — запас на округление принтера: лист ровно в печатную область
  // упирается в порог и Chromium выносит нижнюю кромку на вторую страницу
  let ps = certPrintScale(format);
  if (sheet.width * MM_PER_PX * ps > printableW) ps = 0.98 * printableW / (sheet.width * MM_PER_PX);
  if (sheetHeightPx && sheetHeightPx * MM_PER_PX * ps > printableH) {
    ps = 0.98 * printableH / (sheetHeightPx * MM_PER_PX);
  }
  return `
    @page { size: ${sheet.page}; margin: ${sheet.margin}; }
    @media print {
      html, body { background: #fff !important; margin: 0 !important; }
      body > * { display: none !important; }
      body > #cert-overlay {
        display: block !important; position: static !important; padding: 0 !important;
        background: #fff !important; -webkit-backdrop-filter: none !important; backdrop-filter: none !important;
        overflow: visible !important;
      }
      #cert-overlay .cert-box { max-width: none !important; margin: 0 !important; }
      #cert-overlay .btn, #cert-overlay .cert-note { display: none !important; }
      #cert-overlay .cert-viewport { height: auto !important; width: auto !important; overflow: visible !important; }
      #cert-scale {
        position: absolute !important; left: 0 !important; top: 0 !important; margin: 0 !important;
        /* zoom, а не transform: scale не меняет layout-высоту, и Chromium
           разбивает «непоместившийся» лист на две страницы */
        zoom: ${ps} !important; transform: none !important;
      }
      .cert-sheet, .cert-sheet * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    }`;
}

async function openCertificate(code) {
  const apiFn = window.merchApi || ((p) => fetch(p).then((x) => x.json()).catch(() => ({ ok: false })));
  const r = await apiFn(`/api/cert/${encodeURIComponent(code)}`);
  if (!r || !r.ok) {
    alert((r && r.error) || "Failed to load the certificate data");
    return;
  }
  const format = CERT_SHEETS[r.sheet] ? r.sheet : "a5";
  const sheet = CERT_SHEETS[format];

  const prev = document.getElementById("cert-overlay");
  if (prev) prev.remove();
  const prevStyle = document.getElementById("cert-print-style");
  if (prevStyle) prevStyle.remove();

  // @page и масштаб печати зависят от формата и фактической высоты листа —
  // стиль ставится сейчас и уточняется в fit() после загрузки фото
  const style = document.createElement("style");
  style.id = "cert-print-style";
  style.textContent = certPrintCss(format, 0);
  document.head.appendChild(style);

  const ov = document.createElement("div");
  ov.className = "cert-overlay";
  ov.id = "cert-overlay";
  ov.innerHTML = `
    <div class="cert-box">
      <div class="cert-viewport"><div id="cert-scale">${certSheetHtml(r, format)}</div></div>
      <button type="button" class="btn cert-do-print">Print certificate</button>
      <button type="button" class="btn ghost cert-close">Back</button>
      <div class="cert-note">Paper: ${format.toUpperCase()}${sheet.tier === "tag" ? " tag on an A4 sheet — cut along the dashed line" : ""}.</div>
    </div>`;
  document.body.appendChild(ov);
  document.documentElement.classList.add("menu-lock");

  // предпросмотр: вписываем лист (фиксированная px-ширина) в экран
  const scaleBox = ov.querySelector("#cert-scale");
  const viewport = ov.querySelector(".cert-viewport");
  function fit() {
    const w = Math.min(560, ov.clientWidth - 28);
    const k = Math.min(1, w / sheet.width);
    scaleBox.style.width = sheet.width + "px";
    scaleBox.style.transform = `scale(${k})`;
    scaleBox.style.transformOrigin = "top left";
    viewport.style.height = scaleBox.offsetHeight * k + "px";
    viewport.style.width = sheet.width * k + "px";
    // фактическая высота листа известна — уточняем масштаб печати
    style.textContent = certPrintCss(format, scaleBox.offsetHeight);
  }
  fit();
  const onResize = () => fit();
  window.addEventListener("resize", onResize);
  // фото/шрифты могли доехать позже — пересчитать высоту
  ov.querySelectorAll("img").forEach((im) => im.addEventListener("load", fit));

  function close() {
    window.removeEventListener("resize", onResize);
    ov.remove();
    style.remove();
    document.documentElement.classList.remove("menu-lock");
  }
  ov.querySelector(".cert-close").onclick = close;
  ov.addEventListener("click", (e) => { if (e.target === ov) close(); });
  document.addEventListener("keydown", function onEsc(e) {
    if (e.key === "Escape") { close(); document.removeEventListener("keydown", onEsc); }
  });
  ov.querySelector(".cert-do-print").onclick = () => window.print();
}
window.openCertificate = openCertificate;

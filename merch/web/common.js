/* Общие помощники публичной страницы (app.js) и дашборда (admin.js).
   Подключается перед ними; правки формата номера/дат делаются здесь один раз. */
"use strict";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const BASE_YEAR = 2026;
const monthLabel = (m) => `${MONTHS[m % 12]} ${BASE_YEAR + Math.floor(m / 12)}`;

// то же приведение ввода, что на сервере: I/L→1, O→0, U→V
const normalize = (raw) => String(raw || "").toUpperCase().replace(/[^0-9A-Z]/g, "")
  .replace(/I/g, "1").replace(/L/g, "1").replace(/O/g, "0").replace(/U/g, "V");

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
const fmtDate = (iso) => { const s = fmtTime(iso); return s === "—" ? s : s.slice(0, 10); };

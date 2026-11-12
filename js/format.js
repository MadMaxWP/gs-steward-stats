// dates, numbers and small browser helpers. all times are shown in utc

export const monthNames = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
export const shortMonths = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
export const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

export const p2 = n => String(n).padStart(2, '0');
export const fmtTs = iso => {
  if (!iso) return '';
  const d = new Date(iso);
  return p2(d.getUTCHours()) + ':' + p2(d.getUTCMinutes()) + ', ' + d.getUTCDate() + ' ' + monthNames[d.getUTCMonth()] + ' ' + d.getUTCFullYear();
};
export const fmtDay = iso => { const d = new Date(iso); return d.getUTCDate() + ' ' + monthNames[d.getUTCMonth()] + ' ' + d.getUTCFullYear(); };
export const fmtTime = iso => { const d = new Date(iso); return p2(d.getUTCHours()) + ':' + p2(d.getUTCMinutes()); };
export const fmtDate = iso => (iso ? iso.slice(0, 10) : '');
export const ymLong = s => { const [y, m] = s.split('-'); return shortMonths[Number(m) - 1] + ' ' + y; };
export const num = v => (v == null ? 0 : Number(v)).toLocaleString('en');
export const plural = (n, one, many) => num(n) + ' ' + (Number(n) === 1 ? one : (many || one + 's'));
export const compact = v => v >= 1e6 ? (v / 1e6).toFixed(v >= 1e7 ? 0 : 1).replace(/\.0$/, '') + 'M'
  : v >= 1e3 ? (v / 1e3).toFixed(v >= 1e4 ? 0 : 1).replace(/\.0$/, '') + 'k' : String(v);

export const ago = iso => {
  if (!iso) return 'never';
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return 'just now';
  const m = s / 60; if (m < 60) return Math.floor(m) + ' min ago';
  const h = m / 60; if (h < 24) return Math.floor(h) + ' h ago';
  const d = h / 24; if (d < 60) return Math.floor(d) + ' d ago';
  if (d < 730) return Math.floor(d / 30) + ' mo ago';
  return Math.floor(d / 365) + ' y ago';
};

export const monthsAgo = n => { const t = new Date(); t.setUTCMonth(t.getUTCMonth() - n); return t; };
export const today = () => new Date().toISOString().slice(0, 10);
export const daysAgo = n => new Date(Date.now() - n * 86400000).toISOString().slice(0, 10);

// sql only returns months that had actions. this puts the empty ones back, so the
// bars line up with real months. ym values look like 202411
const ymOf = d => d.getUTCFullYear() * 100 + d.getUTCMonth() + 1;
export function fillMonths(rows, start, end) {
  const have = new Map(rows.map(r => [Number(r.ym), Number(r.c || 0)]));
  if (!start) start = rows.length ? Number(rows[0].ym) : null;
  if (!start) return [];
  if (!end) end = ymOf(new Date());
  const out = [];
  let y = Math.floor(start / 100), m = start % 100;
  while (y * 100 + m <= end && out.length < 600) {
    out.push({ label: y + '-' + p2(m), v: have.get(y * 100 + m) || 0 });
    if (++m > 12) { m = 1; y++; }
  }
  return out;
}
export const ymFromDate = s => Number(s.slice(0, 4)) * 100 + Number(s.slice(5, 7));
export const ymMonthsBack = n => { const d = new Date(); d.setUTCDate(1); d.setUTCMonth(d.getUTCMonth() - n); return ymOf(d); };

export const downloadText = (name, text) => {
  const u = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = u; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(u), 1000);
};
export const csvCell = v => '"' + String(v == null ? '' : v).replace(/"/g, '""') + '"';
export const csvText = (head, rows) => '﻿' + [head.join(',')].concat(rows.map(r => r.map(csvCell).join(','))).join('\n');

// localStorage can throw (private mode, blocked storage), so it's always wrapped
export const lsGet = (k, d) => { try { return localStorage.getItem(k) || d; } catch (e) { return d; } };
export const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} };
export const lsJson = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) || d; } catch (e) { return d; } };

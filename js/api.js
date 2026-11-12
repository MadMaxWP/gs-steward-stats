// fetch wrapper with a small per tab cache. answers are kept 4 minutes in
// sessionStorage, so a reload is instant. refresh=1 skips the cache.
// the live feed and login info are never cached

const ttl = 4 * 60 * 1000;
const prefix = 'gs-c:';
const noCache = ['live', 'meta', 'me', 'people'];
const mem = new Map();

const keyFor = (path, q) => prefix + path + '?' + [...q.entries()].filter(([k]) => k !== 'refresh').sort().map(([k, v]) => k + '=' + v).join('&');

function cacheGet(key) {
  let raw = mem.get(key);
  if (!raw) { try { raw = sessionStorage.getItem(key); } catch (e) {} }
  if (!raw) return null;
  const i = raw.indexOf('|');
  if (i > 0 && Date.now() - Number(raw.slice(0, i)) < ttl) {
    try { return JSON.parse(raw.slice(i + 1)); } catch (e) {}
  }
  mem.delete(key);
  try { sessionStorage.removeItem(key); } catch (e) {}
  return null;
}

function cachePut(key, d) {
  const raw = Date.now() + '|' + JSON.stringify(d);
  mem.set(key, raw);
  if (mem.size > 60) mem.delete(mem.keys().next().value);
  try { sessionStorage.setItem(key, raw); } catch (e) {
    // storage full, clear our old entries and try once more
    try {
      for (const k of Object.keys(sessionStorage)) if (k.startsWith(prefix)) sessionStorage.removeItem(k);
      sessionStorage.setItem(key, raw);
    } catch (e2) {}
  }
}

// drop expired entries left over from earlier visits
try {
  for (const k of Object.keys(sessionStorage)) {
    if (!k.startsWith(prefix)) continue;
    const raw = sessionStorage.getItem(k) || '', i = raw.indexOf('|');
    if (i < 1 || Date.now() - Number(raw.slice(0, i)) >= ttl) sessionStorage.removeItem(k);
  }
} catch (e) {}

export function apiUrl(path, params) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) if (v !== '' && v != null) q.set(k, v);
  return 'api/' + path + (q.toString() ? '?' + q.toString() : '');
}

export async function api(path, params) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) if (v !== '' && v != null) q.set(k, v);
  const useCache = !noCache.includes(path);
  const key = keyFor(path, q);
  if (useCache && q.get('refresh') !== '1') { const hit = cacheGet(key); if (hit) return hit; }
  const r = await fetch('api/' + path + (q.toString() ? '?' + q.toString() : ''), { cache: 'no-store' });
  // session ended, a reload lands on the login screen
  if (r.status === 401) { location.reload(); throw new Error('Login required'); }
  let d;
  try { d = await r.json(); } catch (e) { throw new Error('Bad response from server'); }
  if (!r.ok) throw new Error(d.error || 'Request failed');
  if (useCache) cachePut(key, d);
  return d;
}

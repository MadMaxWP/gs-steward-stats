// app wide state: who is logged in, meta data, the hash router and pinned users
import { reactive, ref, watch } from 'vue';
import { lsJson, lsSet } from './format.js';

export const store = reactive({ meta: null, me: null, error: '' });

// ticks every minute so "x min ago" labels keep moving while a page is open
export const tick = ref(Date.now());
setInterval(() => { tick.value = Date.now(); }, 60000);

// old page names that now live somewhere else
const moved = { auths: 'people', online: 'people' };

// routes look like #/user/Name?tab=activity
export function parseHash() {
  const old = location.hash.match(/^#\/?([^/?]+)/);
  if (old && moved[old[1]]) history.replaceState(null, '', '#/' + moved[old[1]]);
  const h = location.hash.replace(/^#\/?/, '');
  const [path, qs] = h.split('?');
  const parts = path.split('/').filter(Boolean).map(decodeURIComponent);
  return { name: parts[0] || 'home', arg: parts.slice(1).join('/'), query: Object.fromEntries(new URLSearchParams(qs || '')) };
}
export const route = ref(parseHash());
// bumped on real navigation only. pages are keyed on it, so following a link
// remounts the page, while setQuery below doesn't
export const navCount = ref(0);
window.addEventListener('hashchange', () => { route.value = parseHash(); navCount.value++; window.scrollTo(0, 0); });

// write filters into the url without navigating, so links can be shared and
// back/reload keep them. empty values are dropped
export function setQuery(changes) {
  const q = { ...route.value.query, ...changes };
  for (const k of Object.keys(q)) if (q[k] === '' || q[k] == null) delete q[k];
  const path = location.hash.replace(/^#\/?/, '').split('?')[0];
  const qs = new URLSearchParams(q).toString();
  history.replaceState(null, '', '#/' + path + (qs ? '?' + qs : ''));
  route.value = parseHash();
}

// pinned users live in this browser only
export const pins = ref(lsJson('gs-pins', []));
watch(pins, v => lsSet('gs-pins', JSON.stringify(v)), { deep: true });
export const isPinned = name => pins.value.includes(name);
export const togglePin = name => {
  pins.value = isPinned(name) ? pins.value.filter(n => n !== name) : [...pins.value, name].sort((a, b) => a.localeCompare(b));
};

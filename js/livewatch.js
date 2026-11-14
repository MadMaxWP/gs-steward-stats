// keeps an eye on the live feed from every page: counts new actions for the
// live feed tab, and plays the sound / shows the notification if they're ticked.
// the live feed page does its own alerts while it's open
import { ref } from 'vue';
import { api } from './api.js';
import { lsGet, lsJson, lsSet } from './format.js';
import { actionLabel, catOf } from './logs.js';
import { route } from './store.js';

export const unseen = ref(0);
// a codex toast inside the page, like mw.notify on the wikis. one at a time,
// a newer action replaces the one showing
export const toast = ref(null);
let toastId = 0;
export const dropToast = () => { toast.value = null; };

// a short two note chime, made in the browser with web audio
let audio = null;
export function startAudio() {
  if (!audio) { try { audio = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) {} }
  if (audio && audio.state === 'suspended') audio.resume();
}
export function chime() {
  if (!audio) return;
  const t = audio.currentTime;
  [880, 1320].forEach((hz, i) => {
    const o = audio.createOscillator(), g = audio.createGain();
    o.frequency.value = hz;
    g.gain.setValueAtTime(0.0001, t + i * 0.15);
    g.gain.exponentialRampToValueAtTime(0.15, t + i * 0.15 + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t + i * 0.15 + 0.3);
    o.connect(g).connect(audio.destination);
    o.start(t + i * 0.15);
    o.stop(t + i * 0.15 + 0.32);
  });
}

// the filters on the live feed page, kept in the browser so other pages can use them
export const liveFilters = () => lsJson('gs-live-filters', { role: 'all', cat: 'all', q: '' });
export const matchesFilters = (i, f) => (f.role === 'all' || i.role === f.role) && (f.cat === 'all' || catOf(i) === f.cat)
  && (!f.q || (i.actor + ' ' + i.wiki + ' ' + i.domain + ' ' + i.title + ' ' + (i.comment || '')).toLowerCase().includes(f.q.toLowerCase()));

export function alertFor(found) {
  if (!found.length) return;
  // with the tool open in a few tabs, only the first one to see these makes a noise
  const newest = found.map(x => x.key).sort().pop();
  if (lsGet('gs-live-alerted', '') === newest) return;
  lsSet('gs-live-alerted', newest);
  const alerts = lsJson('gs-live-alerts', { sound: false, notify: false });
  if (alerts.sound) chime();
  if (!alerts.notify) return;
  const a = found[0];
  const title = found.length === 1 ? actionLabel(a) + ' by ' + a.actor : found.length + ' new actions';
  const body = found.length === 1 ? a.wiki + ': ' + a.title : found.map(x => actionLabel(x) + ' by ' + x.actor).slice(0, 4).join('\n');
  // looking at the tool: a notice in the page that goes away by itself.
  // tab in the background: a browser notification, if the browser allows it
  if (!document.hidden) {
    // the codex toast takes focus when it opens, give it back so typing isn't interrupted
    const was = document.activeElement;
    toast.value = { id: ++toastId, text: title + ' · ' + body.split('\n')[0] };
    setTimeout(() => { if (was && was !== document.body && was.focus) was.focus({ preventScroll: true }); }, 50);
    return;
  }
  if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
    try {
      const n = new Notification(title, { body, tag: 'gs-live' });
      n.onclick = () => { window.focus(); location.hash = '#/live'; n.close(); };
    } catch (e) {}
  }
}

// when the live feed page was last open, everything after that counts as new
export const markSeen = () => { lsSet('gs-live-seen', String(Date.now())); unseen.value = 0; };

let since = 0, started = false;
const known = new Set();

async function poll() {
  try {
    const d = await api('live', { since });
    const onLive = route.value.name === 'live';
    if (onLive) markSeen();
    const f = liveFilters();
    const seenAt = Number(lsGet('gs-live-seen', '0'));
    if (!onLive) {
      // count from the full list on the first answer, then just add the new ones
      const fresh = d.events.filter(e => !known.has(e.key) && e.recv > seenAt && matchesFilters(e, f));
      unseen.value = since === 0 ? fresh.length : unseen.value + fresh.length;
      if (since > 0) alertFor(fresh);
    }
    d.events.forEach(e => known.add(e.key));
    // a little overlap so nothing slips between two answers, the set drops repeats
    since = Math.max(0, d.now - 20000);
  } catch (e) {}
  setTimeout(poll, document.hidden ? 30000 : 15000);
}

export function startWatch() {
  if (started) return;
  started = true;
  if (lsJson('gs-live-alerts', { sound: false }).sound) {
    startAudio();
    // browsers keep audio muted until the first click on the page
    document.addEventListener('click', startAudio, { once: true });
  }
  poll();
}

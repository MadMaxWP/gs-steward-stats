// the login screen, shown for any page until someone logs in with their wikimedia account
import { createApp, ref, watch } from 'vue';
import { CdxButton, CdxIcon, CdxMessage, icons } from './codex.js';

const el = document.getElementById('app');
const cfg = { logo: el.dataset.logo, loginUrl: el.dataset.loginUrl, enabled: el.dataset.enabled === 'yes', source: el.dataset.source, commit: el.dataset.commit };

createApp({
  components: { CdxButton, CdxIcon, CdxMessage },
  setup() {
    const theme = ref(document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light');
    watch(theme, t => {
      document.documentElement.dataset.theme = t;
      document.getElementById('gs-dark').media = t === 'dark' ? 'all' : 'not all';
      try { localStorage.setItem('gs-theme', t); } catch (e) {}
    });
    const busy = ref(false);
    const login = () => { busy.value = true; location.href = cfg.loginUrl; };
    return { theme, busy, login, icons, cfg };
  },
  template: `
<div class="shell">
  <header class="hdr"><div class="hdr-in">
    <span class="brand"><img :src="cfg.logo" alt="">#gs-steward-stats</span>
    <div class="themesw"><cdx-button weight="quiet" :aria-label="theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'" @click="theme = theme === 'dark' ? 'light' : 'dark'"><cdx-icon :icon="theme === 'dark' ? icons.sun : icons.moon"/></cdx-button></div>
  </div></header>
  <main>
    <div class="hero">
      <img :src="cfg.logo" alt="">
      <h1>#gs-steward-stats</h1>
      <p>Log in with your Wikimedia account to continue.</p>
      <cdx-button v-if="cfg.enabled" action="progressive" weight="primary" size="large" :disabled="busy" @click="login"><cdx-icon :icon="icons.logIn"/> Log in</cdx-button>
      <cdx-message v-else type="error" :allow-user-dismiss="false">Login is not configured yet.</cdx-message>
    </div>
  </main>
  <footer class="footer">
    <p>Brought to you by <a href="https://meta.wikimedia.org/wiki/User:Max">Max</a></p>
    <p>Powered by <a href="https://wikitech.wikimedia.org/wiki/Portal:Toolforge">Toolforge</a> &middot; <a href="https://meta.wikimedia.org/wiki/User_talk:Max">Report an issue</a></p>
    <p><a :href="cfg.source">Source</a><template v-if="cfg.commit"> (<a class="mono" :href="cfg.source + '/commit/' + cfg.commit">{{ cfg.commit.slice(0, 7) }}</a>)</template></p>
  </footer>
</div>`
}).mount('#app');

// app shell: header, router and footer. pages live in ./pages
import { computed, createApp, onMounted, ref, watch } from 'vue';
import { api } from './api.js';
import { CdxButton, CdxIcon, CdxInfoChip, CdxProgressIndicator, CdxTooltip, icons } from './codex.js';
import { lsSet } from './format.js';
import { navCount, route, store } from './store.js';
import { GsTag, StaleBanner, SyncNote } from './components/common.js';
import { AboutPage } from './pages/about.js';
import { ExplorerPage } from './pages/explorer.js';
import { HomePage } from './pages/home.js';
import { LivePage } from './pages/live.js';
import { PeoplePage } from './pages/people.js';
import { YearPage } from './pages/year.js';
import { ProjectPage, ProjectsPage } from './pages/projects.js';
import { UserPage } from './pages/user.js';
import { UsersPage } from './pages/users.js';

// back to the page that was asked for before the login screen
try {
  const h = sessionStorage.getItem('gs-after-login');
  if (h) { sessionStorage.removeItem('gs-after-login'); if (!location.hash || location.hash === '#/') location.hash = h; }
} catch (e) {}

async function loadMe() {
  try { store.me = await api('me'); }
  catch (e) { store.me = { username: null, login_enabled: false }; }
}
// while the tab is visible, check in now and then so the people page stays right
setInterval(() => { if (document.visibilityState === 'visible') loadMe(); }, 2 * 60 * 1000);

async function loadMeta() {
  try { store.meta = await api('meta'); }
  catch (e) { store.error = e.message; }
}

// pages that read from the synced database, these get the stale data warning
const dataPages = ['home', 'users', 'user', 'explorer', 'projects', 'project', 'year'];

const App = {
  components: { HomePage, UsersPage, UserPage, ExplorerPage, ProjectsPage, ProjectPage, LivePage, PeoplePage, YearPage, AboutPage, StaleBanner, CdxIcon, CdxButton },
  setup() {
    onMounted(() => { loadMeta(); loadMe(); });
    // pick up a newer sync time when moving to another page
    watch(() => route.value.name + '/' + route.value.arg, () => loadMeta());
    watch(() => route.value.name, n => { if (!['user', 'project'].includes(n)) document.title = '#gs-steward-stats'; });

    const nav = computed(() => [
      ['home', 'Overview', icons.home], ['users', 'Users', icons.group], ['explorer', 'Explorer', icons.search],
      ['projects', 'Projects', icons.globe], ['live', 'Live feed', icons.live],
      ['people', 'People', icons.group], ['about', 'About', icons.info]
    ]);
    const current = computed(() => ({ user: 'users', project: 'projects', year: 'home' })[route.value.name] || route.value.name);
    const showStale = computed(() => dataPages.includes(route.value.name));
    // stewards and global sysops get a link to their own page from the header
    const myPage = computed(() => {
      const me = store.me && store.me.username;
      const members = (store.meta && store.meta.users) || [];
      return me && members.some(u => u.name === me) ? '#/user/' + encodeURIComponent(me) : '';
    });

    const theme = ref(document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light');
    watch(theme, t => {
      document.documentElement.dataset.theme = t;
      const l = document.getElementById('gs-dark');
      if (l) l.media = t === 'dark' ? 'all' : 'not all';
      lsSet('gs-theme', t);
    });
    const toggleTheme = () => { theme.value = theme.value === 'dark' ? 'light' : 'dark'; };
    const logo = document.getElementById('app').dataset.logo;
    return { route, navCount, nav, current, showStale, myPage, store, theme, toggleTheme, icons, logo };
  },
  template: `
<div class="shell">
  <header class="hdr"><div class="hdr-in">
    <a class="brand" href="#/"><img :src="logo" alt="">#gs-steward-stats</a>
    <nav class="nav"><a v-for="n in nav" :key="n[0]" :href="'#/' + (n[0] === 'home' ? '' : n[0])" :class="{ on: current === n[0] }"><cdx-icon :icon="n[2]" size="small"/>{{ n[1] }}</a></nav>
    <div class="acct" v-if="store.me && store.me.username">
      <a v-if="myPage" class="who" :href="myPage" v-tooltip="'Your page'"><cdx-icon :icon="icons.user" size="small"/>{{ store.me.username }}</a>
      <span v-else class="who" v-tooltip="'Logged in as ' + store.me.username"><cdx-icon :icon="icons.user" size="small"/>{{ store.me.username }}</span>
      <a class="cdx-button cdx-button--fake-button cdx-button--fake-button--enabled cdx-button--weight-quiet cdx-button--size-medium" href="logout"><cdx-icon :icon="icons.logOut"/> Log out</a>
    </div>
    <div class="themesw"><cdx-button weight="quiet" :aria-label="theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'" v-tooltip="theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'" @click="toggleTheme"><cdx-icon :icon="theme === 'dark' ? icons.sun : icons.moon"/></cdx-button></div>
  </div></header>
  <main>
    <stale-banner v-if="showStale"/>
    <home-page v-if="route.name === 'home'" :key="'home' + navCount"/>
    <users-page v-else-if="route.name === 'users'" :key="'users' + navCount"/>
    <user-page v-else-if="route.name === 'user'" :name="route.arg" :key="'user' + navCount"/>
    <explorer-page v-else-if="route.name === 'explorer'" :key="'explorer' + navCount"/>
    <projects-page v-else-if="route.name === 'projects'" :key="'projects' + navCount"/>
    <project-page v-else-if="route.name === 'project'" :name="route.arg" :key="'project' + navCount"/>
    <live-page v-else-if="route.name === 'live'"/>
    <people-page v-else-if="route.name === 'people'"/>
    <year-page v-else-if="route.name === 'year'" :key="'year' + navCount"/>
    <about-page v-else-if="route.name === 'about'"/>
    <div v-else class="empty">Page not found.</div>
  </main>
  <footer class="footer">
    <p>Brought to you by <a href="https://meta.wikimedia.org/wiki/User:Max">Max</a></p>
    <p>Powered by <a href="https://wikitech.wikimedia.org/wiki/Portal:Toolforge">Toolforge</a> &middot; <a href="https://meta.wikimedia.org/wiki/User_talk:Max">Report an issue</a></p>
  </footer>
</div>`
};

const app = createApp(App);
app.component('GsTag', GsTag);
app.component('SyncNote', SyncNote);
app.component('CdxInfoChip', CdxInfoChip);
app.component('CdxProgressIndicator', CdxProgressIndicator);
app.directive('tooltip', CdxTooltip);
app.mount('#app');

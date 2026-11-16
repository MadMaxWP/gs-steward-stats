import { computed, onMounted, ref, watch } from 'vue';
import { api } from '../api.js';
import { CdxIcon, CdxMessage, CdxSelect, CdxTable, CdxTextInput, icons } from '../codex.js';
import { ago, fillMonths, fmtTs, num, plural } from '../format.js';
import { actionLabel, roleName, wikiLink } from '../logs.js';
import { route, setQuery } from '../store.js';
import { sortRows } from './users.js';
import { ActionExplorer } from '../components/actions.js';
import { BarChart, RankBars } from '../components/charts.js';
import { CacheBar, StatCard } from '../components/common.js';

export const ProjectsPage = {
  components: { CdxTextInput, CdxSelect, CdxMessage, CdxTable, CacheBar },
  setup() {
    const q0 = route.value.query;
    const cols = [{ id: 'dbname', label: 'Project' }, { id: 'total', label: 'Actions', textAlign: 'number' }, { id: 'users', label: 'Users', textAlign: 'number' }, { id: 'last_ts', label: 'Last action' }];
    const d = ref(null), err = ref(''), at = ref(''), busy = ref(false);
    const q = ref(q0.q || ''), show = ref(q0.show || 'all'), order = ref(q0.order || 'total');
    async function load(fresh) {
      busy.value = true;
      try { const r = await api('projects', { refresh: fresh ? '1' : '' }); d.value = r.rows; at.value = r.cached_at; err.value = ''; }
      catch (e) { err.value = e.message; }
      finally { busy.value = false; }
    }
    onMounted(() => load(false));
    watch([q, show, order], () => setQuery({ q: q.value, show: show.value === 'all' ? '' : show.value, order: order.value === 'total' ? '' : order.value }));
    const showItems = [{ value: 'all', label: 'All projects' }, { value: 'active', label: 'With actions' }, { value: 'none', label: 'No actions yet' }, { value: 'locked', label: 'Closed/Locked projects' }];
    const orderItems = [{ value: 'total', label: 'Most actions' }, { value: 'users', label: 'Most users' }, { value: 'last', label: 'Most recent' }, { value: 'name', label: 'Name' }];
    const rows = computed(() => {
      if (!d.value) return [];
      const t = q.value.toLowerCase();
      return d.value
        .filter(w => (!t || w.dbname.includes(t) || (w.domain || '').includes(t))
          && (show.value === 'all' || (show.value === 'active' && w.total > 0) || (show.value === 'none' && w.total === 0) || (show.value === 'locked' && w.is_locked)))
        .sort((a, b) => (order.value === 'name' ? a.dbname.localeCompare(b.dbname) : order.value === 'users' ? b.users - a.users
          : order.value === 'last' ? (b.last_ts || '').localeCompare(a.last_ts || '') : b.total - a.total));
    });
    return { cols, d, err, q, show, order, showItems, orderItems, rows, at, busy, load, icons, num, ago };
  },
  template: `
<div>
  <div class="pagehead"><h1>Projects</h1><p class="sub">Global sysop projects, with the recorded activity of stewards and global sysops.<sync-note/></p></div>
  <cdx-message v-if="err" type="error">{{ err }}</cdx-message>
  <div v-if="!d && !err" class="loading"><cdx-progress-indicator>Loading</cdx-progress-indicator> Loading</div>
  <section class="panel" v-if="d">
    <cache-bar :at="at" :busy="busy" @refresh="load(true)"/>
    <div class="toolbar">
      <div class="grp"><cdx-text-input v-model="q" clearable :start-icon="icons.search" placeholder="Filter by name or domain"/><cdx-select v-model:selected="show" :menu-items="showItems"/><cdx-select v-model:selected="order" :menu-items="orderItems"/></div>
      <span class="muted">{{ rows.length }} projects</span>
    </div>
    <cdx-table caption="Projects" hide-caption :columns="cols" :data="rows">
      <template #item-dbname="{ row }"><span class="nw"><a class="mono" :href="'#/project/' + encodeURIComponent(row.dbname)">{{ row.dbname }}</a> <gs-tag v-if="row.is_locked" status="warning">Closed/Locked</gs-tag><gs-tag v-else-if="!row.is_gs" status="notice">Non-GS</gs-tag></span></template>
      <template #item-total="{ item }">{{ num(item) }}</template>
      <template #item-users="{ item }">{{ num(item) }}</template>
      <template #item-last_ts="{ item }"><span class="muted nw">{{ ago(item) }}</span></template>
      <template #empty-state>No projects match.</template>
    </cdx-table>
  </section>
</div>`
};

const day = 86400000;

// local admins of one wiki, read from its replica when the page opens
export const LocalAdmins = {
  props: { wiki: String, domain: String, gs30: Number, gs90: Number },
  components: { CdxMessage, CdxSelect, CdxTable, CacheBar, StatCard, RankBars },
  setup(p) {
    const d = ref(null), err = ref(''), busy = ref(false);
    const show = ref('all'), sort = ref({ last_seen: 'desc' });
    async function load(fresh) {
      busy.value = true; err.value = '';
      try { d.value = await api('project/' + encodeURIComponent(p.wiki) + '/admins', { refresh: fresh ? '1' : '' }); }
      catch (e) { err.value = e.message; }
      finally { busy.value = false; }
    }
    onMounted(() => load(false));
    const since = iso => (iso ? (Date.now() - new Date(iso)) / day : Infinity);
    const status = a => {
      const n = since(a.last_seen);
      // same levels as the rest of the tool
      if (a.filter && !a.bot) return { s: '', t: '', k: 'filter' };
      if (n === Infinity) return { s: 'notice', t: 'Never active', k: 'never' };
      if (n <= 30) return { s: 'success', t: 'Active', k: 'active' };
      if (n <= 60) return { s: 'notice', t: 'Moderate', k: 'moderate' };
      if (n <= 182) return { s: 'warning', t: 'Low activity', k: 'semi' };
      return { s: 'error', t: 'Inactive', k: 'inactive' };
    };
    const showItems = [
      { value: 'all', label: 'All admins' }, { value: '7', label: 'Active in the last 7 days' },
      { value: 'active', label: 'Active' }, { value: 'moderate', label: 'Moderate' }, { value: 'semi', label: 'Low activity' },
      { value: 'inactive', label: 'Inactive' }, { value: 'team', label: 'Also steward or global sysop' }
    ];
    const rows = computed(() => {
      if (!d.value) return [];
      const f = show.value;
      const list = d.value.admins.filter(a => {
        const k = status(a).k;
        return f === 'all' || (f === '7' && since(a.last_seen) <= 7) || (f === 'team' && a.role)
          || f === k || (f === 'inactive' && k === 'never');
      });
      return sortRows(list, sort.value);
    });
    const cols = [
      { id: 'name', label: 'Admin', allowSort: true }, { id: 'groups', label: 'Also' },
      { id: 'last_seen', label: 'Last active', allowSort: true }, { id: 'last_admin', label: 'Last admin action', allowSort: true },
      { id: 'edits30', label: 'Edits (30 d)', textAlign: 'number', allowSort: true }, { id: 'admin30', label: 'Admin actions (30 d)', textAlign: 'number', allowSort: true },
      { id: 'status', label: 'Status' }
    ];
    const share = computed(() => (d.value ? [
      { label: 'Local admins', value: d.value.summary.admin90 },
      { label: 'Stewards and global sysops', value: p.gs90 || 0 }
    ] : []));
    // hover text on the local admins card, only when the wiki has a bot or abuse filter account
    const extras = computed(() => {
      if (!d.value) return '';
      const s = d.value.summary;
      const one = (n, what) => (n === 1 ? what : num(n) + ' ' + what);
      if (s.bots && s.filter) {
        return one(s.bots, s.bots === 1 ? 'Admin bot' : 'admin bot accounts') + ' and ' + one(s.filter, s.filter === 1 ? 'abuse filter account' : 'abuse filter accounts') + ' are left out.';
      }
      if (s.bots) return s.bots === 1 ? 'Admin bot account is left out.' : num(s.bots) + ' admin bot accounts are left out.';
      if (s.filter) return s.filter === 1 ? 'Abuse filter account is left out.' : num(s.filter) + ' abuse filter accounts are left out.';
      return '';
    });
    const adminLine = computed(() => {
      if (!d.value) return '';
      const s = d.value.summary;
      if (!s.admins) return 'This wiki has no local admins.';
      const who = s.admins === 1 ? (s.logged60 ? 'with a' : 'with no')
        : (!s.logged60 ? 'none with a' : s.logged60 === s.admins ? 'all with a' : num(s.logged60) + ' with a');
      return plural(s.admins, 'local admin') + ', ' + who + ' logged action in the last 2 months.';
    });
    const userLink = n => 'https://' + p.domain + '/wiki/User:' + encodeURIComponent(n.replace(/ /g, '_'));
    const caLink = n => 'https://meta.wikimedia.org/wiki/Special:CentralAuth/' + encodeURIComponent(n);
    return { d, err, busy, load, show, showItems, sort, rows, cols, share, status, extras, adminLine, userLink, caLink, ago, num, plural, icons };
  },
  template: `
<section class="panel">
  <h2>Local admins</h2>
  <cdx-message v-if="err" type="error">{{ err }}</cdx-message>
  <div v-else-if="!d" class="loading"><cdx-progress-indicator>Loading</cdx-progress-indicator> Checking the admins on {{ wiki }}</div>
  <template v-else>
    <cache-bar :at="d.cached_at" :busy="busy" @refresh="load(true)"/>
    <div class="stats">
      <stat-card label="Local admins" :value="num(d.summary.admins)" :icon="icons.group" v-tooltip="extras || null"/>
      <stat-card label="Active in the last 7 days" :value="num(d.summary.active7)" :icon="icons.userActive" :hint="num(d.summary.active30) + ' in 30 days, ' + num(d.summary.active90) + ' in 90 days'"/>
      <stat-card label="Admin actions by locals (30 d)" :value="num(d.summary.admin30)" :icon="icons.check" :hint="'stewards and global sysops: ' + num(gs30)"/>
      <stat-card v-if="d.summary.edits30 != null" label="Edits on the wiki (30 d)" :value="num(d.summary.edits30)" :icon="icons.contrib" :hint="'by ' + plural(d.summary.editors30, 'editor') + ', bots left out'"/>
    </div>
    <cdx-message type="notice" :allow-user-dismiss="false">
      {{ adminLine }}
    </cdx-message>
    <h3 class="mt">Who did the admin work here in the last 90 days</h3>
    <rank-bars :items="share" share/>
    <div class="toolbar mt"><div class="grp"><cdx-select v-model:selected="show" :menu-items="showItems"/></div><span class="muted">{{ rows.length }} of {{ plural(d.admins.length, 'admin') }}</span></div>
    <div v-if="!d.admins.length" class="empty">This wiki has no local admins.</div>
    <div v-else-if="!rows.length" class="empty">No admins match.</div>
    <cdx-table v-else caption="Local admins" hide-caption :columns="cols" :data="rows" v-model:sort="sort">
      <template #item-name="{ row }"><span class="nw"><a :href="userLink(row.name)" target="_blank" rel="noopener"><b>{{ row.name }}</b></a> <a class="ca" :href="caLink(row.name)" target="_blank" rel="noopener" title="CentralAuth">CA</a></span></template>
      <template #item-groups="{ row }"><span class="tags"><role-tag v-if="row.role" :role="row.role"/><gs-tag v-if="row.filter && !row.bot">abuse filter account</gs-tag><gs-tag v-for="g in row.groups" :key="g">{{ g }}</gs-tag></span></template>
      <template #item-last_seen="{ row }"><span class="nw" :title="row.last_edit ? 'Last edit ' + ago(row.last_edit) : ''">{{ row.last_seen ? ago(row.last_seen) : 'never' }}</span></template>
      <template #item-last_admin="{ item }"><span class="nw">{{ item ? ago(item) : 'none' }}</span></template>
      <template #item-edits30="{ item }">{{ num(item) }}</template>
      <template #item-admin30="{ item }">{{ num(item) }}</template>
      <template #item-status="{ row }"><gs-tag v-if="status(row).t" :status="status(row).s">{{ status(row).t }}</gs-tag></template>
    </cdx-table>
  </template>
</section>`
};

// one wiki: who acts there, what they do, and when
export const ProjectPage = {
  props: { name: String },
  components: { ActionExplorer, StatCard, BarChart, RankBars, CdxIcon, CdxMessage, CacheBar, LocalAdmins },
  setup(p) {
    const query = route.value.query;
    const d = ref(null), err = ref(''), busy = ref(false);
    async function load(fresh) {
      busy.value = true; err.value = '';
      try { d.value = await api('project/' + encodeURIComponent(p.name), { refresh: fresh ? '1' : '' }); document.title = p.name + ' - #gs-steward-stats'; }
      catch (e) { err.value = e.message; }
      finally { busy.value = false; }
    }
    onMounted(() => load(false));
    const people = computed(() => (d.value ? d.value.users.map(u => ({ label: u.actor, value: Number(u.n), href: '#/user/' + encodeURIComponent(u.actor) })) : []));
    const types = computed(() => {
      if (!d.value) return [];
      const m = new Map();
      for (const t of d.value.by_type) { const l = actionLabel(t); m.set(l, (m.get(l) || 0) + Number(t.n)); }
      return [...m.entries()].map(([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value);
    });
    const months = computed(() => (d.value ? fillMonths(d.value.monthly).slice(-36) : []));
    const site = computed(() => (d.value && d.value.domain ? wikiLink(d.value.domain, 'Special:Log') : ''));
    return { query, d, err, busy, load, people, types, months, site, roleName, icons, num, ago, fmtTs, plural };
  },
  template: `
<div>
  <cdx-message v-if="err" type="error">{{ err }} <a href="#/projects">Back to all projects</a></cdx-message>
  <div v-if="!d && !err" class="loading"><cdx-progress-indicator>Loading</cdx-progress-indicator> Loading</div>
  <template v-if="d">
    <p class="sub mb"><sync-note/></p>
    <cache-bar :at="d.cached_at" :busy="busy" @refresh="load(true)"/>
    <div class="uhead">
      <div class="av"><cdx-icon :icon="icons.globe" size="large"/></div>
      <div>
        <h1>{{ d.dbname }}</h1>
        <div class="links">
          <gs-tag v-if="d.is_locked" status="warning">Closed/Locked</gs-tag>
          <gs-tag v-else-if="!d.is_gs" status="notice">Non-GS</gs-tag>
          <span v-if="d.domain" class="muted">{{ d.domain }}</span>
          <a v-if="site" :href="site" target="_blank" rel="noopener">Logs on the wiki</a>
        </div>
      </div>
    </div>
    <div class="stats">
      <stat-card label="Actions" :value="num(d.summary.total)" :icon="icons.check" tone="ok" :hint="'by ' + plural(d.summary.users, 'current user')"/>
      <stat-card label="Last 30 days" :value="num(d.summary.c30)" :icon="icons.calendar" tone="info" :hint="num(d.summary.c90) + ' in 90 days, ' + num(d.summary.c365) + ' in a year'"/>
      <stat-card label="Last action" :value="ago(d.summary.last_ts)" :icon="icons.clock" tone="info" :hint="d.summary.last_ts ? fmtTs(d.summary.last_ts) : ''"/>
    </div>
    <div class="cols">
      <section class="panel"><h2>Who acts here</h2><rank-bars :items="people" ranked :limit="10"/></section>
      <section class="panel"><h2>Actions by type</h2><rank-bars :items="types" share :limit="8"/></section>
    </div>
    <local-admins v-if="d.domain" :wiki="d.dbname" :domain="d.domain" :gs30="Number(d.summary.c30)" :gs90="Number(d.summary.c90)"/>
    <section class="panel"><h2>Actions per month</h2><bar-chart :data="months"/></section>
    <section class="panel"><h2>Actions</h2><action-explorer :wiki="d.dbname" :initial="query" sync/></section>
  </template>
</div>`
};

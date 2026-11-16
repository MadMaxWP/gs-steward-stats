import { computed, onMounted, ref, watch } from 'vue';
import { api } from '../api.js';
import { CdxCheckbox, CdxIcon, CdxMessage, CdxSelect, CdxTab, CdxTable, CdxTabs, CdxTextInput, icons } from '../codex.js';
import { ago, fillMonths, fmtDate, fmtDay, fmtTs, monthsAgo, num, plural } from '../format.js';
import { actionLabel, activity, roleName } from '../logs.js';
import { route, setQuery, store } from '../store.js';
import { ActionExplorer, ActionList } from '../components/actions.js';
import { BarChart, Heatmap, RankBars } from '../components/charts.js';
import { CacheBar, Pager, PinButton, StatCard } from '../components/common.js';

// steward only tab. numbers come live from the meta replica, apart from the gs totals
const StewardPanel = {
  props: { name: String },
  components: { ActionList, Pager, StatCard, BarChart, RankBars, CdxSelect, CdxMessage, CdxCheckbox, CacheBar },
  setup(p) {
    const per = 50;
    const s = ref(null), err = ref(''), busy = ref(false);
    const cat = ref('all'), page = ref(1), rows = ref([]), total = ref(0), loading = ref(false), allTime = ref(false);
    const path = () => 'steward/' + encodeURIComponent(p.name);
    async function loadSummary(fresh) {
      busy.value = true;
      try { s.value = await api(path(), { refresh: fresh ? '1' : '', all: allTime.value ? '1' : '' }); err.value = ''; }
      catch (e) { err.value = e.message; }
      finally { busy.value = false; }
    }
    async function loadRows(fresh) {
      loading.value = true;
      try {
        const d = await api(path() + '/actions', { cat: cat.value, page: page.value, per, all: allTime.value ? '1' : '', refresh: fresh ? '1' : '' });
        rows.value = d.rows; total.value = d.total; err.value = '';
      } catch (e) { err.value = e.message; }
      finally { loading.value = false; }
    }
    const reload = async () => { await loadSummary(true); await loadRows(true); };
    onMounted(() => { loadSummary(false); loadRows(false); });
    watch(cat, () => { if (page.value === 1) loadRows(false); else page.value = 1; });
    watch(page, () => loadRows(false));
    watch(allTime, () => { page.value = 1; loadSummary(false); loadRows(false); });
    const pages = computed(() => Math.max(1, Math.ceil(total.value / per)));
    const catItems = computed(() => [{ value: 'all', label: 'All steward actions' }].concat(s.value ? s.value.by_cat.map(c => ({ value: c.cat, label: c.label + ' (' + num(c.n) + ')' })) : []));
    const months = computed(() => (s.value ? fillMonths(s.value.monthly).slice(-36) : []));
    const types = computed(() => (s.value ? s.value.by_cat.filter(c => c.n > 0).map(c => ({ label: c.label, value: c.n })) : []));
    return { s, err, busy, cat, page, rows, total, loading, allTime, pages, catItems, months, types, reload, icons, num, ago, fmtTs };
  },
  template: `
<div>
  <cdx-message v-if="err" type="error">{{ err }}</cdx-message>
  <div v-if="!s && !err" class="loading"><cdx-progress-indicator>Loading</cdx-progress-indicator> Loading</div>
  <template v-if="s">
    <cache-bar :at="s.cached_at" :busy="busy || loading" @refresh="reload"/>
    <cdx-message type="notice" :allow-user-dismiss="false">Steward actions are counted separately and are not part of the GS totals.</cdx-message>
    <div class="mt"><cdx-checkbox v-model="allTime">Count all actions, including those made before becoming a steward</cdx-checkbox></div>
    <div class="stats mt">
      <stat-card label="Steward actions" :value="num(s.total)" :icon="icons.check" tone="ok"/>
      <stat-card label="Last 30 days" :value="num(s.c30)" :icon="icons.calendar" tone="info" :hint="num(s.c90) + ' in 90 days, ' + num(s.c365) + ' in a year'"/>
      <stat-card label="Last steward action" :value="ago(s.last_ts)" :icon="icons.clock" tone="info" :hint="fmtTs(s.last_ts)"/>
    </div>
    <div class="cols">
      <section class="chartbox"><h2>By type</h2><rank-bars :items="types" share :limit="8"/></section>
      <section class="chartbox"><h2>Actions per month</h2><bar-chart :data="months" unit="steward actions"/></section>
    </div>
    <div class="toolbar mt"><div class="grp"><cdx-select v-model:selected="cat" :menu-items="catItems"/></div><span class="muted">{{ num(total) }} actions</span></div>
    <div v-if="loading && !rows.length" class="loading"><cdx-progress-indicator>Loading</cdx-progress-indicator> Loading</div>
    <action-list v-else :rows="rows" mode="log" :show-user="false"/>
    <pager v-model:page="page" :pages="pages" :total="total" :loading="loading"/>
    <section class="mt">
      <h2>Notes</h2>
      <ol class="muted small">
        <li>{{ allTime ? 'All actions are counted, including those made before the user became a steward, for example as a regular user or a local administrator.' : 'Only actions made while the user was a steward are counted. Tick the box above to include earlier actions.' }}</li>
        <li>Global blocks, global locks, global renames, global rights, rights changes and AbuseFilter edits come from the logs on Meta-Wiki. Rights changes include actions made with local Meta permissions such as administrator or bureaucrat.</li>
        <li>AbuseFilter edits include both global and local filters.</li>
        <li>SR page edits are edits on Steward requests pages and noticeboards.</li>
        <li>Hide and oversight actions and private AbuseFilter changes are not included.</li>
        <li>CheckUser actions are not stored here. See <a href="https://meta.wikimedia.org/wiki/Stewards/CheckUser_statistics_for_loginwiki" target="_blank" rel="noopener">CheckUser statistics for loginwiki</a>.</li>
        <li>Steward actions on other wikis are not included.</li>
      </ol>
    </section>
  </template>
</div>`
};

export const UserPage = {
  props: { name: String },
  components: { ActionExplorer, StewardPanel, StatCard, BarChart, Heatmap, RankBars, CdxTabs, CdxTab, CdxMessage, CdxTextInput, CdxSelect, CdxIcon, CdxTable, CacheBar, PinButton },
  setup(p) {
    const query = route.value.query;
    const d = ref(null), err = ref(''), busy = ref(false);
    const tab = ref(query.tab || 'actions');
    const wq = ref(''), wsort = ref('n');
    const per = ref(null), perErr = ref(''), perBusy = ref(false), pst = ref('all'), ptype = ref('all');

    async function load(fresh) {
      busy.value = true; err.value = '';
      try {
        d.value = await api('user/' + encodeURIComponent(p.name), { refresh: fresh ? '1' : '' });
        document.title = p.name + ' - #gs-steward-stats';
      } catch (e) { err.value = e.message; }
      finally { busy.value = false; }
    }
    async function loadPeriods(fresh) {
      perBusy.value = true; perErr.value = '';
      try { per.value = await api('user/' + encodeURIComponent(p.name) + '/periods', { refresh: fresh ? '1' : '' }); }
      catch (e) { perErr.value = e.message; }
      finally { perBusy.value = false; }
    }
    onMounted(() => { load(false); if (tab.value === 'membership') loadPeriods(false); });
    watch(tab, t => {
      setQuery({ tab: t === 'actions' ? '' : t });
      if (t === 'membership' && !per.value) loadPeriods(false);
    });

    const grpName = g => (g === 'steward' ? 'Steward' : g === 'global-sysop' ? 'Global sysop' : g);
    const pstItems = [{ value: 'all', label: 'Current and past' }, { value: 'current', label: 'Current only' }, { value: 'past', label: 'Past only' }];
    const ptypeItems = [{ value: 'all', label: 'All projects' }, { value: 'gs', label: 'GS projects' }, { value: 'nongs', label: 'Non-GS projects' }];
    // one row per period, laid out like the global groups table
    const localRows = computed(() => {
      if (!per.value) return [];
      const out = [];
      for (const r of per.value.local) {
        if (ptype.value !== 'all' && (ptype.value === 'gs') !== r.is_gs) continue;
        r.periods.forEach((x, i) => {
          const current = x.to === 'present';
          if (pst.value !== 'all' && (pst.value === 'current') !== current) return;
          out.push({ key: r.wiki + i, wiki: r.wiki, domain: r.domain, is_gs: r.is_gs, is_locked: r.is_locked, from: x.from, to: x.to, note: x.note, log: x.log, current });
        });
      }
      return out;
    });
    const localWikis = computed(() => new Set(localRows.value.map(r => r.wiki)).size);

    // the 6 month inactivity rule is for global sysops only
    const since = () => d.value.summary.last_ts || d.value.role_since || d.value.first_granted;
    const inactiveFrom = () => { const t = new Date(since()); t.setUTCMonth(t.getUTCMonth() + 6); return t; };
    const lastHint = computed(() => {
      const s = d.value && d.value.summary;
      if (!s || !s.last_ts) return '';
      let h = fmtTs(s.last_ts);
      if (d.value.role === 'global-sysop' && new Date(s.last_ts) < monthsAgo(4)) {
        const t = inactiveFrom();
        h += (t <= new Date() ? ' · inactive since ' : ' · inactive from ') + fmtDay(t.toISOString());
      }
      return h;
    });
    // only on your own page
    const myBox = computed(() => {
      if (!d.value || !store.me || store.me.username !== d.value.name) return null;
      const a = activity({ last_ts: d.value.summary.last_ts, role_since: d.value.role_since, first_granted: d.value.first_granted });
      const where = d.value.role === 'steward' ? ' on a GS wiki' : '';
      const last = d.value.summary.last_ts ? 'Last recorded action' + where + ' ' + ago(d.value.summary.last_ts) + '.'
        : 'No recorded actions' + (where ? ' on GS wikis' : '') + ' yet.';
      let note = '';
      if (d.value.role === 'global-sysop' && since()) {
        const day = fmtDay(inactiveFrom().toISOString());
        if (a.key === 'inactive') note = 'Inactive since ' + day + '.';
        else if (a.key === 'semi') note = "You'll count as inactive from " + day + ' if there are no more actions.';
      }
      return { a, text: note ? last + ' ' + note : last };
    });
    const months = computed(() => (d.value ? fillMonths(d.value.monthly).slice(-36) : []));
    const heat = computed(() => {
      const g = Array.from({ length: 7 }, () => Array(24).fill(0));
      if (d.value) for (const c of d.value.heat) g[c.d - 1][c.h] = Number(c.n);
      return g;
    });
    const types = computed(() => {
      if (!d.value) return [];
      const m = new Map();
      for (const t of d.value.by_type) { const l = actionLabel(t); m.set(l, (m.get(l) || 0) + Number(t.n)); }
      return [...m.entries()].map(([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value);
    });
    const wikiRows = computed(() => {
      if (!d.value) return [];
      const t = wq.value.toLowerCase();
      return d.value.by_wiki.map(w => ({ wiki: w.wiki, domain: w.domain, lk: Number(w.lk) === 1, n: Number(w.n), last_ts: w.last_ts }))
        .filter(r => !t || r.wiki.toLowerCase().includes(t) || r.domain.toLowerCase().includes(t))
        .sort((a, b) => (wsort.value === 'name' ? a.wiki.localeCompare(b.wiki) : wsort.value === 'last' ? (b.last_ts || '').localeCompare(a.last_ts || '') : b.n - a.n));
    });
    const wikiCount = computed(() => (d.value ? d.value.by_wiki.filter(w => Number(w.lk) !== 1).length : 0));
    const wikiCols = [{ id: 'wiki', label: 'Project' }, { id: 'n', label: 'Actions', textAlign: 'number' }, { id: 'last_ts', label: 'Last action' }];
    const groupCols = [{ id: 'group', label: 'Group' }, { id: 'from', label: 'From' }, { id: 'to', label: 'To' }, { id: 'current', label: 'Status' }, { id: 'log', label: 'Log' }];
    const localCols = [{ id: 'wiki', label: 'Project' }, { id: 'type', label: 'Type' }, { id: 'from', label: 'From' }, { id: 'to', label: 'To' }, { id: 'current', label: 'Status' }, { id: 'log', label: 'Log' }];
    const wsortItems = [{ value: 'n', label: 'Most actions' }, { value: 'last', label: 'Most recent' }, { value: 'name', label: 'Project name' }];
    const links = computed(() => {
      const n = encodeURIComponent(p.name.replace(/ /g, '_'));
      const out = [
        ['Meta user page', 'https://meta.wikimedia.org/wiki/User:' + n],
        ['Global account', 'https://meta.wikimedia.org/wiki/Special:CentralAuth/' + n],
        ['Global contributions', 'https://meta.wikimedia.org/wiki/Special:GlobalContributions/' + n],
        ['On-wiki stats', 'https://meta.wikimedia.org/wiki/User:Max/GlobalSysopStats/' + n],
        ['Year in review', '#/year?user=' + encodeURIComponent(p.name)]
      ];
      if (d.value && d.value.role === 'steward') out.push(['CheckUser statistics', 'https://meta.wikimedia.org/wiki/Stewards/CheckUser_statistics_for_loginwiki']);
      return out;
    });
    return {
      query, d, err, busy, load, tab, wq, wsort, per, perErr, perBusy, loadPeriods, pst, ptype, grpName, pstItems, ptypeItems, localRows,
      months, heat, types, wikiRows, wikiCount, localWikis, lastHint, myBox, wikiCols, groupCols, localCols, wsortItems, links, roleName, icons, num, ago, fmtTs, fmtDate, plural
    };
  },
  template: `
<div>
  <cdx-message v-if="err" type="error">{{ err }} <a href="#/users">Back to all users</a></cdx-message>
  <div v-if="!d && !err" class="loading"><cdx-progress-indicator>Loading</cdx-progress-indicator> Loading</div>
  <template v-if="d">
    <p class="sub mb"><sync-note/></p>
    <cache-bar :at="d.cached_at" :busy="busy" @refresh="load(true)"/>
    <div class="uhead">
      <div class="av"><cdx-icon :icon="icons.user" size="large"/></div>
      <div>
        <h1>{{ d.name }} <pin-button :name="d.name"/></h1>
        <div class="links">
          <role-tag :role="d.role"/>
          <span class="muted">{{ roleName(d.role) }} since {{ fmtDate(d.role_since) || 'unknown' }}<template v-if="d.first_granted && fmtDate(d.first_granted) !== fmtDate(d.role_since)"> (first global rights {{ fmtDate(d.first_granted) }})</template></span>
          <a v-for="l in links" :key="l[0]" :href="l[1]" :target="l[1].startsWith('#') ? null : '_blank'" rel="noopener">{{ l[0] }}</a>
        </div>
      </div>
    </div>
    <section v-if="myBox" class="panel mybox">
      <h2>Your activity</h2>
      <p><gs-tag :status="myBox.a.chip">{{ myBox.a.label }}</gs-tag> {{ myBox.text }}</p>
    </section>
    <div class="stats">
      <stat-card label="Total actions" :value="num(d.summary.total)" :icon="icons.check" tone="ok" :hint="'on ' + plural(wikiCount, 'project')"/>
      <stat-card label="Last 30 days" :value="num(d.summary.c30)" :icon="icons.calendar" tone="info" :hint="num(d.summary.c90) + ' in 90 days, ' + num(d.summary.c365) + ' in a year'"/>
      <stat-card label="Last action" :value="ago(d.summary.last_ts)" :icon="icons.clock" tone="info" :hint="lastHint"/>
      <stat-card label="Closed/Locked project actions" :value="num(d.summary.locked)" :icon="icons.lock" tone="warn" hint="Not included in total actions"/>
    </div>
    <cdx-tabs v-model:active="tab" :framed="true">
      <cdx-tab name="actions" label="Actions"><div class="panel tabpanel"><action-explorer :user="d.name" :initial="query" sync/></div></cdx-tab>
      <cdx-tab name="projects" label="Projects">
        <div class="panel tabpanel">
          <div class="toolbar"><div class="grp"><cdx-text-input v-model="wq" clearable :start-icon="icons.search" placeholder="Filter projects"/><cdx-select v-model:selected="wsort" :menu-items="wsortItems"/></div></div>
          <cdx-table caption="Projects" hide-caption :columns="wikiCols" :data="wikiRows">
            <template #item-wiki="{ row }"><span class="nw"><a class="mono" :href="'#/project/' + encodeURIComponent(row.wiki)">{{ row.wiki }}</a> <gs-tag v-if="row.lk" status="warning">Closed/Locked</gs-tag></span></template>
            <template #item-n="{ item }">{{ num(item) }}</template>
            <template #item-last_ts="{ item }"><span class="muted">{{ ago(item) }}</span></template>
            <template #empty-state>No projects match.</template>
          </cdx-table>
        </div>
      </cdx-tab>
      <cdx-tab v-if="d.role === 'steward'" name="steward" label="Steward actions"><div class="panel tabpanel"><steward-panel :name="d.name"/></div></cdx-tab>
      <cdx-tab name="membership" label="Rights history">
        <div class="panel tabpanel">
          <cdx-message v-if="perErr" type="error">{{ perErr }}</cdx-message>
          <div v-else-if="!per" class="loading"><cdx-progress-indicator>Loading</cdx-progress-indicator> Loading</div>
          <template v-else>
            <cache-bar :at="per.cached_at" :busy="perBusy" @refresh="loadPeriods(true)"/>
            <cdx-message v-if="!per.found" type="notice" :allow-user-dismiss="false">No rights history was found for this user in the configuration.</cdx-message>
            <template v-else>
              <h2>Global groups</h2>
              <cdx-table caption="Global groups" hide-caption :columns="groupCols" :data="per.groups">
                <template #item-group="{ item }"><role-tag v-if="item === 'steward' || item === 'global-sysop'" :role="item"/><span v-else>{{ grpName(item) }}</span></template>
                <template #item-from="{ item }"><span class="nw">{{ fmtDate(item) }}</span></template>
                <template #item-to="{ item }"><span class="nw">{{ item === 'present' ? 'present' : fmtDate(item) }}</span></template>
                <template #item-current="{ item }"><gs-tag :status="item ? 'success' : 'notice'">{{ item ? 'Current' : 'Past' }}</gs-tag></template>
                <template #item-log="{ item }"><a v-if="item" :href="'https://meta.wikimedia.org/wiki/' + item" target="_blank" rel="noopener" aria-label="View log" v-tooltip="'View log'"><cdx-icon :icon="icons.ext" size="small"/></a></template>
              </cdx-table>
              <h2 class="mt">Local administrator rights</h2>
              <cdx-message type="notice" :allow-user-dismiss="false">Actions made on a project while this user was a local administrator there are not recorded.</cdx-message>
              <div class="toolbar mt"><div class="grp"><cdx-select v-model:selected="pst" :menu-items="pstItems"/><cdx-select v-model:selected="ptype" :menu-items="ptypeItems"/></div><span class="muted">{{ localWikis }} of {{ plural(per.local.length, 'project') }}</span></div>
              <div v-if="!localRows.length" class="empty">No projects match.</div>
              <cdx-table v-else caption="Local administrator rights" hide-caption :columns="localCols" :data="localRows">
                <template #item-wiki="{ item }"><span class="nw mono">{{ item }}</span></template>
                <template #item-type="{ row }"><span class="nw"><gs-tag :status="row.is_gs ? 'success' : 'notice'">{{ row.is_gs ? 'GS' : 'Non-GS' }}</gs-tag> <gs-tag v-if="row.is_locked" status="warning">Closed/Locked</gs-tag></span></template>
                <template #item-from="{ item }"><span class="nw">{{ fmtDate(item) }}</span></template>
                <template #item-to="{ row }"><span class="nw">{{ row.to === 'present' ? 'present' : fmtDate(row.to) }}</span><span v-if="row.note" class="muted small"> ({{ row.note }})</span></template>
                <template #item-current="{ item }"><gs-tag :status="item ? 'success' : 'notice'">{{ item ? 'Current' : 'Past' }}</gs-tag></template>
                <template #item-log="{ row }"><a v-if="row.log && row.domain" :href="'https://' + row.domain + '/wiki/' + row.log" target="_blank" rel="noopener" aria-label="View log" v-tooltip="'View log'"><cdx-icon :icon="icons.ext" size="small"/></a></template>
              </cdx-table>
            </template>
          </template>
        </div>
      </cdx-tab>
      <cdx-tab name="activity" label="Activity">
        <div class="panel tabpanel">
          <div class="cols">
            <section class="chartbox"><h2>Actions per month</h2><bar-chart :data="months"/></section>
            <section class="chartbox"><h2>Actions by type</h2><rank-bars :items="types" share :limit="8"/></section>
          </div>
          <section class="chartbox mt"><h2>When actions happen (UTC)</h2><heatmap :cells="heat"/></section>
        </div>
      </cdx-tab>
    </cdx-tabs>
  </template>
</div>`
};

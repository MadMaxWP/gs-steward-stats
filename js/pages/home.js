import { computed, onMounted, ref, watch } from 'vue';
import { api } from '../api.js';
import { CdxButton, CdxMessage, CdxTable, icons } from '../codex.js';
import { ago, fillMonths, fmtDay, fmtTs, monthNames, num, plural, ymFromDate, ymMonthsBack } from '../format.js';
import { activity, gsInactive, roleName } from '../logs.js';
import { pins, route, setQuery, store } from '../store.js';
import { ActionList } from '../components/actions.js';
import { BarChart, RankBars } from '../components/charts.js';
import { CacheBar, PeriodPicker, PinButton, StatCard, periodLabel, periodRange } from '../components/common.js';

export const HomePage = {
  components: { StatCard, BarChart, RankBars, ActionList, CdxButton, CdxMessage, CdxTable, CacheBar, PeriodPicker, PinButton },
  setup() {
    const d = ref(null), err = ref(''), busy = ref(false);
    const q = route.value.query;
    const per = ref({ period: q.period || 'all', from: q.from || '', to: q.to || '' });
    const range = computed(() => periodRange(per.value));
    const ranged = ref(null), recent = ref([]);

    async function load(fresh) {
      busy.value = true;
      try { d.value = await api('overview', { refresh: fresh ? '1' : '' }); err.value = ''; }
      catch (e) { err.value = e.message; }
      finally { busy.value = false; }
      loadRange(fresh);
    }
    async function loadRange(fresh) {
      if (!range.value) { ranged.value = null; return; }
      try {
        const r = range.value;
        const [p, a] = await Promise.all([
          api('period', { from: r.from, to: r.to, refresh: fresh ? '1' : '' }),
          api('actions', { from: r.from, to: r.to, limit: 15, nocount: '1', refresh: fresh ? '1' : '' })
        ]);
        ranged.value = p; recent.value = a.rows;
      } catch (e) { err.value = e.message; }
    }
    onMounted(() => { load(false); loadYear(); });

    // a short teaser for the year page. in january the new year has barely started,
    // so it shows the year that just ended instead. same if this year has nothing yet
    const year = ref(null);
    async function loadYear() {
      const now = new Date(), thisYear = now.getUTCFullYear();
      try {
        let y = await api('year', { year: now.getUTCMonth() === 0 ? thisYear - 1 : thisYear });
        if (!y.totals.total && y.year === thisYear) y = await api('year', { year: thisYear - 1 });
        year.value = y;
      } catch (e) { year.value = null; }
    }
    const yearDone = computed(() => year.value && year.value.year < new Date().getUTCFullYear());
    const yearLink = computed(() => (yearDone.value ? '#/year?year=' + year.value.year : '#/year'));
    const yearLine = computed(() => {
      const y = year.value;
      if (!y || !y.totals.total) return '';
      const best = [...y.monthly].sort((a, b) => b.c - a.c)[0];
      const parts = [num(y.totals.total) + ' actions on ' + plural(y.totals.days, 'day') + ' by ' + plural(y.totals.users, 'person', 'people') + ' across ' + plural(y.totals.wikis, 'project') + '.'];
      if (best) parts.push('Busiest month: ' + monthNames[Number(String(best.ym).slice(4)) - 1] + ' (' + num(best.c) + ').');
      if (y.biggest_day) parts.push('Biggest day: ' + fmtDay(y.biggest_day.day) + ' (' + num(y.biggest_day.n) + ').');
      return parts.join(' ');
    });
    watch(per, v => {
      setQuery({ period: v.period === 'all' ? '' : v.period, from: v.period === 'custom' ? v.from : '', to: v.period === 'custom' ? v.to : '' });
      loadRange(false);
    }, { deep: true });

    const users = computed(() => (d.value ? d.value.users : []));
    // most active: last 30 days normally, or the chosen period
    const top = computed(() => {
      const counts = ranged.value ? ranged.value.users : Object.fromEntries(users.value.map(u => [u.name, Number(u.c30)]));
      return Object.entries(counts).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]).slice(0, 10)
        .map(([name, n]) => ({ label: name, value: n, href: '#/user/' + encodeURIComponent(name) }));
    });
    const months = computed(() => {
      if (ranged.value) return fillMonths(ranged.value.monthly, ymFromDate(ranged.value.from), ymFromDate(ranged.value.to));
      return d.value ? fillMonths(d.value.monthly, ymMonthsBack(23)) : [];
    });
    // one rule for "active" everywhere: the same one the activity tags use
    const active = computed(() => users.value.filter(u => activity(u).key === 'active').length);
    const activeInRange = computed(() => (ranged.value ? Object.values(ranged.value.users).filter(n => n > 0).length : 0));
    const gsCount = computed(() => users.value.filter(u => u.role === 'global-sysop').length);
    const inactive = computed(() => users.value.filter(gsInactive).length);
    const label = computed(() => periodLabel(per.value));

    const pinCols = [
      { id: 'pin', label: '', width: '44px' }, { id: 'name', label: 'User' }, { id: 'role', label: 'Role' },
      { id: 'c30', label: '30 days', textAlign: 'number' }, { id: 'last_ts', label: 'Last action' }, { id: 'activity', label: 'Activity' }
    ];
    const pinned = computed(() => users.value.filter(u => pins.value.includes(u.name)));

    // only for a logged in steward or global sysop: where they stand.
    // the 6 month inactivity rule is for global sysops, stewards just get their activity
    const myStatus = computed(() => {
      const me = store.me && store.me.username;
      const u = me && users.value.find(x => x.name === me);
      if (!u) return null;
      const a = activity(u);
      // stewards also do locks etc on meta, so say gs wiki for them
      const where = u.role === 'steward' ? ' on a GS wiki' : '';
      const last = u.last_ts ? 'Your last recorded action' + where + ' was ' + ago(u.last_ts) + '.' : 'You have no recorded actions' + where.replace('a GS wiki', 'GS wikis') + ' yet.';
      // stewards have no inactivity rule here, so just the status
      if (u.role === 'steward') return { type: a.key === 'active' || a.key === 'moderate' ? 'success' : 'notice', text: 'Your activity: ' + a.label + '. ' + last };
      if (a.key === 'inactive') return { type: 'error', text: last + ' That is 6 months or more, which meets the inactivity criterion for removal.' };
      // the inactivity date only matters once someone has gone quiet for 2 months
      if (a.key !== 'semi') return { type: 'success', text: 'Your activity: ' + a.label + '. ' + last };
      const until = new Date(u.last_ts || u.role_since || u.first_granted);
      until.setUTCMonth(until.getUTCMonth() + 6);
      return { type: 'warning', text: 'Your activity: ' + a.label + '. ' + last + ' Under the 6 month rule you would count as inactive from ' + fmtDay(until.toISOString()) + ' if you make no more actions.' };
    });

    return {
      d, err, busy, load, per, range, ranged, recent, top, months, active, activeInRange, gsCount, inactive, label,
      pinCols, pinned, myStatus, year, yearLine, yearDone, yearLink, activity, roleName, icons, num, ago, fmtTs
    };
  },
  template: `
<div>
  <div class="pagehead"><h1>Overview</h1><p class="sub">Administrative actions by current stewards and global sysops on global sysop projects.<sync-note/></p></div>
  <cdx-message v-if="err" type="error">{{ err }}</cdx-message>
  <div v-if="!d && !err" class="loading"><cdx-progress-indicator>Loading</cdx-progress-indicator> Loading</div>
  <template v-if="d">
    <div class="toolbar">
      <cache-bar :at="d.cached_at" :busy="busy" @refresh="load(true)"/>
      <period-picker v-model="per"/>
    </div>
    <cdx-message v-if="!d.totals.total && !d.totals.locked" type="warning">No data yet. Run backfill.py to fill the database.</cdx-message>
    <cdx-message v-if="myStatus" :type="myStatus.type" class="mb">{{ myStatus.text }}</cdx-message>
    <div class="stats" v-if="ranged">
      <stat-card label="Actions in this period" :value="num(ranged.total)" :icon="icons.contrib" tone="ok" :hint="label + ', active GS projects'"/>
      <stat-card label="Users with actions" :value="activeInRange + ' / ' + d.users.length" :icon="icons.userActive" tone="info" :hint="label"/>
      <stat-card label="Closed/Locked project actions" :value="num(ranged.locked)" :icon="icons.lock" tone="warn" :hint="label + ', listed separately'"/>
      <stat-card label="Inactive global sysops" :value="inactive + ' / ' + gsCount" :icon="icons.warn" :tone="inactive ? 'err' : 'ok'" hint="No action in 6 months, as of today"/>
    </div>
    <div class="stats" v-else>
      <stat-card label="Actions by current users" :value="num(d.totals.total)" :icon="icons.contrib" tone="ok" hint="Current stewards and global sysops only, active GS projects"/>
      <stat-card label="Last 24 hours" :value="num(d.totals.d1)" :icon="icons.clock" tone="info" :hint="num(d.totals.d7) + ' in 7 days'"/>
      <stat-card label="Last 30 days" :value="num(d.totals.d30)" :icon="icons.calendar" tone="info"/>
      <stat-card label="Active users" :value="active + ' / ' + d.users.length" :icon="icons.userActive" tone="info" hint="Last action within a month"/>
      <stat-card label="Inactive global sysops" :value="inactive + ' / ' + gsCount" :icon="icons.warn" :tone="inactive ? 'err' : 'ok'" hint="No action in 6 months, active or closed/locked projects"/>
      <stat-card label="Closed/Locked project actions" :value="num(d.totals.locked)" :icon="icons.lock" tone="warn" hint="Listed separately"/>
    </div>
    <section class="panel" v-if="pinned.length">
      <div class="panelhead"><h2>Pinned users</h2><a href="#/users?pinned=1">Show in users list</a></div>
      <cdx-table caption="Pinned users" hide-caption :columns="pinCols" :data="pinned">
        <template #item-pin="{ row }"><pin-button :name="row.name"/></template>
        <template #item-name="{ row }"><a :href="'#/user/' + encodeURIComponent(row.name)"><b>{{ row.name }}</b></a></template>
        <template #item-role="{ row }"><role-tag :role="row.role"/></template>
        <template #item-c30="{ item }">{{ num(item) }}</template>
        <template #item-last_ts="{ item }"><span class="muted nw" v-tooltip="item ? fmtTs(item) + ' UTC' : 'No actions yet'">{{ ago(item) }}</span></template>
        <template #item-activity="{ row }"><gs-tag :status="activity(row).chip">{{ activity(row).label }}</gs-tag></template>
      </cdx-table>
    </section>
    <div class="cols">
      <section class="panel">
        <div class="panelhead"><h2>Most active, {{ ranged ? label : 'last 30 days' }}</h2><a href="#/users">All users</a></div>
        <div v-if="!top.length" class="empty">No actions in this time.</div>
        <rank-bars v-else :items="top" ranked/>
      </section>
      <section class="panel">
        <h2>Actions per month</h2>
        <bar-chart :data="months"/>
      </section>
    </div>
    <section class="panel" v-if="yearLine">
      <div class="panelhead"><h2>{{ year.year }} {{ yearDone ? 'in review' : 'so far' }}</h2><a class="cdx-button cdx-button--fake-button cdx-button--fake-button--enabled cdx-button--size-medium" :href="yearLink">{{ yearDone ? 'See the full review' : 'See the full year in review' }}</a></div>
      <p class="muted">{{ yearLine }}</p>
    </section>
    <section class="panel">
      <div class="panelhead"><h2>Recent actions</h2><a :href="range ? '#/explorer?from=' + range.from + '&to=' + range.to : '#/explorer'">Open explorer</a></div>
      <action-list :rows="ranged ? recent : d.recent" mode="log" :show-user="true"/>
    </section>
  </template>
</div>`
};

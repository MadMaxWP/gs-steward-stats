import { computed, onMounted, ref, watch } from 'vue';
import { api } from '../api.js';
import { CdxMessage, CdxSelect, icons } from '../codex.js';
import { fillMonths, fmtDay, monthNames, num, plural } from '../format.js';
import { actionLabel } from '../logs.js';
import { route, setQuery, store } from '../store.js';
import { BarChart, RankBars } from '../components/charts.js';
import { StatCard } from '../components/common.js';

// one calendar year at a glance, for the whole team or for one person
export const YearPage = {
  components: { StatCard, BarChart, RankBars, CdxMessage, CdxSelect },
  setup() {
    const q = route.value.query;
    const thisYear = new Date().getUTCFullYear();
    const year = ref(String(q.year || thisYear));
    const who = ref(q.user || '');
    const d = ref(null), err = ref(''), busy = ref(false);

    async function load() {
      busy.value = true; err.value = '';
      try { d.value = await api('year', { year: year.value, user: who.value }); }
      catch (e) { err.value = e.message; }
      finally { busy.value = false; }
    }
    onMounted(load);
    watch([year, who], () => { setQuery({ year: year.value === String(thisYear) ? '' : year.value, user: who.value }); load(); });

    const yearItems = computed(() => ((d.value && d.value.years) || [thisYear]).map(y => ({ value: String(y), label: String(y) })));
    const whoItems = computed(() => [{ value: '', label: 'Everyone' }].concat(
      ((store.meta && store.meta.users) || []).map(u => ({ value: u.name, label: u.name }))
    ));
    const current = computed(() => d.value && d.value.year === thisYear);
    const title = computed(() => (who.value ? who.value + "'s " : '') + year.value + ' in review');

    // the chart covers the whole year, or up to this month for the current year
    const months = computed(() => {
      if (!d.value) return [];
      const y = d.value.year;
      const end = current.value ? y * 100 + new Date().getUTCMonth() + 1 : y * 100 + 12;
      return fillMonths(d.value.monthly, y * 100 + 1, end);
    });
    const busiest = computed(() => {
      const top = months.value.reduce((m, x) => (x.v > m.v ? x : m), { v: 0, label: '' });
      return top.v ? { name: monthNames[Number(top.label.slice(5, 7)) - 1], n: top.v } : null;
    });
    const wikis = computed(() => (d.value ? d.value.wikis.map(w => ({ label: w.wiki, value: Number(w.n), href: '#/project/' + encodeURIComponent(w.wiki) })) : []));
    const people = computed(() => (d.value ? d.value.people.map(p => ({ label: p.actor, value: Number(p.n), href: '#/user/' + encodeURIComponent(p.actor) })) : []));
    const types = computed(() => {
      if (!d.value) return [];
      const m = new Map();
      for (const t of d.value.by_type) { const l = actionLabel(t); m.set(l, (m.get(l) || 0) + Number(t.n)); }
      return [...m.entries()].map(([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value);
    });
    return { year, who, d, err, busy, yearItems, whoItems, current, title, months, busiest, wikis, people, types, icons, num, plural, fmtDay };
  },
  template: `
<div>
  <div class="pagehead"><h1>{{ title }}</h1><p v-if="current" class="sub">So far this year.</p></div>
  <div class="toolbar">
    <div class="grp">
      <cdx-select v-model:selected="year" :menu-items="yearItems" aria-label="Year"/>
      <cdx-select v-model:selected="who" :menu-items="whoItems" aria-label="Person"/>
    </div>
  </div>
  <cdx-message v-if="err" type="error">{{ err }}</cdx-message>
  <div v-if="!d && !err" class="loading"><cdx-progress-indicator>Loading</cdx-progress-indicator></div>
  <template v-if="d">
    <cdx-message v-if="!d.totals.total" type="notice" class="mb">No actions on active GS projects in {{ d.year }}.</cdx-message>
    <div class="stats">
      <stat-card label="Actions" :value="num(d.totals.total)" :icon="icons.check" tone="ok" :hint="'on ' + plural(d.totals.days, 'day') + ', active GS projects'"/>
      <stat-card label="Busiest month" :value="busiest ? busiest.name : '–'" :icon="icons.calendar" tone="info" :hint="busiest ? num(busiest.n) + ' actions' : ''"/>
      <stat-card label="Biggest day" :value="d.biggest_day ? fmtDay(d.biggest_day.day) : '–'" :icon="icons.clock" tone="info" :hint="d.biggest_day ? num(d.biggest_day.n) + ' actions' : ''"/>
      <stat-card label="Projects" :value="num(d.totals.wikis)" :icon="icons.globe" tone="info" :hint="!who ? 'by ' + plural(d.totals.users, 'person', 'people') : ''"/>
      <stat-card v-if="d.totals.locked" label="Closed/Locked project actions" :value="num(d.totals.locked)" :icon="icons.lock" tone="warn" hint="Not part of the totals"/>
    </div>
    <section class="panel"><h2>Actions per month</h2><bar-chart :data="months"/></section>
    <div class="cols">
      <section v-if="!who" class="panel"><h2>Most active</h2><rank-bars :items="people" ranked :limit="10"/></section>
      <section class="panel"><h2>Top projects</h2><rank-bars :items="wikis" ranked/></section>
      <section class="panel"><h2>Actions by type</h2><rank-bars :items="types" share :limit="8"/></section>
    </div>
  </template>
</div>`
};

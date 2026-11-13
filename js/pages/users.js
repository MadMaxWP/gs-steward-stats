import { computed, onMounted, ref, watch } from 'vue';
import { api } from '../api.js';
import { CdxButton, CdxCheckbox, CdxIcon, CdxMessage, CdxSelect, CdxTable, CdxTextInput, icons } from '../codex.js';
import { ago, csvText, downloadText, fmtDate, fmtTs, num } from '../format.js';
import { activity, gsInactive, roleName } from '../logs.js';
import { pins, route, setQuery } from '../store.js';
import { CacheBar, PeriodPicker, PinButton, periodLabel, periodRange } from '../components/common.js';

// cdx-table only says which column and direction, the sorting is ours
export const sortRows = (rows, sort) => {
  const [k, dir] = Object.entries(sort || {})[0] || [];
  if (!k || dir === 'none') return rows;
  const m = dir === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    const x = a[k] == null ? '' : a[k], y = b[k] == null ? '' : b[k];
    return (typeof x === 'string' && typeof y === 'string' ? x.localeCompare(y) : x < y ? -1 : x > y ? 1 : 0) * m;
  });
};

export const UsersPage = {
  components: { CdxTextInput, CdxSelect, CdxButton, CdxCheckbox, CdxIcon, CdxMessage, CdxTable, CacheBar, PeriodPicker, PinButton },
  setup() {
    const q0 = route.value.query;
    const d = ref(null), err = ref(''), busy = ref(false);
    const q = ref(q0.q || ''), level = ref(q0.level || 'all'), role = ref(q0.role || 'all'), pinnedOnly = ref(q0.pinned === '1');
    const per = ref({ period: q0.period || 'all', from: q0.from || '', to: q0.to || '' });
    const range = computed(() => periodRange(per.value));
    const ranged = ref(null);
    const sort = ref(range.value ? { inrange: 'desc' } : { c30: 'desc' });

    async function load(fresh) {
      busy.value = true;
      try { d.value = await api('overview', { refresh: fresh ? '1' : '' }); err.value = ''; }
      catch (e) { err.value = e.message; }
      finally { busy.value = false; }
      loadRange(fresh);
    }
    async function loadRange(fresh) {
      if (!range.value) { ranged.value = null; return; }
      try { ranged.value = await api('period', { from: range.value.from, to: range.value.to, refresh: fresh ? '1' : '' }); }
      catch (e) { err.value = e.message; }
    }
    onMounted(() => load(false));
    watch(per, (v, old) => {
      if ((v.period === 'all') !== (old.period === 'all')) sort.value = v.period === 'all' ? { c30: 'desc' } : { inrange: 'desc' };
      loadRange(false);
    }, { deep: true });
    watch([q, level, role, pinnedOnly, per], () => setQuery({
      q: q.value, level: level.value === 'all' ? '' : level.value, role: role.value === 'all' ? '' : role.value, pinned: pinnedOnly.value ? '1' : '',
      period: per.value.period === 'all' ? '' : per.value.period,
      from: per.value.period === 'custom' ? per.value.from : '', to: per.value.period === 'custom' ? per.value.to : ''
    }), { deep: true });

    const cols = computed(() => [
      { id: 'pin', label: '', width: '44px' },
      { id: 'name', label: 'User', allowSort: true }, { id: 'role', label: 'Role', allowSort: true },
      { id: 'role_since', label: 'Current role since', allowSort: true },
      ...(ranged.value ? [{ id: 'inrange', label: 'In period', allowSort: true, textAlign: 'number' }] : []),
      { id: 'total', label: 'Actions', allowSort: true, textAlign: 'number' }, { id: 'c30', label: '30 days', allowSort: true, textAlign: 'number' },
      { id: 'c90', label: '90 days', allowSort: true, textAlign: 'number' }, { id: 'wikis', label: 'Projects', allowSort: true, textAlign: 'number' },
      { id: 'locked', label: 'Closed/Locked projects', allowSort: true, textAlign: 'number' },
      { id: 'last_ts', label: 'Last action', allowSort: true }, { id: 'activity', label: 'Activity' }
    ]);
    const levelItems = [
      { value: 'all', label: 'All activity levels' }, { value: 'active', label: 'Active' }, { value: 'moderate', label: 'Moderate' },
      { value: 'semi', label: 'Low activity' }, { value: 'inactive', label: 'Inactive' }
    ];
    const roleItems = [{ value: 'all', label: 'Stewards and global sysops' }, { value: 'steward', label: 'Stewards' }, { value: 'global-sysop', label: 'Global sysops' }];
    const inactive = computed(() => (d.value ? d.value.users.filter(gsInactive).length : 0));
    const rows = computed(() => {
      if (!d.value) return [];
      const text = q.value.toLowerCase();
      const counts = ranged.value ? ranged.value.users : {};
      const list = d.value.users
        .map(u => ({ ...u, inrange: counts[u.name] || 0 }))
        .filter(u => (!text || u.name.toLowerCase().includes(text))
          && (level.value === 'all' || activity(u).key === level.value)
          && (role.value === 'all' || u.role === role.value)
          && (!pinnedOnly.value || pins.value.includes(u.name)));
      // pinned people stay on top, each group keeps the chosen column order
      const sorted = sortRows(list, sort.value);
      return [...sorted.filter(u => pins.value.includes(u.name)), ...sorted.filter(u => !pins.value.includes(u.name))];
    });
    const exportCsv = () => {
      const head = ['user', 'role', 'current_role_since', 'first_global_rights', ...(ranged.value ? ['in_period'] : []), 'actions', 'last_30_days', 'last_90_days', 'projects', 'locked_project_actions', 'last_action', 'activity'];
      downloadText('gs_users.csv', csvText(head, rows.value.map(u => [
        u.name, u.role, u.role_since, u.first_granted, ...(ranged.value ? [u.inrange] : []), u.total, u.c30, u.c90, u.wikis, u.locked, u.last_ts, activity(u).label
      ])));
    };
    const label = computed(() => periodLabel(per.value));
    return { d, err, busy, load, q, level, role, pinnedOnly, per, ranged, label, sort, cols, levelItems, roleItems, rows, inactive, exportCsv, activity, roleName, icons, num, ago, fmtDate, fmtTs };
  },
  template: `
<div>
  <div class="pagehead"><h1>Stewards and global sysops</h1><p class="sub">All current stewards and global sysops and their activity on global sysop projects.<sync-note/></p></div>
  <cdx-message v-if="err" type="error">{{ err }}</cdx-message>
  <div v-if="!d && !err" class="loading"><cdx-progress-indicator>Loading</cdx-progress-indicator> Loading</div>
  <section class="panel" v-if="d">
    <cache-bar :at="d.cached_at" :busy="busy" @refresh="load(true)"/>
    <cdx-message v-if="inactive" type="warning" :allow-user-dismiss="false" class="mb">{{ inactive }} global sysop{{ inactive === 1 ? ' has' : 's have' }} no recorded action in the last 6 months on active or closed/locked GS projects, which meets the inactivity criterion for removal.</cdx-message>
    <div class="toolbar">
      <div class="grp">
        <cdx-text-input v-model="q" clearable :start-icon="icons.search" placeholder="Filter by username"/>
        <cdx-select v-model:selected="role" :menu-items="roleItems"/>
        <cdx-select v-model:selected="level" :menu-items="levelItems"/>
        <period-picker v-model="per"/>
        <cdx-checkbox v-model="pinnedOnly" :inline="true">Pinned only</cdx-checkbox>
      </div>
      <div class="grp"><span class="muted">{{ rows.length }} of {{ d.users.length }} users</span><cdx-button @click="exportCsv"><cdx-icon :icon="icons.download"/> CSV</cdx-button></div>
    </div>
    <cdx-table caption="Stewards and global sysops" hide-caption :columns="cols" :data="rows" v-model:sort="sort">
      <template #item-pin="{ row }"><pin-button :name="row.name"/></template>
      <template #item-name="{ row }"><a class="uname" :href="'#/user/' + encodeURIComponent(row.name)"><b>{{ row.name }}</b></a></template>
      <template #item-role="{ row }"><role-tag :role="row.role"/></template>
      <template #item-role_since="{ row }">
        <span v-if="row.first_granted && fmtDate(row.first_granted) !== fmtDate(row.role_since)" class="nw muted" v-tooltip="'First global rights: ' + fmtDate(row.first_granted)">{{ fmtDate(row.role_since) || 'unknown' }}</span>
        <span v-else class="nw muted">{{ fmtDate(row.role_since) || 'unknown' }}</span>
      </template>
      <template #item-inrange="{ item }"><b>{{ num(item) }}</b></template>
      <template #item-total="{ item }">{{ num(item) }}</template>
      <template #item-c30="{ item }">{{ num(item) }}</template>
      <template #item-c90="{ item }">{{ num(item) }}</template>
      <template #item-wikis="{ item }">{{ num(item) }}</template>
      <template #item-locked="{ item }">{{ num(item) }}</template>
      <template #item-last_ts="{ row }"><span v-if="row.last" class="muted" v-tooltip="fmtTs(row.last.ts) + ' UTC'">{{ ago(row.last.ts) }}, {{ row.last.log_type }}/{{ row.last.log_action }} on {{ row.last.wiki }}</span><span v-else class="muted">none</span></template>
      <template #item-activity="{ row }"><gs-tag :status="activity(row).chip">{{ activity(row).label }}</gs-tag></template>
      <template #empty-state>No users match.</template>
    </cdx-table>
  </section>
</div>`
};

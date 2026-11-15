// small building blocks used on most pages
import { computed } from 'vue';
import { CdxButton, CdxCard, CdxIcon, CdxMessage, CdxSelect, CdxTextInput } from '../codex.js';
import { icons } from '../codex.js';
import { ago, daysAgo, fmtTs, today } from '../format.js';
import { isPinned, store, tick, togglePin } from '../store.js';

export const StatCard = {
  props: { label: String, value: [String, Number], icon: Object, tone: { type: String, default: 'info' }, hint: String },
  components: { CdxCard },
  template: `<cdx-card class="stat" :class="'tone-' + tone" :icon="icon"><template #title>{{ value }}</template><template #description>{{ label }}</template><template v-if="hint" #supporting-text>{{ hint }}</template></cdx-card>`
};

// thin outlined tag for activity, current/past, gs/non-gs etc, registered as <gs-tag>
export const GsTag = {
  props: { status: { type: String, default: 'notice' } },
  template: `<span class="gs-tag" :class="'is-' + status"><slot/></span>`
};

// steward in blue, global sysop in plain grey, square like the other tags
export const RoleTag = {
  props: { role: { type: String, default: '' } },
  template: `<span class="role-tag" :class="role === 'steward' ? 'is-steward' : 'is-gs'">{{ role === 'steward' ? 'Steward' : 'Global sysop' }}</span>`
};

// newest of the sync times: the update job's, and the listener's when it saves a live action
export const lastSync = () => {
  const u = store.meta && store.meta.updated;
  return u ? [u.last_update, u.last_backfill, u.last_live].filter(Boolean).sort().pop() || '' : '';
};

export const SyncNote = {
  setup() {
    const at = computed(lastSync);
    const age = computed(() => { tick.value; return at.value ? ago(at.value) : ''; });
    return { at, age, fmtTs };
  },
  template: `<span v-if="at" class="upd" v-tooltip="fmtTs(at) + ' UTC'">Data last synced {{ age }}.</span>`
};

// shown when the cron job seems stuck, so old numbers don't pass for current ones
export const StaleBanner = {
  components: { CdxMessage },
  setup() {
    const at = computed(lastSync);
    const stale = computed(() => { tick.value; return !!at.value && Date.now() - new Date(at.value).getTime() > 12 * 3600 * 1000; });
    return { at, stale, ago };
  },
  template: `<cdx-message v-if="stale" type="warning" class="stale">The data was last synced {{ ago(at) }}, so these numbers may be out of date.</cdx-message>`
};

export const CacheBar = {
  props: { at: String, busy: Boolean },
  emits: ['refresh'],
  components: { CdxButton, CdxIcon },
  setup(props) {
    const age = computed(() => { tick.value; return ago(props.at); });
    return { icons, age };
  },
  template: `<div class="cachebar" v-if="at"><span>Results as of {{ age }}.</span><cdx-button size="small" weight="quiet" :disabled="busy" @click="$emit('refresh')"><cdx-icon :icon="icons.refresh"/> Reload results</cdx-button></div>`
};

// hidden when there's only one page, so empty results don't say "page 1 of 1"
export const Pager = {
  props: { page: Number, pages: Number, total: Number, loading: Boolean },
  emits: ['update:page'],
  components: { CdxButton, CdxIcon },
  setup() { return { icons }; },
  template: `
<div class="pager" v-if="pages > 1">
  <cdx-button :disabled="page <= 1 || loading" @click="$emit('update:page', 1)" aria-label="First page"><cdx-icon :icon="icons.first"/></cdx-button>
  <cdx-button :disabled="page <= 1 || loading" @click="$emit('update:page', page - 1)" aria-label="Previous page"><cdx-icon :icon="icons.prev"/></cdx-button>
  <span>Page {{ page.toLocaleString('en') }} of {{ pages.toLocaleString('en') }} ({{ total.toLocaleString('en') }} results)</span>
  <cdx-button :disabled="page >= pages || loading" @click="$emit('update:page', page + 1)" aria-label="Next page"><cdx-icon :icon="icons.next"/></cdx-button>
  <cdx-button :disabled="page >= pages || loading" @click="$emit('update:page', pages)" aria-label="Last page"><cdx-icon :icon="icons.last"/></cdx-button>
</div>`
};

export const PinButton = {
  props: { name: String },
  components: { CdxButton, CdxIcon },
  setup(p) {
    const on = computed(() => isPinned(p.name));
    const label = computed(() => (on.value ? 'Unpin ' : 'Pin ') + p.name);
    return { on, label, icons, toggle: () => togglePin(p.name) };
  },
  template: `<cdx-button weight="quiet" size="small" :aria-label="label" :aria-pressed="on ? 'true' : 'false'" v-tooltip="on ? 'Unpin' : 'Pin to the top of your lists'" @click="toggle"><cdx-icon :icon="on ? icons.unstar : icons.star"/></cdx-button>`
};

// date range picker. value is { period, from, to }, from/to only matter for custom
export const periodItems = [
  { value: 'all', label: 'All time' }, { value: '7d', label: 'Last 7 days' }, { value: '30d', label: 'Last 30 days' },
  { value: '90d', label: 'Last 90 days' }, { value: '365d', label: 'Last 12 months' }, { value: 'ytd', label: 'This year' },
  { value: 'lastyear', label: 'Last year' }, { value: 'custom', label: 'Custom range' }
];

// turns the picker value into real dates, or null for all time
export function periodRange(v) {
  const y = new Date().getUTCFullYear();
  switch (v.period) {
    case '7d': return { from: daysAgo(6), to: today() };
    case '30d': return { from: daysAgo(29), to: today() };
    case '90d': return { from: daysAgo(89), to: today() };
    case '365d': return { from: daysAgo(364), to: today() };
    case 'ytd': return { from: y + '-01-01', to: today() };
    case 'lastyear': return { from: (y - 1) + '-01-01', to: (y - 1) + '-12-31' };
    case 'custom': return v.from || v.to ? { from: v.from || '', to: v.to || '' } : null;
    default: return null;
  }
}

export const periodLabel = v => {
  if (v.period === 'custom') return (v.from || 'start') + ' to ' + (v.to || 'today');
  return (periodItems.find(i => i.value === v.period) || periodItems[0]).label.toLowerCase();
};

export const PeriodPicker = {
  props: { modelValue: Object },
  emits: ['update:modelValue'],
  components: { CdxSelect, CdxTextInput },
  setup(p, { emit }) {
    const set = (k, val) => emit('update:modelValue', { ...p.modelValue, [k]: val });
    return { periodItems, set };
  },
  template: `
<div class="period">
  <cdx-select :selected="modelValue.period" :menu-items="periodItems" @update:selected="set('period', $event)" aria-label="Period"/>
  <template v-if="modelValue.period === 'custom'">
    <cdx-text-input input-type="date" :model-value="modelValue.from" @update:model-value="set('from', $event)" aria-label="From (UTC)"/>
    <span class="muted">to</span>
    <cdx-text-input input-type="date" :model-value="modelValue.to" @update:model-value="set('to', $event)" aria-label="To (UTC)"/>
  </template>
</div>`
};

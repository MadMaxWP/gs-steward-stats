// charts. codex has no chart component, so these are plain html styled with
// codex tokens (see the chart part of app.css)
import { computed, ref, watch } from 'vue';
import { CdxButton } from '../codex.js';
import { compact, dayNames, num, p2, shortMonths, ymLong } from '../format.js';

// window width, so small screens get fewer axis labels
const width = ref(window.innerWidth);
window.addEventListener('resize', () => { width.value = window.innerWidth; }, { passive: true });

// round up to 1, 2 or 5 x 10^n so the y axis gets readable numbers
const niceStep = x => { if (x <= 1) return 1; const p = 10 ** Math.floor(Math.log10(x)); const f = x / p; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p; };

// monthly bars. data is [{ label: 'YYYY-MM', v }], gaps already filled
export const BarChart = {
  props: { data: { type: Array, default: () => [] }, unit: { type: String, default: 'actions' } },
  setup(p) {
    const sel = ref(-1);
    watch(() => p.data, () => { sel.value = -1; });
    const step = computed(() => niceStep(Math.max(1, ...p.data.map(x => x.v)) / 4));
    const top = computed(() => step.value * 4);
    const ticks = computed(() => [0, 1, 2, 3, 4].map(i => i * step.value));
    const total = computed(() => p.data.reduce((s, x) => s + x.v, 0));
    const peak = computed(() => p.data.reduce((m, x) => (x.v > m.v ? x : m), p.data[0] || { v: 0, label: '' }));
    const avg = computed(() => (p.data.length ? Math.round(total.value / p.data.length) : 0));
    const shown = computed(() => (sel.value >= 0 ? p.data[sel.value] : null));
    const every = computed(() => Math.max(1, Math.ceil(p.data.length / (width.value < 600 ? 4 : 8))));
    // labels counted back from the newest month, so the latest one always has a label
    const label = (x, i) => {
      if ((p.data.length - 1 - i) % every.value !== 0) return '';
      const [y, m] = x.label.split('-');
      return shortMonths[Number(m) - 1] + " '" + y.slice(2);
    };
    const pick = i => { sel.value = sel.value === i ? -1 : i; };
    return { sel, top, ticks, total, peak, avg, shown, label, pick, num, compact, ymLong };
  },
  template: `
<div class="chart">
  <div v-if="!data.length" class="empty">No data.</div>
  <template v-else>
    <div class="chart-sum" aria-live="polite">
      <template v-if="shown"><span><b>{{ ymLong(shown.label) }}</b></span><span><b>{{ num(shown.v) }}</b> {{ unit }}</span></template>
      <template v-else-if="total"><span>Total <b>{{ num(total) }}</b></span><span>Peak <b>{{ num(peak.v) }}</b> in {{ ymLong(peak.label) }}</span><span>Average <b>{{ num(avg) }}</b> a month</span></template>
      <template v-else><span>No {{ unit }} in this time.</span></template>
    </div>
    <div class="vchart" @mouseleave="sel = -1">
      <div class="yaxis" aria-hidden="true"><span v-for="t in ticks" :key="t" :style="{ bottom: (t / top * 100) + '%' }">{{ compact(t) }}</span></div>
      <div class="plot">
        <div v-for="t in ticks" :key="t" class="gl" :class="{ base: t === 0 }" :style="{ bottom: (t / top * 100) + '%' }"></div>
        <div class="bars">
          <button v-for="(x, i) in data" :key="x.label" type="button" class="vbar" :class="{ on: sel === i, dim: sel >= 0 && sel !== i }"
            :aria-label="ymLong(x.label) + ': ' + num(x.v) + ' ' + unit" @mouseenter="sel = i" @focus="sel = i" @click="pick(i)">
            <i :style="{ height: (x.v / top * 100) + '%', minHeight: x.v ? '2px' : '0' }"></i>
          </button>
        </div>
      </div>
      <div class="xaxis" aria-hidden="true"><span v-for="(x, i) in data" :key="x.label">{{ label(x, i) }}</span></div>
    </div>
  </template>
</div>`
};

// day x hour grid, cells is 7 rows of 24 counts (sunday first, like mysql's DAYOFWEEK)
export const Heatmap = {
  props: { cells: Array },
  setup(p) {
    const sel = ref(null);
    const max = computed(() => Math.max(1, ...p.cells.flat()));
    const total = computed(() => p.cells.flat().reduce((s, c) => s + c, 0));
    const busiest = computed(() => {
      let b = { d: 0, h: 0, n: -1 };
      p.cells.forEach((row, d) => row.forEach((n, h) => { if (n > b.n) b = { d, h, n }; }));
      return b;
    });
    const opacity = c => (c ? 0.2 + 0.8 * c / max.value : 1);
    const slot = (d, h) => dayNames[d] + ' ' + p2(h) + ':00–' + p2((h + 1) % 24) + ':00 UTC';
    const every = computed(() => (width.value < 600 ? 6 : 3));
    const pick = (d, h) => { sel.value = sel.value && sel.value.d === d && sel.value.h === h ? null : { d, h }; };
    return { sel, total, busiest, opacity, slot, every, pick, dayNames, num };
  },
  template: `
<div class="chart">
  <div class="chart-sum" aria-live="polite">
    <template v-if="sel"><span><b>{{ slot(sel.d, sel.h) }}</b></span><span><b>{{ num(cells[sel.d][sel.h]) }}</b> actions</span></template>
    <template v-else-if="total"><span>Busiest <b>{{ slot(busiest.d, busiest.h) }}</b></span><span><b>{{ num(busiest.n) }}</b> actions</span></template>
    <template v-else><span>No actions yet.</span></template>
  </div>
  <div class="heatbox" @mouseleave="sel = null">
    <div class="heat">
      <template v-for="(row, i) in cells" :key="i">
        <span class="hl">{{ dayNames[i] }}</span>
        <button v-for="(c, j) in row" :key="j" type="button" class="hc" :class="{ v: c, on: sel && sel.d === i && sel.h === j }" :style="{ opacity: opacity(c) }"
          :aria-label="slot(i, j) + ': ' + c + ' actions'" @mouseenter="sel = { d: i, h: j }" @focus="sel = { d: i, h: j }" @click="pick(i, j)"></button>
      </template>
      <span></span>
      <span v-for="j in 24" :key="'x' + j" class="hx">{{ (j - 1) % every === 0 ? (j - 1) : '' }}</span>
    </div>
  </div>
  <div class="heatlegend" aria-hidden="true">Less <i class="z"></i><i style="opacity:.2"></i><i style="opacity:.47"></i><i style="opacity:.73"></i><i></i> More</div>
</div>`
};

// ranked list with a bar under each row, so long usernames never collide on mobile
export const RankBars = {
  props: { items: { type: Array, default: () => [] }, ranked: Boolean, share: Boolean, limit: { type: Number, default: 0 } },
  components: { CdxButton },
  setup(p) {
    const all = ref(false);
    const max = computed(() => Math.max(1, ...p.items.map(i => i.value)));
    const sum = computed(() => p.items.reduce((s, i) => s + i.value, 0) || 1);
    const list = computed(() => (p.limit && !all.value ? p.items.slice(0, p.limit) : p.items));
    const pct = v => {
      const x = v / sum.value * 100;
      if (x > 0 && x < 0.1) return '<0.1%';
      return (x >= 10 || x === 0 ? Math.round(x) : x.toFixed(1)) + '%';
    };
    return { all, max, list, pct, num };
  },
  template: `
<div>
  <div v-if="!items.length" class="empty">No data.</div>
  <ol v-else class="rank">
    <li v-for="(i, n) in list" :key="i.label">
      <div class="rk-top">
        <span v-if="ranked" class="rk-n">{{ n + 1 }}</span>
        <a v-if="i.href" class="rk-l" :href="i.href" v-tooltip="i.label">{{ i.label }}</a>
        <span v-else class="rk-l" v-tooltip="i.label">{{ i.label }}</span>
        <span class="rk-v">{{ num(i.value) }}<small v-if="share">{{ pct(i.value) }}</small></span>
      </div>
      <div class="rk-track"><div class="rk-fill" :style="{ width: (i.value / max * 100) + '%' }"></div></div>
    </li>
  </ol>
  <div v-if="limit && items.length > limit" class="rank-more"><cdx-button weight="quiet" size="small" @click="all = !all">{{ all ? 'Show fewer' : 'Show all ' + items.length }}</cdx-button></div>
</div>`
};

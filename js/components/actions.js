// lists of log actions, and the explorer that filters and pages through them
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { api, apiUrl } from '../api.js';
import { CdxButton, CdxCard, CdxField, CdxIcon, CdxLookup, CdxMessage, CdxSelect, CdxTable, CdxTextInput, CdxToggleButtonGroup, icons } from '../codex.js';
import { fmtDay, fmtTime, fmtTs, lsGet, lsSet, num } from '../format.js';
import { actionCats, actionLabel, commentParts, paramText, permalink, roleChip, roleName, sentence, targetLink, toneOf } from '../logs.js';
import { setQuery, store } from '../store.js';
import { Pager } from './common.js';

export const LogSentence = {
  props: { a: Object, withUser: { type: Boolean, default: true } },
  setup(p) { return { parts: computed(() => sentence(p.a, p.withUser)) }; },
  template: `<span class="sent"><template v-for="(s, i) in parts" :key="i"><a v-if="s.href" :href="s.href" :class="s.cls" target="_blank" rel="noopener">{{ s.v }}</a><span v-else :class="s.cls">{{ s.v }}</span></template></span>`
};

export const modeItems = [
  { value: 'log', label: 'Log', icon: icons.list }, { value: 'table', label: 'Table', icon: icons.table },
  { value: 'cards', label: 'Cards', icon: icons.card }, { value: 'timeline', label: 'Timeline', icon: icons.tl }
];

export const ActionList = {
  props: { rows: { type: Array, default: () => [] }, mode: { type: String, default: 'log' }, showUser: { type: Boolean, default: true } },
  components: { LogSentence, CdxIcon, CdxTable, CdxCard },
  setup(p) {
    const cols = computed(() => [
      { id: 'ts', label: 'Time (UTC)' },
      ...(p.showUser ? [{ id: 'actor', label: 'User' }] : []),
      { id: 'wiki', label: 'Project' }, { id: 'action', label: 'Action' }, { id: 'title', label: 'Target' },
      { id: 'comment', label: 'Reason', minWidth: '200px' }, { id: 'details', label: 'Details' }, { id: 'link', label: 'Log' }
    ]);
    // timeline groups by day
    const days = computed(() => {
      const out = [];
      let cur = null;
      for (const r of p.rows) {
        const day = fmtDay(r.ts);
        if (!cur || cur.day !== day) { cur = { day, items: [] }; out.push(cur); }
        cur.items.push(r);
      }
      return out;
    });
    const key = r => r.key || (r.wiki + ':' + r.log_id);
    const comment = r => commentParts(r.comment, r.domain || 'meta.wikimedia.org');
    return { cols, days, key, comment, fmtTs, fmtTime, permalink, targetLink, actionLabel, paramText, toneOf, roleName, roleChip, icons };
  },
  template: `
<div>
<div v-if="!rows.length" class="empty"><cdx-icon :icon="icons.info"/> No actions to show.</div>
<ul v-else-if="mode === 'log'" class="mwlog">
  <li v-for="r in rows" :key="key(r)" :class="{ fresh: r._new }">
    <span class="ts">{{ fmtTs(r.ts) }}</span>
    <span class="ico" :class="'t-' + toneOf(r).tone"><cdx-icon :icon="toneOf(r).icon" size="small"/></span>
    <log-sentence :a="r" :with-user="showUser"/>
    <span class="tags">
      <cdx-info-chip status="subtle" class="wtag">{{ r.wiki }}</cdx-info-chip>
      <gs-tag v-if="showUser && r.role" :status="roleChip(r.role)">{{ roleName(r.role) }}</gs-tag>
      <gs-tag v-if="r.locked" status="warning">Closed/Locked project</gs-tag>
      <a class="perma" :href="permalink(r)" target="_blank" rel="noopener" aria-label="Open log entry" v-tooltip="'Open log entry'"><cdx-icon :icon="icons.ext" size="small"/></a>
    </span>
  </li>
</ul>
<cdx-table v-else-if="mode === 'table'" caption="Actions" hide-caption :columns="cols" :data="rows">
  <template #item-ts="{ row }"><span class="nw">{{ fmtTs(row.ts) }}</span></template>
  <template #item-actor="{ row }"><span class="nw"><a :href="'#/user/' + encodeURIComponent(row.actor)">{{ row.actor }}</a> <gs-tag v-if="row.role" :status="roleChip(row.role)">{{ roleName(row.role) }}</gs-tag></span></template>
  <template #item-wiki="{ row }"><span class="nw"><a class="mono" :href="'#/project/' + encodeURIComponent(row.wiki)">{{ row.wiki }}</a> <gs-tag v-if="row.locked" status="warning">Closed/Locked</gs-tag></span></template>
  <template #item-action="{ row }"><span class="nw"><span class="ico" :class="'t-' + toneOf(row).tone"><cdx-icon :icon="toneOf(row).icon" size="small"/></span> {{ actionLabel(row) }}</span></template>
  <template #item-title="{ row }"><a :href="targetLink(row)" target="_blank" rel="noopener">{{ row.title }}</a></template>
  <template #item-comment="{ row }"><span class="sent"><template v-for="(s, i) in comment(row)" :key="i"><a v-if="s.href" :href="s.href" :class="s.cls" target="_blank" rel="noopener">{{ s.v }}</a><span v-else :class="s.cls">{{ s.v }}</span></template></span></template>
  <template #item-details="{ row }"><span class="muted mono">{{ paramText(row) }}</span></template>
  <template #item-link="{ row }"><a :href="permalink(row)" target="_blank" rel="noopener" aria-label="Open log entry" v-tooltip="'Open log entry'"><cdx-icon :icon="icons.ext" size="small"/></a></template>
</cdx-table>
<div v-else-if="mode === 'cards'" class="cards">
  <cdx-card v-for="r in rows" :key="key(r)" class="logcard" :class="['tone-' + toneOf(r).tone, { fresh: r._new }]" :icon="toneOf(r).icon">
    <template #title><span class="lc-head"><span>{{ actionLabel(r) }}</span><span class="muted lc-ts">{{ fmtTs(r.ts) }}</span></span></template>
    <template #description><log-sentence :a="r" :with-user="showUser"/></template>
    <template #supporting-text>
      <span v-if="paramText(r)" class="lc-params">{{ paramText(r) }}</span>
      <span class="lc-tags">
        <cdx-info-chip status="subtle" class="wtag">{{ r.wiki }}</cdx-info-chip>
        <gs-tag v-if="showUser && r.role" :status="roleChip(r.role)">{{ roleName(r.role) }}</gs-tag>
        <gs-tag v-if="r.locked" status="warning">Closed/Locked project</gs-tag>
        <a class="perma" :href="permalink(r)" target="_blank" rel="noopener" aria-label="Open log entry" v-tooltip="'Open log entry'"><cdx-icon :icon="icons.ext" size="small"/></a>
      </span>
    </template>
  </cdx-card>
</div>
<div v-else>
  <div v-for="g in days" :key="g.day" class="tl-day">
    <h4>{{ g.day }}<span>{{ g.items.length }} action{{ g.items.length === 1 ? '' : 's' }}</span></h4>
    <div class="tl-items">
      <div v-for="r in g.items" :key="key(r)" class="tl-item" :class="{ fresh: r._new }">
        <span class="tl-time">{{ fmtTime(r.ts) }}</span>
        <span class="ico dot" :class="'t-' + toneOf(r).tone"><cdx-icon :icon="toneOf(r).icon" size="small"/></span>
        <log-sentence :a="r" :with-user="showUser"/>
        <span class="tags">
          <cdx-info-chip status="subtle" class="wtag">{{ r.wiki }}</cdx-info-chip>
          <gs-tag v-if="showUser && r.role" :status="roleChip(r.role)">{{ roleName(r.role) }}</gs-tag>
          <gs-tag v-if="r.locked" status="warning">Closed/Locked project</gs-tag>
        </span>
      </div>
    </div>
  </div>
</div>
</div>`
};

const exportCap = 500000;
const blank = () => ({ q: '', user: '', role: 'all', wiki: '', cat: 'all', scope: 'open', from: '', to: '', sort: 'desc', per: '50' });

// filters + paging over /api/actions.
//   user / wiki: lock the explorer to one user or one project
//   sync: keep the filters in the address bar
export const ActionExplorer = {
  props: {
    user: { type: String, default: '' },
    wiki: { type: String, default: '' },
    initial: { type: Object, default: () => ({}) },
    sync: Boolean
  },
  components: { ActionList, Pager, CdxSelect, CdxTextInput, CdxToggleButtonGroup, CdxButton, CdxIcon, CdxMessage, CdxField, CdxLookup },
  setup(p) {
    const base = () => ({ ...blank(), user: p.user, wiki: p.wiki, scope: p.wiki ? 'all' : 'open' });
    const f = reactive(base());
    for (const k of Object.keys(f)) if (p.initial[k] && !(k === 'user' && p.user) && !(k === 'wiki' && p.wiki)) f[k] = p.initial[k];
    const mode = ref(lsGet('gs-mode', 'log'));
    const page = ref(Math.max(1, Number(p.initial.page) || 1));
    const rows = ref([]), total = ref(0), loading = ref(false), err = ref('');

    // rows come in chunks of a few pages, so paging inside a chunk needs no request
    const chunks = new Map();
    let counted = false, gen = 0, timer = null, seq = 0;
    const perPage = () => Number(f.per);
    const pagesPerChunk = () => (perPage() <= 50 ? 5 : perPage() <= 100 ? 3 : 2);
    const chunkSize = () => perPage() * pagesPerChunk();
    const params = () => ({
      user: f.user, role: f.role === 'all' ? '' : f.role, wiki: f.wiki, cat: f.cat === 'all' ? '' : f.cat,
      scope: f.scope, q: f.q, from: f.from, to: f.to, sort: f.sort
    });

    async function getChunk(idx, fresh) {
      const my = gen, size = chunkSize(), start = idx * size;
      const q = { ...params(), limit: size, nocount: counted ? '1' : '', refresh: fresh ? '1' : '' };
      const prev = chunks.get(idx - 1);
      if (prev && prev.length === size) {
        // next to a chunk we have: carry on from its last row, no offset needed
        const last = prev[prev.length - 1];
        q.after = last.ts + '|' + last.id;
      } else if (counted && start > total.value / 2) {
        // past the middle: read from the other end so the offset stays small
        const end = Math.min(total.value, start + size);
        q.tail = '1'; q.offset = total.value - end; q.limit = Math.max(1, end - start);
      } else {
        q.offset = start;
      }
      const d = await api('actions', q);
      if (my !== gen) return null;
      chunks.set(idx, d.rows);
      if (d.total >= 0) { total.value = d.total; counted = true; }
      return d.rows;
    }

    async function load(fresh) {
      const my = ++seq;
      loading.value = true; err.value = '';
      try {
        if (fresh) { chunks.clear(); counted = false; gen++; }
        if (!counted) await getChunk(0, fresh);  // the first chunk brings the total
        const idx = Math.floor((page.value - 1) / pagesPerChunk());
        let data = chunks.get(idx);
        if (!data) data = await getChunk(idx, false);
        if (my !== seq || !data) return;
        const start = ((page.value - 1) % pagesPerChunk()) * perPage();
        rows.value = data.slice(start, start + perPage());
        // on the last page of a chunk, fetch the next one in the background
        const next = idx + 1;
        if ((page.value - 1) % pagesPerChunk() === pagesPerChunk() - 1 && next * chunkSize() < total.value && !chunks.has(next)) getChunk(next, false).catch(() => {});
      } catch (e) { err.value = e.message; }
      finally { if (my === seq) loading.value = false; }
    }

    const writeUrl = () => {
      if (!p.sync) return;
      const b = base(), q = {};
      for (const k of Object.keys(b)) if ((k !== 'user' || !p.user) && (k !== 'wiki' || !p.wiki)) q[k] = f[k] !== b[k] ? f[k] : '';
      q.page = page.value > 1 ? page.value : '';
      setQuery(q);
    };

    watch(() => JSON.stringify(f), () => {
      gen++; chunks.clear(); counted = false;
      clearTimeout(timer);
      timer = setTimeout(() => { if (page.value === 1) load(); else page.value = 1; writeUrl(); }, 300);
    });
    watch(page, () => { load(); writeUrl(); });
    watch(mode, v => lsSet('gs-mode', v));
    onMounted(() => load());
    onBeforeUnmount(() => clearTimeout(timer));

    // user and project boxes: typing only suggests. the filter changes once the
    // text is a real name (picked from the menu or typed in full), or cleared
    const users = computed(() => (store.meta && store.meta.users) || []);
    const wikis = computed(() => (store.meta && store.meta.wikis) || []);
    const userText = ref(f.user), wikiText = ref(f.wiki);
    const userPick = ref(null), wikiPick = ref(null);
    const matchUser = t => users.value.find(u => u.name.toLowerCase() === t.trim().toLowerCase());
    const matchWiki = t => wikis.value.find(w => w.dbname === t.trim().toLowerCase() || (w.domain && w.domain === t.trim().toLowerCase()));
    watch(userText, t => { if (!t || !t.trim()) f.user = ''; else { const m = matchUser(t); if (m) f.user = m.name; } });
    watch(wikiText, t => { if (!t || !t.trim()) f.wiki = ''; else { const m = matchWiki(t); if (m) f.wiki = m.dbname; } });
    watch(userPick, v => { if (v) f.user = v; });
    watch(wikiPick, v => { if (v) f.wiki = v; });
    const suggest = (list, text, value, desc) => {
      const t = (text || '').toLowerCase();
      return list.filter(x => !t || value(x).toLowerCase().includes(t) || desc(x).toLowerCase().includes(t)).slice(0, 20)
        .map(x => ({ value: value(x), label: value(x), description: desc(x) }));
    };
    const userItems = computed(() => suggest(users.value, userText.value, u => u.name, u => roleName(u.role)));
    const wikiItems = computed(() => suggest(wikis.value, wikiText.value, w => w.dbname, w => w.domain || ''));
    const lookupMenu = { visibleItemLimit: 8 };

    const pages = computed(() => Math.max(1, Math.ceil(total.value / perPage())));
    const catItems = [{ value: 'all', label: 'All actions' }, ...actionCats];
    const roleItems = [{ value: 'all', label: 'Stewards and global sysops' }, { value: 'steward', label: 'Stewards' }, { value: 'global-sysop', label: 'Global sysops' }];
    const scopeItems = [{ value: 'open', label: 'Active GS projects' }, { value: 'locked', label: 'Closed/Locked projects' }, { value: 'all', label: 'All projects' }];
    const perItems = [25, 50, 100, 200].map(n => ({ value: String(n), label: n + ' per page' }));
    const sortItems = [{ value: 'desc', label: 'Newest first' }, { value: 'asc', label: 'Oldest first' }];
    const csvUrl = computed(() => apiUrl('actions', { ...params(), format: 'csv' }));
    const reset = () => { Object.assign(f, base()); userText.value = f.user; wikiText.value = f.wiki; };
    // only tell people about the export limit when they actually export too much
    const capNote = ref(false);
    const csvClicked = () => { capNote.value = total.value > exportCap; };
    watch(() => JSON.stringify(f), () => { capNote.value = false; });

    return {
      f, mode, page, rows, total, loading, err, pages, csvUrl, exportCap, capNote, csvClicked, reset, refresh: () => load(true),
      userText, wikiText, userPick, wikiPick, userItems, wikiItems, lookupMenu,
      catItems, roleItems, scopeItems, perItems, sortItems, modeItems, icons, num
    };
  },
  template: `
<div>
  <div class="filters">
    <cdx-field class="wide"><template #label>Search target or reason</template><cdx-text-input v-model="f.q" clearable :start-icon="icons.search" placeholder="Page title or reason text"/></cdx-field>
    <cdx-field v-if="!user"><template #label>User</template><cdx-lookup v-model:selected="userPick" v-model:input-value="userText" :menu-items="userItems" :menu-config="lookupMenu" clearable placeholder="Any user"/></cdx-field>
    <cdx-field v-if="!user"><template #label>Role</template><cdx-select v-model:selected="f.role" :menu-items="roleItems"/></cdx-field>
    <cdx-field v-if="!wiki"><template #label>Project</template><cdx-lookup v-model:selected="wikiPick" v-model:input-value="wikiText" :menu-items="wikiItems" :menu-config="lookupMenu" clearable placeholder="e.g. frwiki"/></cdx-field>
    <cdx-field><template #label>Action</template><cdx-select v-model:selected="f.cat" :menu-items="catItems"/></cdx-field>
    <cdx-field v-if="!wiki"><template #label>Projects</template><cdx-select v-model:selected="f.scope" :menu-items="scopeItems"/></cdx-field>
    <cdx-field><template #label>From (UTC)</template><cdx-text-input v-model="f.from" input-type="date"/></cdx-field>
    <cdx-field><template #label>To (UTC)</template><cdx-text-input v-model="f.to" input-type="date"/></cdx-field>
    <cdx-field><template #label>Order</template><cdx-select v-model:selected="f.sort" :menu-items="sortItems"/></cdx-field>
    <cdx-field><template #label>Page size</template><cdx-select v-model:selected="f.per" :menu-items="perItems"/></cdx-field>
  </div>
  <div class="toolbar">
    <div class="grp"><cdx-toggle-button-group v-model="mode" :buttons="modeItems"/></div>
    <div class="grp">
      <span class="muted">{{ loading ? 'Loading' : num(total) + ' actions' }}</span>
      <cdx-button :disabled="loading" @click="refresh"><cdx-icon :icon="icons.refresh"/> Refresh</cdx-button>
      <cdx-button @click="reset"><cdx-icon :icon="icons.reset"/> Reset</cdx-button>
      <a :href="csvUrl" class="cdx-button cdx-button--fake-button cdx-button--fake-button--enabled cdx-button--size-medium" download @click="csvClicked"><cdx-icon :icon="icons.download"/> CSV</a>
    </div>
  </div>
  <cdx-message v-if="capNote" type="notice" class="mb" allow-user-dismiss @user-dismissed="capNote = false">The CSV file holds the first {{ num(exportCap) }} of these actions. Narrow the filters to export the rest.</cdx-message>
  <cdx-message v-if="err" type="error">{{ err }}</cdx-message>
  <div v-if="loading && !rows.length" class="loading"><cdx-progress-indicator>Loading</cdx-progress-indicator> Loading</div>
  <action-list v-else :rows="rows" :mode="mode" :show-user="!user"/>
  <pager v-model:page="page" :pages="pages" :total="total" :loading="loading"/>
</div>`
};

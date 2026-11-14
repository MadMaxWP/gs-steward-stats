import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { api } from '../api.js';
import { CdxButton, CdxCheckbox, CdxField, CdxIcon, CdxMessage, CdxSelect, CdxTextInput, CdxToggleButtonGroup, icons } from '../codex.js';
import { ago, lsGet, lsJson, lsSet } from '../format.js';
import { liveCats } from '../logs.js';
import { ActionList, modeItems } from '../components/actions.js';
import { alertFor, chime, liveFilters, markSeen, matchesFilters, startAudio } from '../livewatch.js';

export const LivePage = {
  components: { ActionList, CdxSelect, CdxTextInput, CdxToggleButtonGroup, CdxButton, CdxCheckbox, CdxIcon, CdxMessage, CdxField },
  setup() {
    const items = ref([]), status = ref(null), err = ref('');
    // filters are remembered so alerts on other pages follow them too
    const f0 = liveFilters();
    const paused = ref(false), mode = ref(lsGet('gs-live-mode', 'log')), role = ref(f0.role), cat = ref(f0.cat), q = ref(f0.q);
    watch([role, cat, q], () => lsSet('gs-live-filters', JSON.stringify({ role: role.value, cat: cat.value, q: q.value })));
    let since = 0, timer = null;
    const seen = new Set();

    const matches = i => matchesFilters(i, { role: role.value, cat: cat.value, q: q.value });

    // alerts fire for new actions that match the filters above, on any page of the tool
    const alerts = ref(lsJson('gs-live-alerts', { sound: false, notify: false }));
    const permission = ref(typeof Notification === 'undefined' ? 'unsupported' : Notification.permission);
    watch(alerts, v => lsSet('gs-live-alerts', JSON.stringify(v)), { deep: true });
    watch(() => alerts.value.sound, on => {
      // browsers only allow audio after a click, and ticking the box is one
      if (on) { startAudio(); chime(); }
    });
    watch(() => alerts.value.notify, async on => {
      // the notice inside the page always works, the browser one only if it's allowed
      if (!on || permission.value !== 'default') return;
      permission.value = await Notification.requestPermission();
    });
    if (alerts.value.sound) startAudio();

    async function poll() {
      try {
        const d = await api('live', { since });
        status.value = d.status; err.value = '';
        if (paused.value) return;
        const fresh = [];
        for (const e of d.events) {
          if (seen.has(e.key)) continue;
          seen.add(e.key);
          e._new = since > 0;
          items.value.push(e);
          if (e._new) fresh.push(e);
        }
        if (d.events.length) {
          items.value.sort((a, b) => (a.ts < b.ts ? 1 : a.ts > b.ts ? -1 : 0));
          if (items.value.length > 500) items.value.length = 500;
        }
        // the first answer is history, only later ones can alert
        alertFor(fresh.filter(matches));
        markSeen();
        since = Math.max(0, d.now - 20000);
      } catch (e) { err.value = e.message; }
    }
    onMounted(() => { markSeen(); poll(); timer = setInterval(poll, 4000); });
    onBeforeUnmount(() => { clearInterval(timer); markSeen(); });
    watch(mode, v => lsSet('gs-live-mode', v));

    const catItems = [{ value: 'all', label: 'All actions' }, ...liveCats];
    const roleItems = [{ value: 'all', label: 'Stewards and global sysops' }, { value: 'steward', label: 'Stewards' }, { value: 'global-sysop', label: 'Global sysops' }];
    const filtered = computed(() => items.value.filter(matches));
    const lastHour = computed(() => items.value.filter(i => Date.now() - new Date(i.ts).getTime() < 3600000).length);
    const lastEvent = computed(() => (status.value && status.value.last_event_ms ? ago(new Date(status.value.last_event_ms).toISOString()) : 'not yet'));
    const clear = () => { items.value = []; };
    return { items, status, err, paused, mode, role, cat, q, alerts, permission, catItems, roleItems, modeItems, filtered, lastHour, lastEvent, clear, icons };
  },
  template: `
<div>
  <div class="pagehead"><h1>Live feed</h1><p class="sub">Actions by stewards and global sysops as they happen, including steward only logs and steward request page edits on Meta.</p></div>
  <cdx-message v-if="err" type="error">{{ err }}</cdx-message>
  <cdx-message v-else-if="status && !status.connected" type="warning" inline>Connecting to the Wikimedia event stream.</cdx-message>
  <cdx-message v-else-if="status && !status.context_ok" type="warning" inline>Connected, but the list of stewards, global sysops or GS projects could not be loaded yet, so some actions may be missed. Retrying every minute.</cdx-message>
  <cdx-message v-else-if="status" type="success" inline>Connected. Tracking {{ status.stewards }} stewards, {{ status.global_sysops }} global sysops and {{ status.wikis }} projects. Last event {{ lastEvent }}.</cdx-message>
  <section class="panel mt">
    <div class="filters">
      <cdx-field class="wide"><template #label>Search</template><cdx-text-input v-model="q" clearable :start-icon="icons.search" placeholder="User, project, target or reason"/></cdx-field>
      <cdx-field><template #label>Role</template><cdx-select v-model:selected="role" :menu-items="roleItems"/></cdx-field>
      <cdx-field><template #label>Action</template><cdx-select v-model:selected="cat" :menu-items="catItems"/></cdx-field>
      <cdx-field :is-fieldset="true" class="wide">
        <template #label>Alerts for new actions matching these filters, on any page of this tool</template>
        <cdx-checkbox v-model="alerts.sound" :inline="true">Play a sound</cdx-checkbox>
        <cdx-checkbox v-model="alerts.notify" :inline="true">Show a notification</cdx-checkbox>
        <template v-if="alerts.notify && (permission === 'denied' || permission === 'unsupported')" #help-text>Notifications show inside the tool only, your browser blocks them for this site.</template>
      </cdx-field>
    </div>
    <div class="toolbar">
      <div class="grp"><cdx-toggle-button-group v-model="mode" :buttons="modeItems"/></div>
      <div class="grp">
        <span class="muted">{{ filtered.length }} shown, {{ lastHour }} in the last hour</span>
        <cdx-button @click="paused = !paused"><cdx-icon :icon="paused ? icons.play : icons.pause"/> {{ paused ? 'Resume' : 'Pause' }}</cdx-button>
        <cdx-button @click="clear"><cdx-icon :icon="icons.clear"/> Clear</cdx-button>
      </div>
    </div>
    <div v-if="!items.length" class="loading"><cdx-progress-indicator>Loading</cdx-progress-indicator> Waiting for actions</div>
    <action-list v-else :rows="filtered" :mode="mode" :show-user="true"/>
  </section>
</div>`
};

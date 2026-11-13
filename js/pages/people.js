import { onBeforeUnmount, onMounted, ref } from 'vue';
import { api } from '../api.js';
import { CdxIcon, CdxMessage, icons } from '../codex.js';
import { metaUser } from '../logs.js';
import { store } from '../store.js';

// everyone who has used the tool lately in one list, online people first.
// the server only sends a name and a rough "x ago"
export const PeoplePage = {
  components: { CdxIcon, CdxMessage },
  setup() {
    const d = ref(null), err = ref('');
    let timer = null;
    async function load() {
      try { d.value = await api('people'); err.value = ''; }
      catch (e) { err.value = e.message; }
    }
    onMounted(() => { load(); timer = setInterval(load, 60000); });
    onBeforeUnmount(() => clearInterval(timer));
    return { d, err, metaUser, store, icons };
  },
  template: `
<div>
  <div class="pagehead"><h1>People</h1></div>
  <cdx-message v-if="err" type="error">{{ err }}</cdx-message>
  <div v-if="!d && !err" class="loading"><cdx-progress-indicator>Loading</cdx-progress-indicator></div>
  <section v-if="d" class="panel">
    <ul class="people">
      <li v-for="p in d.users" :key="p.name">
        <span class="who"><a :href="metaUser(p.name)" target="_blank" rel="noopener"><b>{{ p.name }}</b></a><cdx-icon v-if="store.me && p.name === store.me.username" class="you" :icon="icons.star" size="small" icon-label="You"></cdx-icon><a class="ca" :href="'https://meta.wikimedia.org/wiki/Special:CentralAuth/' + encodeURIComponent(p.name)" target="_blank" rel="noopener" title="CentralAuth">CA</a></span>
        <span class="when"><template v-if="p.online"><span class="dot" aria-hidden="true"></span>Online</template><template v-else>{{ p.ago }}</template></span>
      </li>
    </ul>
  </section>
</div>`
};

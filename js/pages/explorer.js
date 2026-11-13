import { ActionExplorer } from '../components/actions.js';
import { route } from '../store.js';

export const ExplorerPage = {
  components: { ActionExplorer },
  setup() { return { query: route.value.query }; },
  template: `
<div>
  <div class="pagehead"><h1>Action explorer</h1><p class="sub">Search every recorded action by current stewards and global sysops.<sync-note/></p></div>
  <section class="panel"><action-explorer :initial="query" sync/></section>
</div>`
};

import { CdxIcon, icons } from '../codex.js';

export const AboutPage = {
  components: { CdxIcon },
  setup() { return { icons }; },
  template: `
<div>
  <div class="pagehead"><h1>About</h1></div>
  <section class="panel about">
    <p>gs-steward-stats tracks admin actions by current stewards and global sysops on global sysop wikis: deletions and undeletions, revision and log deletion, blocks, protections, history merges, imports and AbuseFilter changes.</p>

    <h2><cdx-icon :icon="icons.contrib"/>Counting</h2>
    <p>An action is counted only if the user held steward or global sysop rights at the time. Actions on a wiki where the user was also a local admin are excluded. Closed wikis are listed separately and are not part of the main totals. Former stewards and global sysops are not tracked.</p>

    <h2><cdx-icon :icon="icons.userActive"/>Activity</h2>
    <p>Based on the date of a user's most recent counted action, including closed wikis.</p>
    <ul>
      <li><b>Active</b>: within the last month</li>
      <li><b>Moderate</b>: 1 to 2 months ago</li>
      <li><b>Low activity</b>: 2 to 6 months ago</li>
      <li><b>Inactive</b>: more than 6 months ago</li>
    </ul>
    <p>Global locks, suppression and renames are not included in activity, so a steward shown as inactive on GS wikis may still be active in other steward work.</p>

    <h2><cdx-icon :icon="icons.live"/>Live feed</h2>
    <p>Shows actions from the Wikimedia event stream as they happen. On Meta it also includes steward logs (rights, global blocks, locks, renames) and steward edits on the request pages.</p>

    <h2><cdx-icon :icon="icons.star"/>Pins</h2>
    <p>Starred users are pinned to the top of the overview and users list. Pins are stored in your browser only.</p>

    <h2><cdx-icon :icon="icons.group"/>People</h2>
    <p>Lists users who have logged in recently. Only the username and last visit time (to the minute) are stored, and entries are removed after 30 days.</p>

    <h2><cdx-icon :icon="icons.refresh"/>Data</h2>
    <p>Action history is read from the Wiki Replicas and stored in ToolsDB. New actions are saved from the event stream within seconds, and a full sync with the replicas runs every 3 hours. Rights history and local admin periods come from the GlobalSysopStats config.</p>

    <h2><cdx-icon :icon="icons.info"/>Notes</h2>
    <p>Counts are reliable for nearly all actions. Some closed wikis are not available on the replicas and are not queried, and actions performed right around the start or end of a rights period may sometimes be counted differently, so counts may differ very slightly. Every action links to its log entry so it can be verified.</p>

    <div class="aboutbtns">
      <a class="cdx-button cdx-button--fake-button cdx-button--fake-button--enabled cdx-button--action-progressive cdx-button--weight-normal cdx-button--size-medium" href="https://meta.wikimedia.org/wiki/User:DreamRimmer_bot/GlobalSysopStats/user-config.json" target="_blank" rel="noopener"><cdx-icon :icon="icons.ext"/> Source config (JSON)</a>
      <a class="cdx-button cdx-button--fake-button cdx-button--fake-button--enabled cdx-button--action-default cdx-button--weight-normal cdx-button--size-medium" href="https://meta.wikimedia.org/wiki/User_talk:Max" target="_blank" rel="noopener"><cdx-icon :icon="icons.ext"/> Report an issue</a>
    </div>
  </section>
</div>`
};

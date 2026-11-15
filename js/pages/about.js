import { CdxIcon, icons } from '../codex.js';

export const AboutPage = {
  components: { CdxIcon },
  setup() { return { icons }; },
  template: `
<div>
  <div class="pagehead"><h1>About</h1><p class="sub">Here's a quick explanation of what this tool tracks and how the numbers work.</p></div>
  <section class="panel about">
    <h2><cdx-icon :icon="icons.info"/>What this tool shows</h2>
    <p>This tool keeps track of administrative actions by current stewards and global sysops on global sysop projects. This includes deletions, undeletions, revision and log deletions, blocks, unblocks, protections, history merges, imports and AbuseFilter changes. Former stewards and global sysops aren't included.</p>

    <h2><cdx-icon :icon="icons.contrib"/>What gets counted</h2>
    <p>An action only counts if the user had the steward or global sysop right when they performed it. Actions on projects where they were also a local admin at the time aren't counted. Closed and locked projects are shown separately and aren't included in the main totals.</p>

    <h2><cdx-icon :icon="icons.userActive"/>Activity levels</h2>
    <p>Activity is based on when a user last performed an action recorded by this tool, including actions on closed and locked projects.</p>
    <ul>
      <li><b>Active:</b> At least one action in the last month.</li>
      <li><b>Moderate:</b> No action in the last month, but one within the last two months.</li>
      <li><b>Low activity:</b> No action in the last two months, but one within the last six months.</li>
      <li><b>Inactive:</b> No recorded action in the last six months or longer.</li>
    </ul>
    <p>This doesn't cover everything stewards do. Things like global locks, suppressions and renames aren't included in these activity figures, so someone marked as inactive here may still be active in other areas.</p>

    <h2><cdx-icon :icon="icons.live"/>Live feed</h2>
    <p>The live feed shows actions as they happen, including steward only logs from Meta such as rights changes, global blocks, global locks and renames, and edits by stewards on the steward request pages.</p>

    <h2><cdx-icon :icon="icons.star"/>Pinned users</h2>
    <p>You can use the star button to pin users and keep them handy. Pinned users appear on the overview and in the users list. Your pins are saved in your browser.</p>

    <h2><cdx-icon :icon="icons.group"/>People</h2>
    <p>The People page shows who has recently visited the tool, who's online and when others were last here.</p>
    <p>Only your username and roughly when you last visited are stored, rounded to the nearest minute. You're removed from the list after 30 days without a visit.</p>

    <h2><cdx-icon :icon="icons.refresh"/>Where the data comes from</h2>
    <p>Action history comes from the Wikimedia replica databases and is stored in the ToolsDB database. New actions are added from the live event stream, and a full sync from the replicas runs every three hours to fill any gaps.</p>
    <p>Steward and global sysop group history, along with local admin periods, comes from the GlobalSysopStats config and the APIs.</p>

    <h2><cdx-icon :icon="icons.warn"/>Accuracy</h2>
    <p>The numbers should be right for most actions, but there are a few limitations. Some closed or locked projects aren't available through the replicas, suppressed log entries can't be seen, and actions performed right around the start or end of a rights period may sometimes be counted differently.</p>
    <p>You can check individual actions by opening the corresponding log entry using the link icon.</p>

    <div class="aboutbtns">
      <a class="cdx-button cdx-button--fake-button cdx-button--fake-button--enabled cdx-button--action-progressive cdx-button--weight-normal cdx-button--size-medium" href="https://meta.wikimedia.org/wiki/User:DreamRimmer_bot/GlobalSysopStats/user-config.json" target="_blank" rel="noopener"><cdx-icon :icon="icons.ext"/> Source config (JSON)</a>
      <a class="cdx-button cdx-button--fake-button cdx-button--fake-button--enabled cdx-button--action-default cdx-button--weight-normal cdx-button--size-medium" href="https://meta.wikimedia.org/wiki/User_talk:Max" target="_blank" rel="noopener"><cdx-icon :icon="icons.ext"/> Report an issue</a>
    </div>
  </section>
</div>`
};

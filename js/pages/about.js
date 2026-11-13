import { CdxIcon, icons } from '../codex.js';

export const AboutPage = {
  components: { CdxIcon },
  setup() { return { icons }; },
  template: `
<div>
  <div class="pagehead"><h1>About</h1><p class="sub">What this tool shows and how the numbers are calculated.</p></div>
  <section class="panel about">
    <h2><cdx-icon :icon="icons.info"/>What this tool shows</h2>
    <p>This tool lists administrative actions by current stewards and global sysops on global sysop projects: deletions, undeletions, revision and log deletions, blocks, unblocks, protections, history merges, imports and AbuseFilter changes. Former members are not included.</p>
    <h2><cdx-icon :icon="icons.contrib"/>What gets counted</h2>
    <p>An action is counted only if the user held the steward or global sysop right at that time. Actions on a project where the user was also a local administrator at the time are skipped. Closed/locked projects are shown separately and are not part of the main totals.</p>
    <h2><cdx-icon :icon="icons.userActive"/>Activity levels</h2>
    <p>Activity is based on the date of a user's last recorded action, on active or closed/locked projects. A user is Active with an action in the last month, Moderate within the last two months, Low activity within the last six months, and Inactive with no action for six months or more. Stewards also do work that is not tracked here, such as global locks, suppression and renames, so a steward marked as inactive may still be active elsewhere.</p>
    <h2><cdx-icon :icon="icons.live"/>Live feed</h2>
    <p>The live feed shows actions as they happen, including steward only logs from Meta such as rights changes, global blocks, global locks and renames, and edits by stewards on the steward request pages. It listens only while someone has the page open, and keeps the last day of events so everyone sees the same feed.</p>
    <h2><cdx-icon :icon="icons.star"/>Pinned users</h2>
    <p>Pin users with the star button to keep them at hand on the overview and in the users list. Pins are saved in your browser only.</p>
    <h2><cdx-icon :icon="icons.userActive"/>People</h2>
    <p>The People page lists who has used the tool lately, online now or how long ago they were here. Only your username and roughly when you were last here are kept, rounded to the minute, and you drop off the list after 30 days away. Nothing else about your visits is stored.</p>
    <h2><cdx-icon :icon="icons.refresh"/>Where the data comes from</h2>
    <p>History comes from the Wikimedia replica databases and the data is synced every few hours. Totals are worked out at each sync, so the numbers on the overview, users and project pages are as of the last sync. Group history and local administrator periods come from the GlobalSysopStats config on Meta.</p>
    <h2><cdx-icon :icon="icons.warn"/>Accuracy</h2>
    <p>The numbers are accurate for nearly all actions, but a few may differ or be missing. Some closed/locked projects cannot be read from the replicas, suppressed log entries are hidden, and actions at the exact boundary of a rights period may be counted on either side. To verify a number, open the log entry using its link icon.</p>
    <div class="aboutbtns">
      <a class="cdx-button cdx-button--fake-button cdx-button--fake-button--enabled cdx-button--action-progressive cdx-button--weight-normal cdx-button--size-medium" href="https://meta.wikimedia.org/wiki/User:DreamRimmer_bot/GlobalSysopStats/user-config.json" target="_blank" rel="noopener"><cdx-icon :icon="icons.ext"/> Source config (JSON)</a>
      <a class="cdx-button cdx-button--fake-button cdx-button--fake-button--enabled cdx-button--action-default cdx-button--weight-normal cdx-button--size-medium" href="https://meta.wikimedia.org/wiki/User_talk:Max" target="_blank" rel="noopener"><cdx-icon :icon="icons.ext"/> Report an issue</a>
    </div>
  </section>
</div>`
};

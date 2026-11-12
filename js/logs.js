// how log entries are named, coloured and turned into a sentence like on Special:Log
import { ic } from './codex.js';
import { monthsAgo } from './format.js';

export const actionCats = [
  { value: 'delete', label: 'Deletions' }, { value: 'undelete', label: 'Undeletions' }, { value: 'revdel', label: 'Revision deletions' },
  { value: 'logdel', label: 'Log deletions' }, { value: 'block', label: 'Blocks' }, { value: 'unblock', label: 'Unblocks' },
  { value: 'reblock', label: 'Block modifications' }, { value: 'protect', label: 'Protections' }, { value: 'unprotect', label: 'Unprotections' },
  { value: 'protmod', label: 'Protection modifications' }, { value: 'merge', label: 'Page history merges' }, { value: 'import', label: 'Imports' },
  { value: 'abusefilter', label: 'AbuseFilter' }
];
// the live feed also carries the steward logs and sr page edits from meta
export const liveCats = [
  ...actionCats,
  { value: 'rights', label: 'Rights changes' }, { value: 'gblrights', label: 'Global rights' }, { value: 'gblblock', label: 'Global blocks' },
  { value: 'globalauth', label: 'Global locks' }, { value: 'renameuser', label: 'Renames' }, { value: 'gblrename', label: 'Global renames' },
  { value: 'sr', label: 'SR page edits' }
];

export const catOf = r => {
  const t = r.log_type, x = r.log_action;
  if (t === 'delete') return x === 'restore' ? 'undelete' : x === 'revision' ? 'revdel' : x === 'event' ? 'logdel' : 'delete';
  if (t === 'block') return x === 'unblock' ? 'unblock' : x === 'reblock' ? 'reblock' : 'block';
  if (t === 'protect') return x === 'unprotect' ? 'unprotect' : (x === 'modify' || x === 'move_prot') ? 'protmod' : 'protect';
  return t;
};

export const roleName = r => (r === 'steward' ? 'Steward' : 'Global sysop');
export const roleChip = r => (r === 'steward' ? 'progressive' : 'notice');

// icon + tone per action, falling back to per type
const byAction = {
  delete: { delete: ['cdxIconTrash', 'err'], delete_redir: ['cdxIconTrash', 'err'], delete_redir2: ['cdxIconTrash', 'err'], restore: ['cdxIconRestore', 'ok'], revision: ['cdxIconEyeClosed', 'warn'], event: ['cdxIconEyeClosed', 'warn'] },
  block: { block: ['cdxIconBlock', 'err'], unblock: ['cdxIconUnBlock', 'ok'], reblock: ['cdxIconSettings', 'warn'] },
  protect: { protect: ['cdxIconLock', 'warn'], unprotect: ['cdxIconUnLock', 'ok'], modify: ['cdxIconSettings', 'warn'], move_prot: ['cdxIconSettings', 'warn'] },
  gblblock: { gblock: ['cdxIconGlobe', 'err'], gunblock: ['cdxIconGlobe', 'ok'] }
};
const byType = {
  delete: ['cdxIconTrash', 'err'], block: ['cdxIconBlock', 'err'], protect: ['cdxIconLock', 'warn'],
  merge: ['cdxIconMerge', 'info'], import: ['cdxIconDownload', 'info'], abusefilter: ['cdxIconFunnel', 'info'],
  move: ['cdxIconMove', 'info'], rights: ['cdxIconUserRights', 'info'], gblrights: ['cdxIconUserGroup', 'info'],
  gblrename: ['cdxIconUserAvatar', 'info'], sr: ['cdxIconEdit', 'info'], gblblock: ['cdxIconGlobe', 'warn'],
  globalauth: ['cdxIconLock', 'warn'], renameuser: ['cdxIconUserAvatar', 'info']
};
export const toneOf = a => {
  const m = (byAction[a.log_type] && byAction[a.log_type][a.log_action]) || byType[a.log_type] || ['cdxIconInfoFilled', 'mute'];
  return { icon: ic(m[0], 'cdxIconInfoFilled'), tone: m[1] };
};

const labels = {
  'delete/delete': 'Deletion', 'delete/delete_redir': 'Deletion', 'delete/delete_redir2': 'Deletion', 'delete/restore': 'Undeletion',
  'delete/revision': 'Revision deletion', 'delete/event': 'Log deletion', 'block/block': 'Block', 'block/unblock': 'Unblock',
  'block/reblock': 'Block change', 'protect/protect': 'Protection', 'protect/unprotect': 'Unprotection',
  'protect/modify': 'Protection change', 'protect/move_prot': 'Protection move', 'merge/merge': 'History merge',
  'gblblock/gblock': 'Global block', 'gblblock/gunblock': 'Global unblock', 'rights/rights': 'Rights change',
  'gblrights/usergroups': 'Global rights change', 'globalauth/setstatus': 'Global lock/status change',
  'gblrename/rename': 'Global rename', 'sr/edit': 'SR page edit'
};
// when the action is blank or one we don't know, fall back to the type's name
const typeLabels = {
  delete: 'Deletion', block: 'Block', protect: 'Protection', merge: 'History merge', import: 'Import',
  abusefilter: 'AbuseFilter', move: 'Move', rights: 'Rights change', gblrights: 'Global rights change',
  gblblock: 'Global block', globalauth: 'Global lock/status change', renameuser: 'Rename', gblrename: 'Global rename', sr: 'SR page edit'
};
export const actionLabel = a => labels[a.log_type + '/' + a.log_action]
  || typeLabels[a.log_type]
  || a.log_type + (a.log_action ? '/' + a.log_action : '');

const enc = t => encodeURIComponent(String(t).replace(/ /g, '_')).replace(/%2F/gi, '/').replace(/%3A/gi, ':');
export const wikiLink = (domain, title) => 'https://' + domain + '/wiki/' + enc(title);
export const metaUser = n => wikiLink('meta.wikimedia.org', 'User:' + n);
const list = v => (Array.isArray(v) ? v : (typeof v === 'string' && v ? v.split(',').map(x => x.trim()) : []));

// edit summaries with [[links]] made clickable
const wikilinks = /\[\[([^\]|]+)(?:\|([^\]]*))?\]\]/g;
export function commentParts(c, domain) {
  const out = [];
  if (!c) return out;
  let i = 0, m;
  wikilinks.lastIndex = 0;
  while ((m = wikilinks.exec(c))) {
    if (m.index > i) out.push({ v: c.slice(i, m.index), cls: 'cmt' });
    const target = m[1].replace(/^:/, '').split('#')[0] || m[1];
    out.push({ v: m[2] || m[1], href: wikiLink(domain, target), cls: 'cmt' });
    i = m.index + m[0].length;
  }
  if (i < c.length) out.push({ v: c.slice(i), cls: 'cmt' });
  return out;
}

// the log line as a list of text/link parts
export function sentence(a, withUser) {
  const d = a.domain || 'meta.wikimedia.org';
  const t = a.title || '';
  const p = a.params || {};
  const ty = a.log_type, ac = a.log_action;
  const out = [];
  const text = v => out.push({ v });
  const link = (v, h) => out.push({ v, href: h });
  const bold = v => out.push({ v, cls: 'em' });
  const page = () => link(t, wikiLink(d, t));
  const userLink = n => link(n, wikiLink(d, 'User:' + n));

  if (withUser !== false) {
    userLink(a.actor);
    text(' (');
    link('talk', wikiLink(d, 'User talk:' + a.actor));
    text(' | ');
    link('contribs', 'https://' + d + '/wiki/Special:Contributions/' + enc(a.actor));
    text(')');
  }
  if (ty === 'delete') {
    if (ac === 'restore') { text(' restored page '); page(); }
    else if (ac === 'revision' || ac === 'event') {
      const n = Array.isArray(p.ids) ? p.ids.length : (p.ids ? 1 : 0);
      text(' changed visibility of ' + (n ? n + ' ' : '') + (p.type === 'logging' || ac === 'event' ? 'log event' : 'revision') + (n === 1 ? '' : 's') + ' on ');
      page();
    } else if (ac === 'delete_redir' || ac === 'delete_redir2') { text(' deleted redirect '); page(); text(' by overwriting'); }
    else { text(' deleted page '); page(); }
  } else if (ty === 'block') {
    if (ac === 'unblock') { text(' unblocked '); page(); }
    else {
      text(ac === 'reblock' ? ' changed block settings for ' : ' blocked ');
      page();
      text(' with an expiration time of ');
      bold(p.duration || 'infinite');
      const extra = [];
      if (p.sitewide === false) extra.push('partial block');
      list(p.flags).forEach(f => extra.push(f));
      if (extra.length) text(' (' + extra.join(', ') + ')');
    }
  } else if (ty === 'protect') {
    if (ac === 'unprotect') { text(' removed protection from '); page(); }
    else if (ac === 'move_prot') { text(' moved protection settings from '); link(p.oldtitle || '', wikiLink(d, p.oldtitle || '')); text(' to '); page(); }
    else { text(ac === 'modify' ? ' changed protection settings for ' : ' protected '); page(); if (p.description) text(' ' + p.description); }
  } else if (ty === 'merge') {
    text(' merged '); page();
    if (p.dest) { text(' into '); link(p.dest, wikiLink(d, p.dest)); }
    if (p.mergepoint) text(' (revisions up to ' + p.mergepoint + ')');
  } else if (ty === 'import') {
    text(' imported '); page(); text(ac === 'upload' ? ' by file upload' : ac === 'interwiki' ? ' by interwiki' : '');
  } else if (ty === 'abusefilter') {
    text(ac === 'create' ? ' created abuse filter ' : ' modified abuse filter ');
    const id = p.newId || p.id;
    if (id) link('filter ' + id, 'https://' + d + '/wiki/Special:AbuseFilter/' + id); else page();
    if (p.historyId && id) { text(' ('); link('diff', 'https://' + d + '/wiki/Special:AbuseFilter/history/' + id + '/diff/prev/' + p.historyId); text(')'); }
  } else if (ty === 'move') {
    text(' moved page '); page();
    if (p.target) { text(' to '); link(p.target, wikiLink(d, p.target)); }
  } else if (ty === 'rights') {
    text(' changed group membership for '); page();
    text(' from ' + (list(p.oldgroups).join(', ') || '(none)') + ' to ' + (list(p.newgroups).join(', ') || '(none)'));
  } else if (ty === 'gblrights') {
    if (ac === 'usergroups') {
      text(' changed global group membership for '); page();
      text(' from ' + (list(p.oldGroups).join(', ') || '(none)') + ' to ' + (list(p.newGroups).join(', ') || '(none)'));
    } else { text(' changed global rights settings for '); page(); }
  } else if (ty === 'gblblock') {
    text(ac === 'gblock' ? ' globally blocked ' : ac === 'gunblock' ? ' removed the global block on ' : ' modified the global block on '); page();
  } else if (ty === 'globalauth') {
    const added = list(p.added), removed = list(p.removed);
    text(added.includes('locked') ? ' globally locked ' : removed.includes('locked') ? ' globally unlocked ' : ' changed global status of '); page();
  } else if (ty === 'renameuser' || ty === 'gblrename') {
    text(ty === 'gblrename' ? ' globally renamed user ' : ' renamed user ');
    userLink(p.olduser || t);
    if (p.newuser) { text(' to '); userLink(p.newuser); }
  } else if (ty === 'sr') {
    text(' edited '); page();
  } else {
    text(' performed ' + ty + '/' + ac + ' on '); page();
  }
  if (a.comment) { text(' ('); commentParts(a.comment, d).forEach(s => out.push(s)); text(')'); }
  return out;
}

export const paramText = a => Object.entries(a.params || {})
  .filter(([k]) => k !== 'legacy')
  .map(([k, v]) => k + ': ' + (Array.isArray(v) ? v.join(', ') : (v && typeof v === 'object') ? JSON.stringify(v) : v))
  .join('; ');
export const permalink = r => (r.domain ? 'https://' + r.domain + '/wiki/Special:Redirect/' + (r.log_type === 'sr' ? 'revision/' : 'logid/') + r.log_id : '#');
export const targetLink = r => (r.domain ? wikiLink(r.domain, r.title || '') : '#');

// activity level from the last recorded action, same scale for stewards and gs.
// closed/locked wikis count here, matching the gs inactivity rule
export const activity = u => {
  const since = u.last_ts || u.role_since || u.first_granted;
  if (!since) return { label: 'No actions yet', chip: 'notice', key: 'new' };
  const t = new Date(since);
  if (t < monthsAgo(6)) return { label: 'Inactive', chip: 'error', key: 'inactive' };
  if (!u.last_ts) return { label: 'No actions yet', chip: 'notice', key: 'new' };
  if (t >= monthsAgo(1)) return { label: 'Active', chip: 'success', key: 'active' };
  if (t >= monthsAgo(2)) return { label: 'Moderate', chip: 'notice', key: 'moderate' };
  return { label: 'Low activity', chip: 'warning', key: 'semi' };
};
export const gsInactive = u => u.role === 'global-sysop' && activity(u).key === 'inactive';

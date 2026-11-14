// one place for everything we take from codex
import * as codex from '@wikimedia/codex';
import * as iconSet from '@wikimedia/codex-icons';

export const {
  CdxButton, CdxCard, CdxCheckbox, CdxField, CdxIcon, CdxInfoChip, CdxLookup, CdxMenuButton, CdxMessage, CdxProgressIndicator,
  CdxSelect, CdxTab, CdxTable, CdxTabs, CdxTextInput, CdxToast, CdxToggleButtonGroup, CdxTooltip
} = codex;

// first icon that exists, older icon packs miss a few names
export const ic = (...names) => {
  for (const n of names) if (iconSet[n]) return iconSet[n];
  return iconSet.cdxIconInfoFilled;
};

export const icons = {
  search: ic('cdxIconSearch'), ext: ic('cdxIconLinkExternal'), info: ic('cdxIconInfoFilled'), download: ic('cdxIconDownload'),
  prev: ic('cdxIconPrevious', 'cdxIconArrowPrevious'), next: ic('cdxIconNext', 'cdxIconArrowNext'),
  first: ic('cdxIconDoubleChevronStart', 'cdxIconArrowPrevious'), last: ic('cdxIconDoubleChevronEnd', 'cdxIconArrowNext'),
  pause: ic('cdxIconPause'), play: ic('cdxIconPlay'), clear: ic('cdxIconTrash'), reset: ic('cdxIconClear', 'cdxIconTrash'),
  refresh: ic('cdxIconReload', 'cdxIconHistory'), user: ic('cdxIconUserAvatar'), group: ic('cdxIconUserGroup'),
  globe: ic('cdxIconGlobe'), clock: ic('cdxIconClock'), home: ic('cdxIconHome'), check: ic('cdxIconSuccess', 'cdxIconCheck'),
  list: ic('cdxIconListBullet'), table: ic('cdxIconTable'), card: ic('cdxIconArticle', 'cdxIconImage'), tl: ic('cdxIconHistory'),
  warn: ic('cdxIconAlert'), lock: ic('cdxIconLock'), calendar: ic('cdxIconCalendar'), live: ic('cdxIconLive', 'cdxIconClock'),
  contrib: ic('cdxIconUserContributions', 'cdxIconUserGroup'), userActive: ic('cdxIconUserActive', 'cdxIconUserAvatar'),
  sun: ic('cdxIconSun', 'cdxIconBright', 'cdxIconLightbulb'), moon: ic('cdxIconMoon', 'cdxIconClock'), logOut: ic('cdxIconLogOut', 'cdxIconClose'),
  logIn: ic('cdxIconLogIn', 'cdxIconUserAvatar'), key: ic('cdxIconKey', 'cdxIconLock'), star: ic('cdxIconStar'),
  unstar: ic('cdxIconUnStar', 'cdxIconStar'), bell: ic('cdxIconBell', 'cdxIconNotice')
};

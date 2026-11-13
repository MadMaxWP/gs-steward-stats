import os

# shared settings for the web app and backfill.py

user_agent = "gs-steward-stats (https://meta.wikimedia.org/wiki/User:Max; madmax.wp@proton.me)"

db_name = os.environ.get("GS_DB_NAME", "gs_actions")
db_host = os.environ.get("GS_DB_HOST", "tools.db.svc.wikimedia.cloud")

# per user rights history, kept on meta by DreamRimmer_bot
config_page = "User:DreamRimmer_bot/GlobalSysopStats/user-config.json"
wikiset_name = "Opted-out of global sysop wikis"

app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# the live feed files go here. every worker can see it, so it's
# how they share things
data_dir = os.environ.get("GS_DATA_DIR", app_dir)

cdn = os.environ.get("GS_CDN", "https://tools-static.wmflabs.org/cdnjs/ajax/libs")
assets = {
    "vue": os.environ.get("GS_VUE_URL", cdn + "/vue/3.5.44/vue.esm-browser.prod.min.js"),
    "codex": os.environ.get("GS_CODEX_URL", cdn + "/codex/2.7.0/codex.min.js"),
    "icons": os.environ.get("GS_ICONS_URL", cdn + "/codex-icons/2.7.0/codex-icons.min.js"),
    "codex_css": os.environ.get("GS_CODEX_CSS", cdn + "/codex/2.7.0/codex.style.css"),
    "tokens": os.environ.get("GS_TOKENS_CSS", cdn + "/codex-design-tokens/2.7.0/theme-wikimedia-ui.css"),
    "dark": os.environ.get("GS_DARK_CSS", cdn + "/codex-design-tokens/2.7.0/theme-wikimedia-ui-mode-dark.css"),
    "logo": "https://upload.wikimedia.org/wikipedia/commons/thumb/5/57/Meta-Wiki_Global_sysop-2000px.png/120px-Meta-Wiki_Global_sysop-2000px.png",
}

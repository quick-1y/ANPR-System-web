"""Personal appearance, sidebar pin and client-time default in the interface.

Theme and style exist only as personal preferences: there is no instance
default, no public appearance endpoint and no Settings control for them. The
sidebar pin is a control inside the sidebar; the timezone is configured only in
Settings → Time (there is no personal timezone)."""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

from app.api.routers import preferences as prefs_router
from app.api.routers import settings as settings_router
from app.api.routers.system import system_time
from app.api.schemas import InterfacePayload
from config.preferences import known_keys, resolve
from config.registry import ConfigClass, REGISTRY, specs
from tests.test_preferences import NO_PERMISSIONS, OTHER_USER, _patch, _with_user_db
from tests.test_reconnect_settings import USER, _container, _payload

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "app" / "web"
JS = WEB / "js"


def _js(name: str) -> str:
    return (JS / name).read_text(encoding="utf-8")


def _all_js() -> str:
    return "".join(p.read_text(encoding="utf-8") for p in JS.glob("*.js"))


class _Tree(HTMLParser):
    """Collects element ids and, for each, the ids of its ancestors."""

    VOID = {"input", "img", "br", "hr", "meta", "link"}

    def __init__(self):
        super().__init__()
        self.stack, self.ancestors = [], {}

    def handle_starttag(self, tag, attrs):
        ident = dict(attrs).get("id")
        if ident:
            self.ancestors[ident] = [a for a in self.stack if a]
        if tag not in self.VOID:
            self.stack.append(ident)

    def handle_endtag(self, tag):
        if tag not in self.VOID and self.stack:
            self.stack.pop()


def _tree() -> _Tree:
    tree = _Tree()
    tree.feed((WEB / "index.html").read_text(encoding="utf-8"))
    return tree


def _inside(container_id: str) -> set[str]:
    return {ident for ident, parents in _tree().ancestors.items() if container_id in parents}


class TestPersonalAppearanceOnly:
    def test_there_is_no_instance_default_anywhere_in_the_registry(self):
        assert not [k for k in REGISTRY if k.startswith("interface.default_") and k != "interface.default_locale"]
        assert {"theme", "style"} <= {s.key for s in specs(ConfigClass.U)}

    def test_the_public_appearance_endpoint_is_gone(self):
        assert not (ROOT / "app" / "api" / "routers" / "public.py").exists()
        assert "public_router" not in (ROOT / "app" / "api" / "main.py").read_text(encoding="utf-8")
        assert "api/public/appearance" not in _all_js()

    def test_settings_api_carries_no_theme_or_style(self):
        assert set(InterfacePayload.model_fields) == {"display_timezone"}
        container, _ = _container()
        body = settings_router.get_global_settings(container=container, current_user=USER)
        assert set(body["interface"]) == {"display_timezone", "timezone_configured"}

    def test_the_theme_belongs_to_the_user_not_to_the_instance(self):
        container = _with_user_db()
        _patch(container, NO_PERMISSIONS, theme="dark", style="aurora")
        mine = prefs_router.get_my_preferences(container=container, user=NO_PERMISSIONS)["preferences"]
        theirs = prefs_router.get_my_preferences(container=container, user=OTHER_USER)["preferences"]
        assert (mine["theme"], mine["style"]) == ({"value": "dark", "source": "user"}, {"value": "aurora", "source": "user"})
        assert (theirs["theme"], theirs["style"]) == ({"value": "light", "source": "default"}, {"value": "graphite-minimal", "source": "default"})

    def test_a_user_without_a_choice_gets_the_code_default_and_a_reset_returns_to_it(self):
        container = _with_user_db()
        assert resolve({})["theme"] == {"value": "light", "source": "default"}
        assert _patch(container, NO_PERMISSIONS, theme="dark")["preferences"]["theme"]["source"] == "user"
        assert _patch(container, NO_PERMISSIONS, theme=None)["preferences"]["theme"] == {"value": "light", "source": "default"}

    def test_the_settings_page_has_no_theme_or_style_controls(self):
        assert 'id="g_theme"' not in (WEB / "index.html").read_text(encoding="utf-8")
        assert 'id="g_style"' not in (WEB / "index.html").read_text(encoding="utf-8")
        settings = _js("settings.js")
        assert "default_theme" not in settings and "default_style" not in settings and "appearance" not in settings

    def test_appearance_is_resolved_before_the_settings_page_and_without_a_public_call(self):
        app = _js("app.js")
        assert app.index("appearance.signIn(") < app.index('hasPermission("tab:settings")')
        assert "fetchPublic" not in _js("appearance-core.js") + _js("appearance.js")
        assert "anpr_appearance_instance" not in _all_js()


class TestMyPreferencesContents:
    def test_the_modal_holds_only_theme_and_style(self):
        controls = {i for i in _inside("prefsModal") if i.startswith("p_")}
        assert controls == {"p_theme", "p_style", "p_theme_source", "p_style_source"}

    def test_no_timezone_or_pin_control_is_left_in_it(self):
        assert not {"p_timezone", "p_sidebar_locked"} & _inside("prefsModal")

    def test_the_preference_api_has_no_timezone(self):
        assert "timezone" not in known_keys()
        assert set(known_keys()) == {"theme", "style", "sidebar_locked", "debug_panel_enabled", "channel_metrics_visible"}

    def test_the_personal_controls_live_outside_the_settings_tab(self):
        tree = _tree()
        for control in ("themeToggleBtn", "prefsBtn", "prefsModal", "p_theme", "p_style", "railPinBtn"):
            assert control in tree.ancestors, control
            assert "tab-settings" not in tree.ancestors[control], control

    def test_no_personal_timezone_code_remains(self):
        assert "p_timezone" not in _all_js() and "personalZone" not in _all_js()
        assert "effective_timezone" not in (ROOT / "config" / "preferences.py").read_text(encoding="utf-8")


class TestSidebarPin:
    def test_the_pin_is_a_button_inside_the_sidebar(self):
        assert "leftRail" in _tree().ancestors["railPinBtn"]
        assert 'aria-pressed="false"' in (WEB / "index.html").read_text(encoding="utf-8")

    def test_it_toggles_the_same_personal_preference_and_the_same_rail_behaviour(self):
        prefs = _js("preferences.js")
        block = prefs[prefs.index("export function bindSidebarPin"):]
        assert 'savePreference("sidebar_locked", wanted)' in block and "afterChange(wanted)" in block
        app = _js("app.js")
        assert "bindSidebarPin((pinned) => applySidebarLocked(pinned))" in app and "syncSidebarPin()" in app
        assert "if (sidebarLocked) return;" in _js("ui.js")  # a pinned rail does not expand on hover

    def test_a_failed_save_leaves_the_pin_unchanged(self):
        prefs = _js("preferences.js")
        block = prefs[prefs.index("export function bindSidebarPin"):]
        assert block.index("catch") < block.index("syncSidebarPin()")

    def test_the_old_checkbox_preference_control_is_gone(self):
        assert "g_sidebar_locked" not in (WEB / "index.html").read_text(encoding="utf-8") + _all_js()
        assert '"p_sidebar_locked"' not in _js("preferences.js")


class TestClientTimeDefault:
    def test_without_a_stored_zone_the_server_names_no_zone(self):
        container, _ = _container()
        body = system_time(container=container, _user=USER)
        assert body["display_timezone"] is None and body["timezone_configured"] is False

    def test_a_stored_zone_is_reported_even_when_it_is_utc(self):
        container, _ = _container()
        payload = _payload()
        payload.interface = InterfacePayload(display_timezone="UTC")
        settings_router.put_global_settings(payload, container=container, current_user=USER)
        body = system_time(container=container, _user=USER)
        assert (body["display_timezone"], body["timezone_configured"]) == ("UTC", True)

    def test_the_default_zone_labels_are_gone(self):
        text = (WEB / "index.html").read_text(encoding="utf-8") + _all_js()
        assert "(по умолчанию)" not in text and "зона браузера" not in text

    def test_timezone_is_configured_only_under_general_time_display(self):
        assert "g_timezone" in _inside("sp-general")
        assert "g_timezone" not in _inside("prefsModal")

    def test_the_topbar_label_is_empty_unless_an_administrator_chose_a_zone(self):
        ui = _js("ui.js")
        assert "label ?" in ui[ui.index("export function updateZoneLabels"):]
        assert 'label = state.source === "server" ? zone : ""' in _js("datetime.js")

    def test_the_settings_note_says_the_default_is_the_computers_time(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        assert "время его компьютера" in html and "сейчас используется UTC" not in html


class TestSingleTimeFormatter:
    def test_no_view_formats_dates_by_itself(self):
        for path in JS.glob("*.js"):
            if path.name == "datetime.js":
                continue
            text = path.read_text(encoding="utf-8")
            for banned in ("toLocaleString", "toLocaleTimeString", "toLocaleDateString", '"ru-RU"'):
                assert banned not in text, f"{path.name} uses {banned}"

    def test_journal_filters_are_read_in_the_display_zone(self):
        journal = _js("journal.js")
        assert "new Date(dateFrom)" not in journal and journal.count("wallTimeToUtcIso(dateFrom)") == 2

    def test_clock_uses_server_time(self):
        ui = _js("ui.js")
        clock = ui[ui.index("export function updateTopbarDateTime"):ui.index("export function updateZoneLabels")]
        assert "serverNow()" in clock and "new Date()" not in clock

    def test_views_rerender_when_the_zone_changes(self):
        app = _js("app.js")
        block = app[app.index("onZoneChange("):]
        block = block[:block.index("});")]
        for call in ("updateTopbarDateTime()", "renderEventFeed(true)", "loadJournal()", "updateZoneLabels()"):
            assert call in block, call

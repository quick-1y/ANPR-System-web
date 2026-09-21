"""Appearance and time in the interface (roadmap phase 7): the public
endpoint (7.1), instance/personal separation (7.4), and wiring invariants of
the browser code that the Node tests cannot see (7.2, 7.3, 7.5)."""
from __future__ import annotations

import inspect
import re
import threading
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api.deps import get_container, require_permission
from app.api.routers import preferences as prefs_router
from app.api.routers import public as public_router
from app.api.routers import settings as settings_router
from app.api.schemas import InterfacePayload
from tests.test_preferences import NO_PERMISSIONS, OTHER_USER, _patch, _with_user_db
from tests.test_reconnect_settings import USER, _container, _payload
from tests.test_settings_service import _Repo

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "app" / "web"
JS = WEB / "js"


def _js(name: str) -> str:
    return (JS / name).read_text(encoding="utf-8")


# ── 7.1 public endpoint ─────────────────────────────────────────────────

class TestPublicAppearance:
    def test_it_needs_no_token(self):
        params = inspect.signature(public_router.public_appearance).parameters
        assert list(params) == ["container", "_access"]
        assert params["container"].default.dependency is get_container
        from app.api.deps import _no_authentication

        assert params["_access"].default.dependency is _no_authentication
        route = next(r for r in public_router.router.routes if r.path == "/api/public/appearance")
        assert route.methods == {"GET"}

    def test_it_returns_the_two_defaults_and_nothing_else(self):
        container, _ = _container(_Repo({"interface.default_theme": "dark", "interface.display_timezone": "Europe/Minsk",
                                         "retention.events_retention_days": 3}))
        body = public_router.public_appearance(container=container)
        assert body == {"default_theme": "dark", "default_style": "graphite-minimal"}
        assert set(body) == {"default_theme", "default_style"}

    def test_it_falls_back_to_code_defaults_with_200_when_the_database_is_down(self):
        repo = _Repo()
        repo.down = True
        container, _ = _container(repo)
        assert public_router.public_appearance(container=container) == {
            "default_theme": "light", "default_style": "graphite-minimal",
        }

    def test_it_follows_the_administrators_change(self):
        container, repo = _container()
        payload = _payload()
        payload.interface = InterfacePayload(default_theme="dark", default_style="aurora")
        settings_router.put_global_settings(payload, container=container, current_user=USER)
        assert public_router.public_appearance(container=container) == {"default_theme": "dark", "default_style": "aurora"}

    def test_an_unauthenticated_request_never_waits_behind_a_slow_database(self):
        container, _ = _container()
        service = container.settings_service
        service._refresh_lock.acquire()  # another thread is stuck talking to the database
        try:
            result = {}
            worker = threading.Thread(target=lambda: result.setdefault("body", public_router.public_appearance(container=container)))
            worker.start()
            worker.join(timeout=2)
            assert not worker.is_alive(), "the public endpoint blocked on the database"
            assert result["body"]["default_theme"] == "light"
        finally:
            service._refresh_lock.release()

    def test_it_is_registered_and_documented(self):
        assert "include_router(public_router)" in (ROOT / "app" / "api" / "main.py").read_text(encoding="utf-8")
        assert "/api/public/appearance" in (ROOT / "docs" / "technical" / "endpoints.md").read_text(encoding="utf-8")


# ── 7.4 instance defaults vs personal preferences ───────────────────────

class TestInstanceVersusPersonal:
    def test_settings_page_writes_instance_defaults_to_app_settings(self):
        container, repo = _container()
        payload = _payload()
        payload.interface = InterfacePayload(default_theme="dark", default_style="aurora")
        settings_router.put_global_settings(payload, container=container, current_user=USER)
        assert repo.stored["interface.default_theme"] == "dark"
        assert repo.stored["interface.default_style"] == "aurora"
        body = settings_router.get_global_settings(container=container, current_user=USER)
        assert (body["interface"]["default_theme"], body["interface"]["default_style"]) == ("dark", "aurora")

    def test_a_user_without_the_settings_tab_gets_the_instance_look_and_can_set_their_own(self):
        container = _with_user_db({"interface.default_theme": "dark"})
        seen = prefs_router.get_my_preferences(container=container, user=NO_PERMISSIONS)["preferences"]["theme"]
        assert seen == {"value": "dark", "source": "instance"}
        mine = _patch(container, NO_PERMISSIONS, theme="light")["preferences"]["theme"]
        assert mine == {"value": "light", "source": "user"}
        # the instance default is untouched and other people still get it
        assert prefs_router.get_my_preferences(container=container, user=OTHER_USER)["preferences"]["theme"]["value"] == "dark"

    def test_that_user_cannot_change_the_instance_default(self):
        guard = inspect.signature(settings_router.put_global_settings).parameters["current_user"].default.dependency
        with pytest.raises(HTTPException) as exc:
            guard(current_user=NO_PERMISSIONS)
        assert exc.value.status_code == 403

    def test_the_personal_controls_live_outside_the_settings_tab(self):
        """Hiding the Settings tab must not remove the theme switch or the
        personal preferences (roadmap 4.11: appearance needs no permission)."""
        from html.parser import HTMLParser

        void = {"input", "img", "br", "hr", "meta", "link"}

        class Inside(HTMLParser):
            def __init__(self):
                super().__init__()
                self.stack, self.inside_settings, self.found = [], set(), set()

            def handle_starttag(self, tag, attrs):
                ident = dict(attrs).get("id")
                if ident:
                    self.found.add(ident)
                    if "tab-settings" in self.stack:
                        self.inside_settings.add(ident)
                if tag not in void:
                    self.stack.append(ident)

            def handle_endtag(self, tag):
                if tag not in void and self.stack:
                    self.stack.pop()

        parser = Inside()
        parser.feed((WEB / "index.html").read_text(encoding="utf-8"))
        for control in ("themeToggleBtn", "prefsBtn", "prefsModal", "p_theme", "p_style", "p_timezone", "p_sidebar_locked"):
            assert control in parser.found, control
            assert control not in parser.inside_settings, f"{control} is inside the Settings tab"

    def test_appearance_does_not_wait_for_the_settings_page_load(self):
        app = _js("app.js")
        assert app.index("appearance.signIn(") < app.index('hasPermission("tab:settings")')
        assert "loadGlobalSettings" not in _js("appearance.js") + _js("appearance-core.js")

    def test_instance_and_personal_controls_talk_to_different_endpoints(self):
        assert "/api/settings" in _js("settings.js") and "default_theme" in _js("settings.js")
        assert "/api/me/preferences" in _js("preferences.js")
        assert "applyTheme" not in _js("settings.js") and "applyStyle" not in _js("settings.js")


# ── 7.2 / 7.3 client storage and ownership ──────────────────────────────

class TestAppearanceOwnership:
    def test_old_cache_keys_are_gone(self):
        for path in JS.glob("*.js"):
            text = path.read_text(encoding="utf-8")
            assert "anpr_theme" not in text and "anpr_style" not in text, path.name

    def test_only_the_appearance_module_writes_a_look_to_storage(self):
        for path in JS.glob("*.js"):
            if path.name in ("appearance-core.js", "appearance.js"):
                continue
            text = path.read_text(encoding="utf-8")
            assert "anpr_appearance" not in text, path.name

    def test_appliers_are_pure_dom_functions(self):
        ui = _js("ui.js")
        body = ui[ui.index("export function applyStyle"):ui.index("export function getCurrentTheme")]
        assert "localStorage" not in body and "getElementById(\"g_" not in body

    def test_storage_access_is_guarded(self):
        core = _js("appearance-core.js")
        for call in ("getItem", "setItem", "removeItem"):
            for match in re.finditer(rf"storage\.{call}\(", core):
                window = core[max(0, match.start() - 160):match.start()]
                assert "try" in window, f"unguarded storage.{call}"

    def test_bootstrap_paints_before_the_network_and_logout_clears_the_cache(self):
        app = _js("app.js")
        assert app.index("appearance.boot(getTokenUserId())") < app.index("await getCurrentUser()")
        logout = app[app.index("logoutBtn.onclick"):]
        assert "appearance.signOut()" in logout.split("};")[0]

    def test_theme_toggle_saves_through_the_server(self):
        app = _js("app.js")
        assert "appearance.setPersonal({ theme:" in app
        assert "setVal(\"g_theme\"" not in app


# ── 7.5 one display time ────────────────────────────────────────────────

class TestSingleTimeFormatter:
    def test_no_view_formats_dates_by_itself(self):
        for path in JS.glob("*.js"):
            if path.name == "datetime.js":
                continue
            text = path.read_text(encoding="utf-8")
            for banned in ("toLocaleString", "toLocaleTimeString", "toLocaleDateString", '"ru-RU"'):
                assert banned not in text, f"{path.name} uses {banned}"

    def test_datetime_module_pins_zone_and_locale(self):
        text = _js("datetime.js")
        assert 'LOCALE = "ru-RU"' in text and "timeZone" in text
        assert "import " not in text.split("export const LOCALE")[0].replace("// ", "")

    def test_journal_filters_are_read_in_the_display_zone(self):
        journal = _js("journal.js")
        assert "new Date(dateFrom)" not in journal and "new Date(dateTo)" not in journal
        assert journal.count("wallTimeToUtcIso(dateFrom)") == 2 and journal.count("wallTimeToUtcIso(dateTo)") == 2

    def test_clock_uses_server_time(self):
        ui = _js("ui.js")
        clock = ui[ui.index("export function updateTopbarDateTime"):ui.index("export function updateZoneLabels")]
        assert "serverNow()" in clock and "new Date()" not in clock

    def test_views_rerender_when_the_zone_changes_without_a_reload(self):
        app = _js("app.js")
        block = app[app.index("onZoneChange("):]
        block = block[:block.index("});")]
        for call in ("updateTopbarDateTime()", "renderEventFeed(true)", "loadJournal()", "updateZoneLabels()"):
            assert call in block, call

    def test_zone_is_labelled_next_to_the_clock_and_above_the_journal(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        assert 'id="topbarTz"' in html and 'id="journalTz"' in html and 'id="tzNotConfiguredNote"' in html
        ui = _js("ui.js")
        assert "Время указано в зоне" in ui and "tz-warn" in ui

    def test_unconfigured_zone_notice_follows_the_server_flag(self):
        settings = _js("settings.js")
        assert "tzNotConfiguredNote" in settings and "timezone_configured" in settings

    def test_personal_zone_change_resyncs_the_clock_and_zone(self):
        app = _js("app.js")
        block = app[app.index('getElementById("p_timezone").onchange'):]
        assert "savePreferences({ timezone" in block.split("};")[0] and "syncServerTime(fetchServerTime)" in block.split("};")[0]

    def test_server_time_is_synced_periodically(self):
        assert "startServerTimeSync(fetchServerTime)" in _js("app.js")
        assert "setInterval" in _js("datetime.js")

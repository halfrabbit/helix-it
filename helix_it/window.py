from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk

from helix_it.db import Store
from helix_it.jobs import Jobs
from helix_it.pages.collections import CollectionsPage
from helix_it.pages.dashboard import DashboardPage
from helix_it.pages.deploy import DeployPage
from helix_it.pages.inventory import InventoryPage
from helix_it.pages.network import NetworkPage
from helix_it.pages.people import PeoplePage
from helix_it.pages.reports import ReportsPage
from helix_it.pages.settings import SettingsPage
from helix_it.pages.software import SoftwarePage
from helix_it.pages.tickets import TicketsPage

NAV = [
    ("dashboard", "Dashboard"),
    ("inventory", "Inventory"),
    ("collections", "Collections"),
    ("deploy", "Deploy"),
    ("tickets", "Help desk"),
    ("network", "Network"),
    ("software", "Software"),
    ("people", "People"),
    ("reports", "Reports"),
    ("settings", "Settings"),
]


class HelixWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, store: Store) -> None:
        super().__init__(application=app, title="Helix IT")
        self.store = store
        self.jobs = Jobs(store)
        self.set_default_size(1280, 820)
        self.add_css_class("helix")
        self._load_css()

        split = Adw.OverlaySplitView()
        split.set_min_sidebar_width(248)
        split.set_max_sidebar_width(280)
        split.set_show_sidebar(True)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.pages = {
            "dashboard": DashboardPage(store),
            "inventory": InventoryPage(store, self.jobs),
            "collections": CollectionsPage(store, self.jobs),
            "deploy": DeployPage(store, self.jobs),
            "tickets": TicketsPage(store),
            "network": NetworkPage(store, on_scanned=self.refresh_all),
            "software": SoftwarePage(store),
            "people": PeoplePage(store),
            "reports": ReportsPage(store),
            "settings": SettingsPage(store, self.jobs, on_reset=self.refresh_all),
        }
        for name, page in self.pages.items():
            self.stack.add_named(page, name)

        content = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toggle = Gtk.Button.new_from_icon_name("sidebar-show-symbolic")
        toggle.connect("clicked", lambda *_: split.set_show_sidebar(not split.get_show_sidebar()))
        header.pack_start(toggle)
        self.title = Adw.WindowTitle(title="Helix IT", subtitle=store.get_meta("org_name", "Local IT console") or "")
        header.set_title_widget(self.title)
        scan = Gtk.Button(label="Scan LAN")
        scan.add_css_class("suggested-action")
        scan.connect("clicked", self._scan)
        header.pack_end(scan)
        content.add_top_bar(header)
        content.set_content(self.stack)

        split.set_sidebar(self._sidebar())
        split.set_content(content)
        self.set_content(split)
        self._bind_shortcuts()
        GLib.timeout_add_seconds(60, self._tick_schedules)

    def _tick_schedules(self) -> bool:
        self.jobs.kick_schedules(self.refresh_all)
        return True

    def _sidebar(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.add_css_class("sidebar")
        brand = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        brand.add_css_class("brand-box")
        mark = Gtk.Label(label="LOCAL IT CONSOLE", xalign=0)
        mark.add_css_class("brand-mark")
        title = Gtk.Label(label="Helix IT", xalign=0)
        title.add_css_class("brand-title")
        sub = Gtk.Label(label="Inventory · deploy · directory", xalign=0)
        sub.add_css_class("brand-sub")
        brand.append(mark)
        brand.append(title)
        brand.append(sub)
        box.append(brand)

        self.nav = Gtk.ListBox()
        self.nav.add_css_class("nav-list")
        self.nav.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.nav.connect("row-activated", self._on_nav)
        for key, label in NAV:
            row = Gtk.ListBoxRow()
            row.page_name = key
            row.set_child(Gtk.Label(label=label, xalign=0))
            self.nav.append(row)
        self.nav.select_row(self.nav.get_row_at_index(0))
        box.append(self.nav)
        return box

    def _on_nav(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        name = row.page_name
        self.stack.set_visible_child_name(name)
        page = self.pages[name]
        if hasattr(page, "refresh"):
            page.refresh()
        subtitle = dict(NAV)[name]
        self.title.set_subtitle(subtitle)

    def _scan(self, *_args) -> None:
        self.stack.set_visible_child_name("network")
        row = next(r for r in self._nav_rows() if r.page_name == "network")
        self.nav.select_row(row)
        self.pages["network"]._start_scan()

    def _nav_rows(self):
        index = 0
        while True:
            row = self.nav.get_row_at_index(index)
            if row is None:
                break
            yield row
            index += 1

    def refresh_all(self) -> None:
        for page in self.pages.values():
            if hasattr(page, "refresh"):
                page.refresh()
        self.title.set_subtitle(self.store.get_meta("org_name", "") or "Helix IT")

    def _bind_shortcuts(self) -> None:
        controller = Gtk.ShortcutController()
        for index, (name, _label) in enumerate(NAV, start=1):
            trigger = Gtk.ShortcutTrigger.parse_string(f"<Ctrl>{index % 10}")
            action = Gtk.CallbackAction.new(lambda *_a, page=name: self._goto(page))
            controller.add_shortcut(Gtk.Shortcut.new(trigger, action))
        self.add_controller(controller)

    def _goto(self, name: str) -> bool:
        self.stack.set_visible_child_name(name)
        for item in self._nav_rows():
            if item.page_name == name:
                self.nav.select_row(item)
                break
        page = self.pages[name]
        if hasattr(page, "refresh"):
            page.refresh()
        return True

    def _load_css(self) -> None:
        css_path = Path(__file__).with_name("style.css")
        provider = Gtk.CssProvider()
        provider.load_from_path(str(css_path))
        display = Gdk.Display.get_default()
        Gtk.StyleContext.add_provider_for_display(
            display,
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

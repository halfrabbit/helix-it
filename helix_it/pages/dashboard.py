from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from helix_it.db import Store
from helix_it.widgets import card, heading, muted, stat_card, status_badge


class DashboardPage(Gtk.Box):
    def __init__(self, store: Store) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.store = store
        self.add_css_class("page")
        self.append(heading("Dashboard"))
        self.sub = muted("Inventory, software deploy, and Active Directory from this Linux console.")
        self.append(self.sub)
        self.stats = Gtk.FlowBox()
        self.stats.set_selection_mode(Gtk.SelectionMode.NONE)
        self.stats.set_max_children_per_line(4)
        self.stats.add_css_class("stat-grid")
        self.append(self.stats)
        split = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        split.set_homogeneous(True)
        self.tickets = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.activity = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        split.append(card("Open tickets", self.tickets))
        split.append(card("Activity", self.activity))
        self.append(split)
        self.refresh()

    def refresh(self) -> None:
        org = self.store.get_meta("org_name", "Helix IT")
        self.sub.set_text(f"{org} · local console on this Linux workstation")
        while child := self.stats.get_first_child():
            self.stats.remove(child)
        stats = self.store.stats()
        cards = [
            ("Devices", str(stats["devices"]), f"{stats['online']} online"),
            ("Directory", str(stats["directory"]), f"{stats['windows']} Windows"),
            ("Open tickets", str(stats["open_tickets"]), f"{stats['critical']} critical"),
            ("Needs attention", str(stats["scan_failed"] + stats["deploy_failed"]), f"{stats['deploy_failed']} deploy failures"),
        ]
        for item in cards:
            self.stats.append(stat_card(*item))
        self._fill(self.tickets, self.store.tickets(status="active")[:6], ticket=True)
        self._fill(self.activity, self.store.activity(), ticket=False)

    def _fill(self, box: Gtk.Box, rows, ticket: bool) -> None:
        while child := box.get_first_child():
            box.remove(child)
        if not rows:
            box.append(muted("Nothing here yet."))
            return
        for row in rows:
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            if ticket:
                line.append(status_badge(row["status"]))
                label = Gtk.Label(label=f"#{row['number']}  {row['title']}", xalign=0)
            else:
                label = Gtk.Label(label=row["message"], xalign=0)
            label.set_hexpand(True)
            label.set_wrap(True)
            line.append(label)
            box.append(line)

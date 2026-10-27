from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from helix_it.db import Store
from helix_it.widgets import BarChart, card, heading, muted


class ReportsPage(Gtk.Box):
    def __init__(self, store: Store) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.store = store
        self.add_css_class("page")
        self.append(heading("Reports"))
        self.append(muted("Counts from the local database — scans, deployments, and the directory sync."))
        self.types = BarChart([])
        self.priorities = BarChart([])
        self.oses = BarChart([])
        self.scans = BarChart([])
        self.deploys = BarChart([])
        grid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        grid.append(card("Devices by type", self.types))
        grid.append(card("Operating systems", self.oses))
        grid.append(card("Inventory scans", self.scans))
        grid.append(card("Deployment results", self.deploys))
        grid.append(card("Open tickets by priority", self.priorities))
        self.append(Gtk.ScrolledWindow(vexpand=True, child=grid))
        self.refresh()

    def refresh(self) -> None:
        self.types.set_rows(self.store.type_counts())
        self.priorities.set_rows(self.store.ticket_priority_counts())
        self.oses.set_rows(self.store.os_counts())
        self.scans.set_rows(self.store.scan_status_counts())
        self.deploys.set_rows(self.store.deployment_status_counts())

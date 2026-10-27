from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from helix_it.db import Store
from helix_it.widgets import heading, muted, search_entry


class SoftwarePage(Gtk.Box):
    def __init__(self, store: Store) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.store = store
        self.query = ""
        self.add_css_class("page")
        self.append(heading("Software"))
        self.append(muted("Titles collected from Windows scans, this Linux console, and the sample inventory."))
        self.append(search_entry("Search titles…", self._on_search))
        self.listbox = Gtk.ListBox()
        self.listbox.add_css_class("plain")
        scroller = Gtk.ScrolledWindow(vexpand=True, child=self.listbox)
        self.append(scroller)
        self.refresh()

    def _on_search(self, text: str) -> None:
        self.query = text
        self.refresh()

    def refresh(self) -> None:
        self.listbox.remove_all()
        rows = self.store.software_summary(self.query)
        if not rows:
            self.listbox.append(Gtk.ListBoxRow(child=muted("No software recorded yet.")))
            return
        for row in rows:
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
            names.append(Gtk.Label(label=row["name"], xalign=0))
            names.append(
                Gtk.Label(
                    label=f"{row['publisher'] or 'Unknown publisher'} · {row['versions'] or '—'}",
                    xalign=0,
                    css_classes=["muted"],
                )
            )
            box.append(names)
            box.append(Gtk.Label(label=f"{row['installs']} installs"))
            self.listbox.append(Gtk.ListBoxRow(child=box))

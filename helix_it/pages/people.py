from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from helix_it.db import Store
from helix_it.widgets import heading, muted, search_entry


class PeoplePage(Gtk.Box):
    def __init__(self, store: Store) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.store = store
        self.query = ""
        self.add_css_class("page")
        self.append(heading("People"))
        self.append(muted("Users tied to assets and tickets."))
        tools = Gtk.Box(spacing=8)
        tools.append(search_entry("Search people…", self._on_search))
        add = Gtk.Button(label="Add person", css_classes=["suggested-action"])
        add.connect("clicked", lambda *_: self._add())
        tools.append(add)
        self.append(tools)
        self.listbox = Gtk.ListBox()
        self.listbox.add_css_class("plain")
        self.append(Gtk.ScrolledWindow(vexpand=True, child=self.listbox))
        self.refresh()

    def _on_search(self, text: str) -> None:
        self.query = text
        self.refresh()

    def refresh(self) -> None:
        self.listbox.remove_all()
        for row in self.store.people(self.query):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            box.append(Gtk.Label(label=row["name"], xalign=0))
            box.append(
                Gtk.Label(
                    label=f"{row['title'] or ''} · {row['department'] or ''} · {row['email'] or ''}",
                    xalign=0,
                    css_classes=["muted"],
                )
            )
            box.append(
                Gtk.Label(
                    label=f"{row['devices']} devices · {row['open_tickets']} open tickets",
                    xalign=0,
                    css_classes=["muted"],
                )
            )
            self.listbox.append(Gtk.ListBoxRow(child=box))
        if not self.listbox.get_first_child():
            self.listbox.append(Gtk.ListBoxRow(child=muted("No people yet.")))

    def _add(self) -> None:
        dialog = Adw.Dialog(title="Add person", content_width=420)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        name = Gtk.Entry(placeholder_text="Name")
        email = Gtk.Entry(placeholder_text="Email")
        department = Gtk.Entry(placeholder_text="Department")
        title = Gtk.Entry(placeholder_text="Title")
        for widget in (name, email, department, title):
            box.append(widget)
        save = Gtk.Button(label="Save", css_classes=["suggested-action"])

        def create(_btn: Gtk.Button) -> None:
            if not name.get_text().strip():
                return
            self.store.add_person(
                name.get_text().strip(),
                email.get_text().strip(),
                department.get_text().strip(),
                title.get_text().strip(),
            )
            dialog.close()
            self.refresh()

        save.connect("clicked", create)
        box.append(save)
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        toolbar.set_content(box)
        dialog.set_child(toolbar)
        dialog.present(self.get_root())

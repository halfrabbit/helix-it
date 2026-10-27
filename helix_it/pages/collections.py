from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from helix_it.collections import FIELDS, OPS
from helix_it.db import Store
from helix_it.pages.common import alert, confirm, deploy_dialog
from helix_it.widgets import heading, muted


class CollectionsPage(Gtk.Box):
    def __init__(self, store: Store, jobs) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.store = store
        self.jobs = jobs
        self.selected_id: int | None = None
        self.add_css_class("page")
        self.append(heading("Collections"))
        self.append(muted("Dynamic filters and pinned computers, in the same role as PDQ collections."))
        tools = Gtk.Box(spacing=8)
        tools.add_css_class("toolbar-gap")
        add = Gtk.Button(label="New collection", css_classes=["suggested-action"])
        add.connect("clicked", lambda *_: self._edit_dialog())
        scan = Gtk.Button(label="Scan")
        scan.connect("clicked", lambda *_: self._scan())
        deploy = Gtk.Button(label="Deploy")
        deploy.connect("clicked", lambda *_: self._deploy())
        delete = Gtk.Button(label="Delete", css_classes=["destructive-action"])
        delete.connect("clicked", lambda *_: self._delete())
        tools.append(add)
        tools.append(scan)
        tools.append(deploy)
        tools.append(delete)
        self.status = Gtk.Label(label="", xalign=0, css_classes=["muted"])
        tools.append(self.status)
        self.append(tools)

        split = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        split.set_vexpand(True)
        self.listbox = Gtk.ListBox(css_classes=["plain"])
        self.listbox.connect("row-selected", self._on_row)
        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True, child=self.listbox)
        self.detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.detail.set_size_request(460, -1)
        detail_scroll = Gtk.ScrolledWindow(vexpand=True, child=self.detail)
        detail_scroll.set_size_request(480, -1)
        split.append(scroller)
        split.append(detail_scroll)
        self.append(split)
        self.refresh()

    def _on_row(self, _list, row) -> None:
        if row is None or not hasattr(row, "collection_id"):
            return
        if self.selected_id == row.collection_id and self.detail.get_first_child() is not None:
            return
        self._show(row.collection_id)

    def refresh(self) -> None:
        selected = self.selected_id
        self.listbox.remove_all()
        rows = self.store.collections()
        chosen = None
        for row in rows:
            count = len(self.store.collection_device_ids(int(row["id"])))
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            box.append(Gtk.Label(label=row["name"], xalign=0))
            box.append(Gtk.Label(label=f"{row['kind']} · {count} computers", xalign=0, css_classes=["muted"]))
            item = Gtk.ListBoxRow(child=box)
            item.collection_id = int(row["id"])
            self.listbox.append(item)
            if selected == int(row["id"]):
                chosen = item
        if chosen:
            self.listbox.select_row(chosen)
            self._show(selected)
        elif rows:
            self._show(int(rows[0]["id"]))
        else:
            self._show(None)

    def _show(self, collection_id: int | None) -> None:
        self.selected_id = collection_id
        while child := self.detail.get_first_child():
            self.detail.remove(child)
        if collection_id is None:
            self.detail.append(muted("No collections yet."))
            return
        col = self.store.collection(collection_id)
        if not col:
            return
        self.name = Gtk.Entry(text=col["name"] or "")
        self.description = Gtk.Entry(text=col["description"] or "")
        self.kind = Gtk.ComboBoxText()
        for kind in ("dynamic", "static", "mixed"):
            self.kind.append(kind, kind)
        self.kind.set_active_id(col["kind"] or "dynamic")
        self.match = Gtk.ComboBoxText()
        self.match.append("all", "Match all filters")
        self.match.append("any", "Match any filter")
        self.match.set_active_id(col["match_mode"] or "all")
        save = Gtk.Button(label="Save collection")
        save.connect("clicked", lambda *_: self._save(collection_id))
        self.detail.append(self.name)
        self.detail.append(self.description)
        self.detail.append(self.kind)
        self.detail.append(self.match)
        self.detail.append(save)
        self.detail.append(Gtk.Label(label="Filters", xalign=0, css_classes=["card-title"]))
        for filt in self.store.collection_filters(collection_id):
            row = Gtk.Box(spacing=8)
            row.append(
                Gtk.Label(
                    label=f"{filt['field']} {filt['op']} {filt['value']}",
                    xalign=0,
                    hexpand=True,
                )
            )
            remove = Gtk.Button(label="Remove")
            remove.connect("clicked", lambda *_b, filter_id=int(filt["id"]): self._remove_filter(filter_id))
            row.append(remove)
            self.detail.append(row)
        self.field = Gtk.ComboBoxText()
        for key, label in FIELDS:
            self.field.append(key, label)
        self.field.set_active(0)
        self.op = Gtk.ComboBoxText()
        for key, label in OPS:
            self.op.append(key, label)
        self.op.set_active(0)
        self.value = Gtk.Entry()
        self.value.set_placeholder_text("Value")
        add = Gtk.Button(label="Add filter")
        add.connect("clicked", lambda *_: self._add_filter(collection_id))
        self.detail.append(self.field)
        self.detail.append(self.op)
        self.detail.append(self.value)
        self.detail.append(add)

        if (col["kind"] or "") in {"static", "mixed"}:
            self.detail.append(Gtk.Label(label="Pinned computers", xalign=0, css_classes=["card-title"]))
            pinned = self.store.static_member_ids(collection_id)
            self.member = Gtk.ComboBoxText()
            for device in self.store.devices():
                if int(device["id"]) not in pinned:
                    self.member.append(str(device["id"]), device["name"])
            self.member.set_active(0)
            pin = Gtk.Button(label="Pin computer")
            pin.connect("clicked", lambda *_: self._pin(collection_id))
            self.detail.append(self.member)
            self.detail.append(pin)
            names = {int(device["id"]): device["name"] for device in self.store.devices()}
            for device_id in sorted(pinned):
                row = Gtk.Box(spacing=8)
                row.append(Gtk.Label(label=names.get(device_id, str(device_id)), xalign=0, hexpand=True))
                remove = Gtk.Button(label="Unpin")
                remove.connect(
                    "clicked",
                    lambda *_b, did=device_id: self._unpin(collection_id, did),
                )
                row.append(remove)
                self.detail.append(row)
        members = self.store.collection_devices(collection_id)
        self.detail.append(Gtk.Label(label=f"Members ({len(members)})", xalign=0, css_classes=["card-title"]))
        for device in members[:80]:
            label = " · ".join(part for part in (device["name"], device["ip"], device["os"]) if part)
            self.detail.append(Gtk.Label(label=label, xalign=0))
        if len(members) > 80:
            self.detail.append(muted(f"Showing 80 of {len(members)}."))

    def _save(self, collection_id: int) -> None:
        self.store.update_collection(
            collection_id,
            name=self.name.get_text().strip() or "Collection",
            description=self.description.get_text().strip(),
            kind=self.kind.get_active_id() or "dynamic",
            match_mode=self.match.get_active_id() or "all",
        )
        self.refresh()

    def _add_filter(self, collection_id: int) -> None:
        self.store.add_filter(
            collection_id,
            self.field.get_active_id() or "name",
            self.op.get_active_id() or "contains",
            self.value.get_text().strip(),
        )
        self.refresh()

    def _remove_filter(self, filter_id: int) -> None:
        self.store.delete_filter(filter_id)
        self.refresh()

    def _pin(self, collection_id: int) -> None:
        device_id = self.member.get_active_id()
        if not device_id:
            return
        self.store.add_member(collection_id, int(device_id))
        self.refresh()

    def _unpin(self, collection_id: int, device_id: int) -> None:
        self.store.remove_member(collection_id, device_id)
        self.refresh()

    def _scan(self) -> None:
        if not self.selected_id:
            return
        ids = self.store.collection_device_ids(self.selected_id)
        self.status.set_text(f"Scanning {len(ids)}…")
        self.jobs.scan(ids, self.status.set_text, self._finished)

    def _deploy(self) -> None:
        if not self.selected_id:
            return
        deploy_dialog(
            self,
            self.store,
            self.jobs,
            self._finished,
            collection_id=self.selected_id,
            on_progress=self.status.set_text,
        )

    def _finished(self, error: str | None) -> None:
        self.status.set_text(error or "Finished.")
        if error:
            alert(self, error)
        self.refresh()

    def _delete(self) -> None:
        if not self.selected_id:
            return
        collection_id = self.selected_id

        def go() -> None:
            self.store.delete_collection(collection_id)
            self.selected_id = None
            self.refresh()

        confirm(self, "Delete this collection? Computers stay in inventory.", go)

    def _edit_dialog(self) -> None:
        dialog = Adw.Dialog()
        dialog.set_title("New collection")
        dialog.set_content_width(420)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        name = Gtk.Entry()
        name.set_placeholder_text("Name")
        kind = Gtk.ComboBoxText()
        for item in ("dynamic", "static", "mixed"):
            kind.append(item, item)
        kind.set_active_id("dynamic")
        save = Gtk.Button(label="Create", css_classes=["suggested-action"])

        def on_save(_btn) -> None:
            title = name.get_text().strip()
            if not title:
                return
            try:
                self.selected_id = self.store.add_collection(title, kind.get_active_id() or "dynamic", "", "all")
            except Exception as exc:
                alert(self, str(exc))
                return
            dialog.close()
            self.refresh()

        save.connect("clicked", on_save)
        box.append(name)
        box.append(kind)
        box.append(save)
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        toolbar.set_content(box)
        dialog.set_child(toolbar)
        dialog.present(self.get_root())

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from helix_it.db import Store
from helix_it.widgets import heading, muted, pill_filters, priority_badge, search_entry, status_badge

STATUSES = ["active", "new", "open", "waiting", "closed", "all"]
PRIORITIES = ["low", "medium", "high", "critical"]
WORKFLOW = ["new", "open", "waiting", "closed"]


class TicketsPage(Gtk.Box):
    def __init__(self, store: Store) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.store = store
        self.filter = "active"
        self.query = ""
        self.selected_id: int | None = None
        self.add_css_class("page")
        self.append(heading("Help desk"))
        self.append(muted("Tickets stay on this machine. No cloud, no vendor lock-in."))

        tools = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        tools.append(search_entry("Search tickets…", self._on_search))
        add = Gtk.Button(label="New ticket")
        add.add_css_class("suggested-action")
        add.connect("clicked", lambda *_: self._new_ticket())
        tools.append(add)
        self.append(tools)
        self.append(pill_filters(STATUSES, self._on_filter))

        split = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self.listbox = Gtk.ListBox()
        self.listbox.add_css_class("tickets")
        self.listbox.connect("row-activated", self._on_row)
        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True, child=self.listbox)
        self.detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        detail_scroll = Gtk.ScrolledWindow(child=self.detail)
        detail_scroll.set_size_request(380, -1)
        split.append(scroller)
        split.append(detail_scroll)
        self.append(split)
        self.refresh()

    def _on_search(self, text: str) -> None:
        self.query = text
        self.refresh()

    def _on_filter(self, name: str) -> None:
        self.filter = name
        self.refresh()

    def refresh(self) -> None:
        rows = self.store.tickets(self.filter, self.query)
        self.listbox.remove_all()
        for row in rows:
            item = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title = Gtk.Label(label=f"#{row['number']}  {row['title']}", xalign=0, hexpand=True)
            title.set_wrap(True)
            top.append(title)
            top.append(priority_badge(row["priority"]))
            top.append(status_badge(row["status"]))
            item.append(top)
            meta = " · ".join(
                part
                for part in (row["requester"], row["assignee"], row["device_name"])
                if part
            )
            if meta:
                item.append(Gtk.Label(label=meta, xalign=0, css_classes=["muted"]))
            list_row = Gtk.ListBoxRow(child=item)
            list_row.ticket_id = int(row["id"])
            self.listbox.append(list_row)
        if rows:
            self._show(int(rows[0]["id"]))
        else:
            self._show(None)

    def _on_row(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        self._show(row.ticket_id)

    def _show(self, ticket_id: int | None) -> None:
        self.selected_id = ticket_id
        while child := self.detail.get_first_child():
            self.detail.remove(child)
        if ticket_id is None:
            self.detail.append(muted("No tickets in this view."))
            return
        ticket = self.store.ticket(ticket_id)
        if not ticket:
            return
        title = Gtk.Label(label=f"#{ticket['number']}  {ticket['title']}", xalign=0, wrap=True)
        title.add_css_class("detail-title")
        self.detail.append(title)
        chips = Gtk.Box(spacing=8)
        chips.append(status_badge(ticket["status"]))
        chips.append(priority_badge(ticket["priority"]))
        self.detail.append(chips)
        self.detail.append(Gtk.Label(label=ticket["description"] or "", xalign=0, wrap=True))
        self.detail.append(
            Gtk.Label(
                label=f"Requester: {ticket['requester'] or '—'}  ·  Assignee: {ticket['assignee'] or 'Unassigned'}",
                xalign=0,
                css_classes=["muted"],
                wrap=True,
            )
        )
        if ticket["device_name"]:
            self.detail.append(Gtk.Label(label=f"Asset: {ticket['device_name']}", xalign=0))

        workflow = Gtk.Box(spacing=6)
        for status in WORKFLOW:
            button = Gtk.Button(label=status.title())
            if status == ticket["status"]:
                button.add_css_class("suggested-action")
            button.connect("clicked", self._set_status, ticket_id, status)
            workflow.append(button)
        self.detail.append(workflow)

        self.detail.append(Gtk.Label(label="Comments", xalign=0, css_classes=["card-title"]))
        for comment in self.store.comments(ticket_id):
            block = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            block.append(Gtk.Label(label=f"{comment['author']} · {comment['created_at']}", xalign=0, css_classes=["muted"]))
            block.append(Gtk.Label(label=comment["body"], xalign=0, wrap=True))
            self.detail.append(block)

        entry = Gtk.Entry()
        entry.set_placeholder_text("Add a comment…")
        save = Gtk.Button(label="Comment")

        def add_comment(_btn: Gtk.Button) -> None:
            body = entry.get_text().strip()
            if not body:
                return
            tech = self.store.get_meta("tech_name", "IT Desk") or "IT Desk"
            self.store.add_comment(ticket_id, tech, body)
            self._show(ticket_id)

        save.connect("clicked", add_comment)
        row = Gtk.Box(spacing=8)
        entry.set_hexpand(True)
        row.append(entry)
        row.append(save)
        self.detail.append(row)

    def _set_status(self, _btn: Gtk.Button, ticket_id: int, status: str) -> None:
        self.store.update_ticket(ticket_id, status=status)
        self.refresh()
        self._show(ticket_id)

    def _new_ticket(self) -> None:
        dialog = Adw.Dialog(title="New ticket", content_width=480)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        title = Gtk.Entry(placeholder_text="Title")
        body = Gtk.Entry(placeholder_text="What happened?")
        priority = Gtk.ComboBoxText()
        for item in PRIORITIES:
            priority.append(item, item.title())
        priority.set_active_id("medium")
        people = self.store.people()
        requester = Gtk.ComboBoxText()
        requester.append("", "No requester")
        for person in people:
            requester.append(str(person["id"]), person["name"])
        requester.set_active_id("")
        devices = self.store.devices()
        device = Gtk.ComboBoxText()
        device.append("", "No asset")
        for item in devices:
            device.append(str(item["id"]), item["name"])
        device.set_active_id("")
        assignee = Gtk.Entry(placeholder_text="Assignee")
        for widget in (title, body, priority, requester, device, assignee):
            box.append(widget)
        save = Gtk.Button(label="Create", css_classes=["suggested-action"])

        def create(_btn: Gtk.Button) -> None:
            if not title.get_text().strip():
                return
            req = requester.get_active_id()
            dev = device.get_active_id()
            self.store.add_ticket(
                title.get_text().strip(),
                body.get_text().strip(),
                priority.get_active_id() or "medium",
                int(req) if req else None,
                assignee.get_text().strip(),
                int(dev) if dev else None,
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

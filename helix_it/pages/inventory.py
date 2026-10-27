from __future__ import annotations

import json

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from helix_it import remote, scanner
from helix_it.db import Store
from helix_it.pages.common import alert, confirm, deploy_dialog, log_dialog
from helix_it.widgets import heading, kv_row, muted, pill_filters, search_entry, status_badge


TYPES = ["all", "computer", "server", "network", "printer", "other"]


class InventoryPage(Gtk.Box):
    def __init__(self, store: Store, jobs) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.store = store
        self.jobs = jobs
        self.filter = "all"
        self.query = ""
        self.selected_id: int | None = None
        self._loading = False
        self.add_css_class("page")
        self.append(heading("Inventory"))
        self.append(muted("Computers from Active Directory and scans. Windows targets are read over WinRM."))

        tools = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        tools.add_css_class("toolbar-gap")
        tools.append(search_entry("Search name, IP, OS, OU…", self._on_search))
        self.collection = Gtk.ComboBoxText()
        self.collection.connect("changed", self._on_collection)
        tools.append(self.collection)
        self.append(tools)

        actions = Gtk.Box(spacing=8)
        add = Gtk.Button(label="Add device")
        add.connect("clicked", lambda *_: self._edit_dialog())
        scan = Gtk.Button(label="Scan", css_classes=["suggested-action"])
        scan.connect("clicked", lambda *_: self._scan_selected())
        scan_all = Gtk.Button(label="Scan Windows")
        scan_all.connect("clicked", lambda *_: self._scan_windows())
        deploy = Gtk.Button(label="Deploy")
        deploy.connect("clicked", lambda *_: self._deploy())
        command = Gtk.Button(label="Command")
        command.connect("clicked", lambda *_: self._tool_dialog("command"))
        powershell = Gtk.Button(label="PowerShell")
        powershell.connect("clicked", lambda *_: self._tool_dialog("powershell"))
        reboot = Gtk.Button(label="Reboot")
        reboot.connect("clicked", lambda *_: self._reboot())
        wake = Gtk.Button(label="Wake")
        wake.connect("clicked", lambda *_: self._wake())
        for button in (add, scan, scan_all, deploy, command, powershell, reboot, wake):
            actions.append(button)
        self.append(actions)
        self.status = Gtk.Label(label="", xalign=0, css_classes=["muted"])
        self.append(self.status)
        self.append(pill_filters(TYPES, self._on_filter))

        split = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        split.set_vexpand(True)
        self.listbox = Gtk.ListBox(css_classes=["inventory"])
        self.listbox.connect("row-selected", self._on_row)
        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True, child=self.listbox)
        self.detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.detail.set_size_request(420, -1)
        split.append(scroller)
        split.append(self.detail)
        self.append(split)
        self.refresh()

    def _on_search(self, text: str) -> None:
        self.query = text
        self.refresh()

    def _on_filter(self, name: str) -> None:
        self.filter = name
        self.refresh()

    def _on_collection(self, *_args) -> None:
        if self._loading:
            return
        self.refresh()

    def _on_row(self, _list, row) -> None:
        if row is None or not hasattr(row, "device_id"):
            return
        if self.selected_id == row.device_id and self.detail.get_first_child() is not None:
            return
        self._show(row.device_id)

    def refresh(self) -> None:
        self._reload_collections()
        selected = self.selected_id
        rows = self.store.devices(None if self.filter == "all" else self.filter, self.query)
        collection_id = self.collection.get_active_id()
        if collection_id and collection_id != "all":
            allowed = set(self.store.collection_device_ids(int(collection_id)))
            rows = [row for row in rows if int(row["id"]) in allowed]
        self.listbox.remove_all()
        chosen = None
        for row in rows:
            item = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            item.set_margin_start(4)
            item.set_margin_end(4)
            names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
            title = Gtk.Label(label=row["name"], xalign=0, css_classes=["heading"])
            bits = [part for part in (row["ip"], row["os"], row["ou"] or row["type"]) if part]
            names.append(title)
            names.append(Gtk.Label(label=" · ".join(bits), xalign=0, css_classes=["muted"]))
            item.append(names)
            item.append(status_badge(row["status"]))
            if int(row["ad_disabled"] or 0):
                item.append(Gtk.Label(label="disabled", css_classes=["muted"]))
            list_row = Gtk.ListBoxRow(child=item)
            list_row.device_id = int(row["id"])
            self.listbox.append(list_row)
            if selected == int(row["id"]):
                chosen = list_row
        if chosen:
            self.listbox.select_row(chosen)
            self._show(selected)
        elif rows:
            self._show(int(rows[0]["id"]))
        else:
            self._show(None)

    def _reload_collections(self) -> None:
        current = self.collection.get_active_id()
        self._loading = True
        self.collection.remove_all()
        self.collection.append("all", "All computers")
        for row in self.store.collections():
            self.collection.append(str(row["id"]), row["name"])
        if not current or not self.collection.set_active_id(current):
            self.collection.set_active_id("all")
        self._loading = False

    def _show(self, device_id: int | None) -> None:
        self.selected_id = device_id
        while child := self.detail.get_first_child():
            self.detail.remove(child)
        if device_id is None:
            self.detail.append(muted("No devices match."))
            return
        device = self.store.device(device_id)
        if not device:
            return
        title = Gtk.Label(label=device["name"], xalign=0, css_classes=["detail-title"])
        self.detail.append(title)
        badges = Gtk.Box(spacing=6)
        badges.append(status_badge(device["status"]))
        if device["scan_status"]:
            badges.append(Gtk.Label(label=f"scan {device['scan_status']}", css_classes=["muted"]))
        self.detail.append(badges)
        if device["scan_error"]:
            self.detail.append(muted(device["scan_error"]))

        book = Gtk.Notebook()
        book.set_vexpand(True)
        book.append_page(self._overview(device), Gtk.Label(label="Overview"))
        book.append_page(self._table(self.store.device_software(device_id), lambda row: f"{row['name']}  {row['version'] or ''}  {row['publisher'] or ''}".strip(), "No applications recorded."), Gtk.Label(label="Apps"))
        book.append_page(self._table(self.store.child_rows("hotfixes", device_id), lambda row: f"{row['hotfix_id']}  {row['installed_on'] or ''}", "No hotfixes recorded."), Gtk.Label(label="Updates"))
        book.append_page(self._table(self.store.child_rows("services", device_id), lambda row: f"{row['name']} — {row['status'] or ''} — {row['start_mode'] or ''}", "No services recorded."), Gtk.Label(label="Services"))
        book.append_page(self._hardware(device_id, device), Gtk.Label(label="Hardware"))
        book.append_page(self._people_and_more(device_id, device), Gtk.Label(label="More"))
        self.detail.append(book)

        buttons = Gtk.Box(spacing=8)
        edit = Gtk.Button(label="Edit")
        edit.connect("clicked", lambda *_: self._edit_dialog(device_id))
        delete = Gtk.Button(label="Remove", css_classes=["destructive-action"])
        delete.connect("clicked", lambda *_: self._delete(device_id))
        buttons.append(edit)
        buttons.append(delete)
        self.detail.append(buttons)

    def _overview(self, device) -> Gtk.ScrolledWindow:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_top=8, margin_start=4, margin_end=4)
        for key, label in (
            ("hostname", "Hostname"),
            ("ip", "IP"),
            ("mac", "MAC"),
            ("domain", "Domain"),
            ("ou", "OU"),
            ("dn", "DN"),
            ("type", "Type"),
            ("os", "OS"),
            ("os_version", "OS version"),
            ("architecture", "Architecture"),
            ("manufacturer", "Vendor"),
            ("model", "Model"),
            ("serial", "Serial"),
            ("cpu", "CPU"),
            ("current_user", "Current user"),
            ("owner_name", "Owner"),
            ("last_boot", "Last boot"),
            ("last_scan", "Last scan"),
            ("last_seen", "Last seen"),
            ("description", "Directory description"),
            ("notes", "Notes"),
        ):
            box.append(kv_row(label, str(device[key]) if device[key] is not None else None))
        if device["ram_gb"]:
            box.append(kv_row("RAM", f"{device['ram_gb']} GB"))
        if device["disk_gb"]:
            box.append(kv_row("Disk", f"{device['disk_gb']} GB"))
        return Gtk.ScrolledWindow(vexpand=True, child=box)

    def _table(self, rows, formatter, empty: str) -> Gtk.ScrolledWindow:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_top=8, margin_start=4)
        if not rows:
            box.append(muted(empty))
        else:
            for row in rows[:400]:
                box.append(Gtk.Label(label=formatter(row), xalign=0, wrap=True))
            if len(rows) > 400:
                box.append(muted(f"Showing 400 of {len(rows)}."))
        return Gtk.ScrolledWindow(vexpand=True, child=box)

    def _hardware(self, device_id: int, device) -> Gtk.ScrolledWindow:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_top=8, margin_start=4)
        box.append(Gtk.Label(label="Disks", xalign=0, css_classes=["card-title"]))
        disks = self.store.child_rows("disks", device_id)
        if not disks:
            box.append(muted("No disks recorded."))
        for row in disks:
            box.append(Gtk.Label(label=f"{row['name'] or 'disk'}  {row['size_gb'] or '?'} GB  free {row['free_gb'] or '?'}", xalign=0))
        box.append(Gtk.Label(label="Network", xalign=0, css_classes=["card-title"]))
        nics = self.store.child_rows("nics", device_id)
        if not nics:
            box.append(muted("No adapters recorded."))
        for row in nics:
            box.append(Gtk.Label(label=" · ".join(part for part in (row["name"], row["mac"], row["ip"]) if part), xalign=0, wrap=True))
        if device["hardware_json"]:
            try:
                extra = json.loads(device["hardware_json"])
            except json.JSONDecodeError:
                extra = {}
            for stick in extra.get("memory") or []:
                box.append(Gtk.Label(label=f"Memory {stick.get('bank') or ''} {stick.get('gb') or ''} GB", xalign=0))
            for video in extra.get("video") or []:
                box.append(Gtk.Label(label=f"Video {video.get('name') or ''}", xalign=0, wrap=True))
        return Gtk.ScrolledWindow(vexpand=True, child=box)

    def _people_and_more(self, device_id: int, device) -> Gtk.ScrolledWindow:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_top=8, margin_start=4)
        groups = self.store.fetchall(
            "SELECT group_name FROM device_groups WHERE device_id = ? ORDER BY group_name",
            (device_id,),
        )
        box.append(Gtk.Label(label="AD groups", xalign=0, css_classes=["card-title"]))
        if not groups:
            box.append(muted("No directory groups stored."))
        for row in groups:
            box.append(Gtk.Label(label=row["group_name"] or "", xalign=0))
        box.append(Gtk.Label(label="Local users", xalign=0, css_classes=["card-title"]))
        users = self.store.child_rows("local_users", device_id)
        if not users:
            box.append(muted("No local users recorded."))
        for row in users:
            suffix = " disabled" if int(row["disabled"] or 0) else ""
            box.append(Gtk.Label(label=f"{row['name']}{suffix}", xalign=0))
        for title, table, formatter in (
            ("Shares", "shares", lambda row: f"{row['name']}  {row['path'] or ''}"),
            ("Printers", "printers", lambda row: f"{row['name']}  {row['driver'] or ''}"),
            ("Startup", "startup_items", lambda row: f"{row['name']}  {row['command'] or ''}"),
        ):
            box.append(Gtk.Label(label=title, xalign=0, css_classes=["card-title"]))
            rows = self.store.child_rows(table, device_id)
            if not rows:
                box.append(muted(f"No {title.lower()} recorded."))
            for row in rows[:100]:
                box.append(Gtk.Label(label=formatter(row), xalign=0, wrap=True))
        if device["custom_scan"]:
            box.append(Gtk.Label(label="Custom scan", xalign=0, css_classes=["card-title"]))
            box.append(Gtk.Label(label=device["custom_scan"], xalign=0, wrap=True, selectable=True))
        return Gtk.ScrolledWindow(vexpand=True, child=box)

    def _scan_selected(self) -> None:
        if not self.selected_id:
            return
        self.status.set_text("Scanning…")
        self.jobs.scan([self.selected_id], self.status.set_text, self._job_done)

    def _scan_windows(self) -> None:
        ids = scanner.scannable_ids(self.store)
        self.status.set_text(f"Scanning {len(ids)} computers…")
        self.jobs.scan(ids, self.status.set_text, self._job_done)

    def _deploy(self) -> None:
        if not self.selected_id:
            return
        deploy_dialog(
            self,
            self.store,
            self.jobs,
            self._job_done,
            device_ids=[self.selected_id],
            on_progress=self.status.set_text,
        )

    def _job_done(self, error: str | None) -> None:
        self.status.set_text(error or "Finished.")
        if error:
            alert(self, error)
        self.refresh()

    def _tool_dialog(self, kind: str) -> None:
        if not self.selected_id:
            return
        device_id = self.selected_id
        dialog = Adw.Dialog()
        dialog.set_title("PowerShell" if kind == "powershell" else "Remote command")
        dialog.set_content_width(560)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
        view = Gtk.TextView(monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        view.add_css_class("mono")
        view.set_size_request(-1, 80)
        output = Gtk.Label(label="", xalign=0, wrap=True, selectable=True)
        run = Gtk.Button(label="Run", css_classes=["suggested-action"])

        def on_run(_btn) -> None:
            buf = view.get_buffer()
            payload = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True).strip()
            if not payload:
                return
            output.set_text("Running…")

            def done(text, error) -> None:
                output.set_text(error or text or "")
                if not error:
                    log_dialog(self, kind, text or "")

            self.jobs.tool(device_id, kind, payload, done)

        run.connect("clicked", on_run)
        box.append(Gtk.ScrolledWindow(child=view, min_content_height=80))
        box.append(run)
        box.append(output)
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        toolbar.set_content(box)
        dialog.set_child(toolbar)
        dialog.present(self.get_root())

    def _reboot(self) -> None:
        if not self.selected_id:
            return
        device = self.store.device(self.selected_id)
        if not device:
            return
        device_id = self.selected_id

        def go() -> None:
            self.jobs.tool(device_id, "reboot", "", lambda text, error: alert(self, error or text or "Reboot command sent."))

        confirm(self, f"Reboot {device['name']} now?", go)

    def _wake(self) -> None:
        if not self.selected_id:
            return
        device = self.store.device(self.selected_id)
        if not device or not device["mac"]:
            alert(self, "This computer has no MAC address.")
            return
        try:
            remote.wake_on_lan(device["mac"])
        except Exception as exc:
            alert(self, str(exc))
            return
        self.status.set_text(f"Sent Wake-on-LAN to {device['name']}.")

    def _delete(self, device_id: int) -> None:
        self.store.delete_device(device_id)
        self.selected_id = None
        self.refresh()

    def _edit_dialog(self, device_id: int | None = None) -> None:
        device = self.store.device(device_id) if device_id else None
        dialog = Adw.Dialog()
        dialog.set_title("Edit device" if device else "Add device")
        dialog.set_content_width(460)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
        fields = {}
        for key, placeholder in (
            ("name", "Name"),
            ("hostname", "Hostname"),
            ("ip", "IP address"),
            ("mac", "MAC"),
            ("os", "Operating system"),
            ("manufacturer", "Vendor"),
            ("model", "Model"),
        ):
            entry = Gtk.Entry(placeholder_text=placeholder)
            if device and device[key]:
                entry.set_text(str(device[key]))
            fields[key] = entry
            box.append(entry)
        type_combo = Gtk.ComboBoxText()
        for item in TYPES[1:]:
            type_combo.append(item, item.title())
        type_combo.set_active_id(device["type"] if device else "computer")
        box.append(type_combo)
        notes = Gtk.Entry(placeholder_text="Notes")
        if device and device["notes"]:
            notes.set_text(device["notes"])
        box.append(notes)
        save = Gtk.Button(label="Save", css_classes=["suggested-action"])

        def on_save(_btn: Gtk.Button) -> None:
            payload = {key: fields[key].get_text().strip() or None for key in fields}
            payload["name"] = fields["name"].get_text().strip() or "Unnamed"
            payload["type"] = type_combo.get_active_id() or "computer"
            payload["notes"] = notes.get_text().strip() or None
            payload["status"] = device["status"] if device else "unknown"
            if device:
                self.store.update_device(device_id, **payload)
            else:
                self.store.add_device(**payload)
            dialog.close()
            self.refresh()

        save.connect("clicked", on_save)
        box.append(save)
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        toolbar.set_content(box)
        dialog.set_child(toolbar)
        dialog.present(self.get_root())

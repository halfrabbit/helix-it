from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from helix_it import secrets
from helix_it.collections import FIELDS, OPS
from datetime import datetime, timezone

from helix_it.db import Store
from helix_it.deployer import default_codes
from helix_it.pages.common import alert, deploy_dialog, log_dialog
from helix_it.schedules import compute_next
from helix_it.widgets import heading, muted, status_badge

KINDS = ("install", "command", "powershell", "copy", "reboot", "sleep", "message", "nested")


class DeployPage(Gtk.Box):
    def __init__(self, store: Store, jobs) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.store = store
        self.jobs = jobs
        self.package_id: int | None = None
        self.deployment_id: int | None = None
        self.add_css_class("page")
        self.append(heading("Deploy"))
        self.append(muted("Packages, step-by-step installs, history, and schedules. Windows targets run over WinRM."))
        self.notebook = Gtk.Notebook()
        self.notebook.set_vexpand(True)
        self.notebook.append_page(self._packages_tab(), Gtk.Label(label="Packages"))
        self.notebook.append_page(self._history_tab(), Gtk.Label(label="History"))
        self.notebook.append_page(self._schedules_tab(), Gtk.Label(label="Schedules"))
        self.append(self.notebook)
        self.refresh()

    def _packages_tab(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        tools = Gtk.Box(spacing=8, css_classes=["toolbar-gap"])
        new = Gtk.Button(label="New package", css_classes=["suggested-action"])
        new.connect("clicked", lambda *_: self._package_dialog())
        deploy = Gtk.Button(label="Deploy")
        deploy.connect("clicked", lambda *_: self._deploy_selected())
        delete = Gtk.Button(label="Delete", css_classes=["destructive-action"])
        delete.connect("clicked", lambda *_: self._delete_package())
        tools.append(new)
        tools.append(deploy)
        tools.append(delete)
        self.package_status = Gtk.Label(label="", xalign=0, css_classes=["muted"])
        tools.append(self.package_status)
        box.append(tools)
        split = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        split.set_vexpand(True)
        self.packages = Gtk.ListBox(css_classes=["plain"])
        self.packages.connect("row-selected", self._on_package)
        split.append(Gtk.ScrolledWindow(vexpand=True, hexpand=True, child=self.packages))
        self.steps = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.steps.set_size_request(420, -1)
        split.append(Gtk.ScrolledWindow(vexpand=True, child=self.steps))
        box.append(split)
        return box

    def _history_tab(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        tools = Gtk.Box(spacing=8)
        retry = Gtk.Button(label="Retry failed")
        retry.connect("clicked", lambda *_: self._retry())
        tools.append(retry)
        self.history_status = Gtk.Label(label="", xalign=0, css_classes=["muted"])
        tools.append(self.history_status)
        box.append(tools)
        split = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        split.set_vexpand(True)
        self.history = Gtk.ListBox(css_classes=["plain"])
        self.history.connect("row-selected", self._on_deployment)
        split.append(Gtk.ScrolledWindow(vexpand=True, hexpand=True, child=self.history))
        self.targets = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        split.append(Gtk.ScrolledWindow(vexpand=True, child=self.targets))
        box.append(split)
        return box

    def _schedules_tab(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        tools = Gtk.Box(spacing=8)
        add = Gtk.Button(label="New schedule", css_classes=["suggested-action"])
        add.connect("clicked", lambda *_: self._schedule_dialog())
        tools.append(add)
        box.append(
            muted(
                "Interval and daily schedules run while Helix IT is open. "
                "Heartbeat deploys after a successful scan when the computer is in the collection "
                "and has never had a successful run of that package. Daily times are UTC."
            )
        )
        box.append(tools)
        self.schedule_list = Gtk.ListBox(css_classes=["plain"])
        box.append(Gtk.ScrolledWindow(vexpand=True, child=self.schedule_list))
        return box

    def refresh(self) -> None:
        self._load_packages()
        self._load_history()
        self._load_schedules()

    def _load_packages(self) -> None:
        selected = self.package_id
        self.packages.remove_all()
        rows = self.store.packages()
        chosen = None
        for row in rows:
            label = Gtk.Label(label=f"{row['name']}  {row['version'] or ''}", xalign=0)
            item = Gtk.ListBoxRow(child=label)
            item.package_id = int(row["id"])
            self.packages.append(item)
            if selected == int(row["id"]):
                chosen = item
        if chosen:
            self.packages.select_row(chosen)
            self._show_package(selected)
        elif rows:
            self._show_package(int(rows[0]["id"]))
        else:
            self._show_package(None)

    def _on_package(self, _list, row) -> None:
        if row is None or not hasattr(row, "package_id"):
            return
        if self.package_id == row.package_id and self.steps.get_first_child() is not None:
            return
        self._show_package(row.package_id)

    def _show_package(self, package_id: int | None) -> None:
        self.package_id = package_id
        while child := self.steps.get_first_child():
            self.steps.remove(child)
        if package_id is None:
            self.steps.append(muted("No packages yet."))
            return
        package = self.store.package(package_id)
        if not package:
            return
        self.steps.append(Gtk.Label(label=package["name"], xalign=0, css_classes=["detail-title"]))
        if package["description"]:
            self.steps.append(muted(package["description"]))
        edit = Gtk.Button(label="Edit package")
        edit.connect("clicked", lambda *_: self._package_dialog(package_id))
        self.steps.append(edit)
        add = Gtk.Button(label="Add step", css_classes=["suggested-action"])
        add.connect("clicked", lambda *_: self._step_dialog(package_id))
        self.steps.append(add)
        for step in self.store.package_steps(package_id):
            row = Gtk.Box(spacing=6)
            text = f"{step['position']}. {step['kind']} — {step['name']}"
            row.append(Gtk.Label(label=text, xalign=0, hexpand=True))
            edit_step = Gtk.Button(label="Edit")
            edit_step.connect("clicked", lambda *_b, sid=int(step["id"]): self._step_dialog(package_id, sid))
            up = Gtk.Button(label="Up")
            up.connect("clicked", lambda *_b, sid=int(step["id"]): self._move(sid, -1))
            down = Gtk.Button(label="Down")
            down.connect("clicked", lambda *_b, sid=int(step["id"]): self._move(sid, 1))
            remove = Gtk.Button(label="Remove")
            remove.connect("clicked", lambda *_b, sid=int(step["id"]): self._remove_step(sid))
            row.append(edit_step)
            row.append(up)
            row.append(down)
            row.append(remove)
            self.steps.append(row)

    def _move(self, step_id: int, direction: int) -> None:
        self.store.move_step(step_id, direction)
        self._show_package(self.package_id)

    def _remove_step(self, step_id: int) -> None:
        self.store.delete_step(step_id)
        self._show_package(self.package_id)

    def _package_dialog(self, package_id: int | None = None) -> None:
        current = self.store.package(package_id) if package_id else None
        dialog = Adw.Dialog()
        dialog.set_title("Edit package" if current else "New package")
        dialog.set_content_width(460)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
        name = Gtk.Entry(placeholder_text="Name", text=(current["name"] if current else ""))
        version = Gtk.Entry(placeholder_text="Version", text=(current["version"] or "" if current else ""))
        description = Gtk.Entry(placeholder_text="Description", text=(current["description"] or "" if current else ""))
        timeout = Gtk.Entry(placeholder_text="Timeout seconds", text=str(current["timeout_sec"] if current else 3600))
        save = Gtk.Button(label="Save", css_classes=["suggested-action"])

        def on_save(_btn) -> None:
            title = name.get_text().strip()
            if not title:
                return
            try:
                seconds = int(timeout.get_text().strip() or "3600")
            except ValueError:
                seconds = 3600
            if current:
                self.store.update_package(
                    package_id,
                    name=title,
                    version=version.get_text().strip(),
                    description=description.get_text().strip(),
                    timeout_sec=seconds,
                )
                self.package_id = package_id
            else:
                self.package_id = self.store.add_package(
                    title,
                    version.get_text().strip(),
                    description.get_text().strip(),
                    seconds,
                )
            dialog.close()
            self.refresh()

        save.connect("clicked", on_save)
        for widget in (name, version, description, timeout, save):
            box.append(widget)
        self._show_dialog(dialog, box)

    def _step_dialog(self, package_id: int, step_id: int | None = None) -> None:
        current = None
        if step_id:
            current = next((step for step in self.store.package_steps(package_id) if int(step["id"]) == step_id), None)
        dialog = Adw.Dialog()
        dialog.set_title("Edit step" if current else "Add step")
        dialog.set_content_width(560)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
        kind = Gtk.ComboBoxText()
        for item in KINDS:
            kind.append(item, item)
        kind.set_active_id(current["kind"] if current else "command")
        name = Gtk.Entry(placeholder_text="Step name", text=(current["name"] if current else ""))
        payload = Gtk.TextView(monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        payload.add_css_class("mono")
        payload.set_size_request(-1, 100)
        payload.get_buffer().set_text(current["payload"] or "" if current else "")
        scroll = Gtk.ScrolledWindow(child=payload, min_content_height=100)
        args = Gtk.Entry(placeholder_text="Install arguments, for example /qn /norestart", text=(current["args"] or "" if current else ""))
        browse = Gtk.Button(label="Browse for file")
        browse.connect("clicked", lambda *_: self._browse(payload))
        codes = Gtk.Entry(
            placeholder_text="Success codes",
            text=(current["success_codes"] if current else default_codes(kind.get_active_id() or "command")),
        )
        kind.connect("changed", lambda *_: codes.set_text(default_codes(kind.get_active_id() or "command")) if not current else None)
        cont = Gtk.CheckButton(label="Continue on error")
        cont.set_active(bool(int(current["continue_on_error"])) if current else False)
        field = Gtk.ComboBoxText()
        field.append("", "Always run")
        for key, label in FIELDS:
            field.append(key, label)
        field.set_active_id(current["condition_field"] or "" if current else "")
        op = Gtk.ComboBoxText()
        for key, label in OPS:
            op.append(key, label)
        op.set_active_id((current["condition_op"] or "contains") if current else "contains")
        value = Gtk.Entry(placeholder_text="Condition value", text=(current["condition_value"] or "" if current else ""))
        nested = Gtk.ComboBoxText()
        nested.append("", "No nested package")
        for package in self.store.packages():
            if int(package["id"]) != package_id:
                nested.append(str(package["id"]), package["name"])
        if current and current["nested_package_id"]:
            nested.set_active_id(str(current["nested_package_id"]))
        else:
            nested.set_active_id("")
        save = Gtk.Button(label="Save step", css_classes=["suggested-action"])

        def text_of(view: Gtk.TextView) -> str:
            buf = view.get_buffer()
            return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True).strip()

        def on_save(_btn) -> None:
            chosen = kind.get_active_id() or "command"
            title = name.get_text().strip() or chosen
            body = text_of(payload)
            nested_id = int(nested.get_active_id()) if nested.get_active_id() else None
            fields = {
                "kind": chosen,
                "name": title,
                "payload": body,
                "args": args.get_text().strip(),
                "success_codes": codes.get_text().strip() or default_codes(chosen),
                "condition_field": field.get_active_id() or None,
                "condition_op": op.get_active_id() or "contains",
                "condition_value": value.get_text().strip(),
                "continue_on_error": 1 if cont.get_active() or chosen == "message" else 0,
                "nested_package_id": nested_id if chosen == "nested" else None,
            }
            if current:
                self.store.update_step(step_id, **fields)
            else:
                self.store.add_step(package_id, **fields)
            dialog.close()
            self._show_package(package_id)

        save.connect("clicked", on_save)
        for widget in (
            kind,
            name,
            Gtk.Label(label="Command, script, message, seconds, or a file path on this computer.", xalign=0, css_classes=["muted"]),
            scroll,
            browse,
            args,
            codes,
            cont,
            Gtk.Label(label="Condition uses the last inventory scan.", xalign=0, css_classes=["muted"]),
            field,
            op,
            value,
            Gtk.Label(label="Nested package", xalign=0, css_classes=["muted"]),
            nested,
            save,
        ):
            box.append(widget)
        self._show_dialog(dialog, box)

    def _browse(self, view: Gtk.TextView) -> None:
        root = self.get_root()
        if not isinstance(root, Gtk.Window):
            return
        dialog = Gtk.FileDialog()

        def done(dlg: Gtk.FileDialog, result: GLib.AsyncResult) -> None:
            try:
                chosen = dlg.open_finish(result)
            except GLib.Error:
                return
            if chosen and chosen.get_path():
                view.get_buffer().set_text(chosen.get_path())

        dialog.open(root, None, done)

    def _deploy_selected(self) -> None:
        if not self.package_id:
            return
        deploy_dialog(
            self,
            self.store,
            self.jobs,
            self._done,
            package_id=self.package_id,
            on_progress=self.package_status.set_text,
        )

    def _done(self, error: str | None) -> None:
        self.package_status.set_text(error or "Finished.")
        self.history_status.set_text(error or "Finished.")
        if error:
            alert(self, error)
        self.refresh()

    def _delete_package(self) -> None:
        if not self.package_id:
            return
        message = self.store.delete_package(self.package_id)
        if message:
            alert(self, message)
            return
        self.package_id = None
        self.refresh()

    def _load_history(self) -> None:
        selected = self.deployment_id
        self.history.remove_all()
        rows = self.store.deployments()
        chosen = None
        for row in rows:
            box = Gtk.Box(spacing=8)
            box.append(status_badge(row["status"]))
            box.append(Gtk.Label(label=f"{row['package_name']} · {row['created_at']}", xalign=0, hexpand=True))
            item = Gtk.ListBoxRow(child=box)
            item.deployment_id = int(row["id"])
            self.history.append(item)
            if selected == int(row["id"]):
                chosen = item
        if not rows:
            self.history.append(Gtk.ListBoxRow(child=muted("No deployments yet.")))
            self._show_targets(None)
            return
        if chosen:
            self.history.select_row(chosen)
            self._show_targets(selected)
        else:
            self._show_targets(int(rows[0]["id"]))

    def _on_deployment(self, _list, row) -> None:
        if row is None or not hasattr(row, "deployment_id"):
            return
        if self.deployment_id == row.deployment_id and self.targets.get_first_child() is not None:
            return
        self._show_targets(row.deployment_id)

    def _show_targets(self, deployment_id: int | None) -> None:
        self.deployment_id = deployment_id
        while child := self.targets.get_first_child():
            self.targets.remove(child)
        if deployment_id is None:
            return
        for target in self.store.deployment_targets(deployment_id):
            row = Gtk.Box(spacing=8)
            row.append(status_badge(target["status"]))
            row.append(Gtk.Label(label=target["device_name"], xalign=0, hexpand=True))
            log = Gtk.Button(label="Log")
            log.connect(
                "clicked",
                lambda *_b, name=target["device_name"], body=target["log"]: log_dialog(self, name, body or ""),
            )
            row.append(log)
            self.targets.append(row)

    def _retry(self) -> None:
        if not self.deployment_id:
            return
        self.jobs.retry(self.deployment_id, self.history_status.set_text, self._done)

    def _load_schedules(self) -> None:
        self.schedule_list.remove_all()
        rows = self.store.schedules()
        if not rows:
            self.schedule_list.append(Gtk.ListBoxRow(child=muted("No schedules yet.")))
            return
        for row in rows:
            box = Gtk.Box(spacing=8)
            label = f"{row['name']} · {row['kind']} · {row['trigger']}"
            if row["next_run"]:
                label += f" · next {row['next_run']}"
            if not int(row["enabled"]):
                label += " · paused"
            box.append(Gtk.Label(label=label, xalign=0, hexpand=True))
            remove = Gtk.Button(label="Delete")
            remove.connect("clicked", lambda *_b, sid=int(row["id"]): self._delete_schedule(sid))
            box.append(remove)
            self.schedule_list.append(Gtk.ListBoxRow(child=box))

    def _delete_schedule(self, schedule_id: int) -> None:
        self.store.delete_schedule(schedule_id)
        self._load_schedules()

    def _schedule_dialog(self) -> None:
        dialog = Adw.Dialog()
        dialog.set_title("New schedule")
        dialog.set_content_width(480)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
        name = Gtk.Entry(placeholder_text="Name")
        kind = Gtk.ComboBoxText()
        kind.append("scan", "Scan")
        kind.append("deploy", "Deploy")
        kind.set_active_id("deploy")
        trigger = Gtk.ComboBoxText()
        trigger.append("interval", "Interval")
        trigger.append("daily", "Daily")
        trigger.append("heartbeat", "Heartbeat")
        trigger.set_active_id("interval")
        interval = Gtk.Entry(placeholder_text="Interval minutes", text="60")
        clock = Gtk.Entry(placeholder_text="Daily time UTC HH:MM", text="02:00")
        package = Gtk.ComboBoxText()
        package.append("", "No package")
        for row in self.store.packages():
            package.append(str(row["id"]), row["name"])
        package.set_active(0)
        collection = Gtk.ComboBoxText()
        collection.append("", "All scannable computers")
        for row in self.store.collections():
            collection.append(str(row["id"]), row["name"])
        collection.set_active(0)
        credential = Gtk.ComboBoxText()
        credential.append("", "Default scan account")
        for cred in secrets.credentials():
            credential.append(cred["name"], cred["name"])
        credential.set_active(0)
        save = Gtk.Button(label="Save schedule", css_classes=["suggested-action"])

        def on_save(_btn) -> None:
            title = name.get_text().strip()
            if not title:
                return
            chosen_trigger = trigger.get_active_id() or "interval"
            try:
                minutes = int(interval.get_text().strip() or "60")
            except ValueError:
                minutes = 60
            now = datetime.now(timezone.utc)
            nxt = compute_next(chosen_trigger, minutes, clock.get_text().strip() or "02:00", now)
            self.store.add_schedule(
                name=title,
                kind=kind.get_active_id() or "deploy",
                trigger=chosen_trigger,
                package_id=int(package.get_active_id()) if package.get_active_id() else None,
                collection_id=int(collection.get_active_id()) if collection.get_active_id() else None,
                interval_minutes=minutes,
                time_of_day=clock.get_text().strip() or "02:00",
                credential=credential.get_active_id() or None,
                enabled=1,
                next_run=nxt,
            )
            dialog.close()
            self._load_schedules()

        save.connect("clicked", on_save)
        for widget in (name, kind, trigger, interval, clock, package, collection, credential, save):
            box.append(widget)
        self._show_dialog(dialog, box)

    def _show_dialog(self, dialog: Adw.Dialog, box: Gtk.Widget) -> None:
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        toolbar.set_content(box)
        dialog.set_child(toolbar)
        dialog.present(self.get_root())

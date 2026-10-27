from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from helix_it import deployer, secrets


def alert(parent: Gtk.Widget, text: str) -> None:
    dialog = Adw.Dialog()
    dialog.set_title("Helix IT")
    dialog.set_content_width(440)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.set_margin_top(16)
    box.set_margin_bottom(16)
    box.set_margin_start(16)
    box.set_margin_end(16)
    label = Gtk.Label(label=text, xalign=0, wrap=True)
    label.set_selectable(True)
    box.append(label)
    close = Gtk.Button(label="Close", css_classes=["suggested-action"])
    close.connect("clicked", lambda *_: dialog.close())
    box.append(close)
    _present(dialog, box, parent)


def confirm(parent: Gtk.Widget, text: str, on_yes) -> None:
    dialog = Adw.Dialog()
    dialog.set_title("Helix IT")
    dialog.set_content_width(440)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.set_margin_top(16)
    box.set_margin_bottom(16)
    box.set_margin_start(16)
    box.set_margin_end(16)
    box.append(Gtk.Label(label=text, xalign=0, wrap=True))
    buttons = Gtk.Box(spacing=8)
    cancel = Gtk.Button(label="Cancel")
    cancel.connect("clicked", lambda *_: dialog.close())
    yes = Gtk.Button(label="Continue", css_classes=["destructive-action"])

    def go(_btn) -> None:
        dialog.close()
        on_yes()

    yes.connect("clicked", go)
    buttons.append(cancel)
    buttons.append(yes)
    box.append(buttons)
    _present(dialog, box, parent)


def log_dialog(parent: Gtk.Widget, title: str, text: str) -> None:
    dialog = Adw.Dialog()
    dialog.set_title(title)
    dialog.set_content_width(640)
    dialog.set_content_height(420)
    view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
    view.add_css_class("mono")
    view.get_buffer().set_text(text or "")
    scroll = Gtk.ScrolledWindow(vexpand=True, child=view)
    _present(dialog, scroll, parent)


def deploy_dialog(
    parent: Gtk.Widget,
    store,
    jobs,
    on_done,
    package_id: int | None = None,
    device_ids: list[int] | None = None,
    collection_id: int | None = None,
    on_progress=None,
) -> None:
    dialog = Adw.Dialog()
    dialog.set_title("Deploy package")
    dialog.set_content_width(480)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_margin_top(16)
    box.set_margin_bottom(16)
    box.set_margin_start(16)
    box.set_margin_end(16)
    box.append(Gtk.Label(label="Choose a package and where it should run.", xalign=0, css_classes=["muted"]))

    package = Gtk.ComboBoxText()
    for row in store.packages():
        package.append(str(row["id"]), row["name"])
    if package_id:
        package.set_active_id(str(package_id))
    elif package.get_active_id() is None:
        package.set_active(0)
    box.append(package)

    collection = Gtk.ComboBoxText()
    collection.append("", "No collection")
    for row in store.collections():
        collection.append(str(row["id"]), row["name"])
    collection.set_active_id(str(collection_id) if collection_id else "")
    box.append(collection)

    computer = Gtk.ComboBoxText()
    computer.append("", "No single computer")
    for row in store.devices():
        computer.append(str(row["id"]), row["name"])
    if device_ids and len(device_ids) == 1 and not collection_id:
        computer.set_active_id(str(device_ids[0]))
    else:
        computer.set_active_id("")
    box.append(computer)

    credential = Gtk.ComboBoxText()
    credential.append("", "Default scan account")
    for cred in secrets.credentials():
        credential.append(cred["name"], cred["name"])
    credential.set_active(0)
    box.append(credential)

    status = Gtk.Label(label="", xalign=0, css_classes=["muted"])
    box.append(status)
    start = Gtk.Button(label="Deploy", css_classes=["suggested-action"])

    def go(_btn) -> None:
        package_value = package.get_active_id()
        if not package_value:
            status.set_text("Choose a package.")
            return
        ids: list[int] = []
        collection_value = collection.get_active_id()
        if collection_value:
            ids.extend(store.collection_device_ids(int(collection_value)))
        computer_value = computer.get_active_id()
        if computer_value:
            ids.append(int(computer_value))
        if not ids and device_ids:
            ids.extend(device_ids)
        if not ids:
            status.set_text("Pick a collection or a computer.")
            return
        try:
            deployment_id = deployer.create_deployment(
                store,
                int(package_value),
                ids,
                credential.get_active_id() or None,
            )
        except Exception as exc:
            status.set_text(str(exc))
            return
        dialog.close()

        def progress(message: str) -> None:
            if on_progress:
                on_progress(message)

        jobs.deploy(deployment_id, progress, on_done)

    start.connect("clicked", go)
    box.append(start)
    _present(dialog, box, parent)


def _present(dialog: Adw.Dialog, content: Gtk.Widget, parent: Gtk.Widget) -> None:
    toolbar = Adw.ToolbarView()
    toolbar.add_top_bar(Adw.HeaderBar())
    toolbar.set_content(content)
    dialog.set_child(toolbar)
    root = parent.get_root() if parent else None
    dialog.present(root or parent)

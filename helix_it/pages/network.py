from __future__ import annotations

import threading

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

from helix_it import network
from helix_it.db import Store
from helix_it.widgets import card, heading, kv_row, muted, status_badge


class NetworkPage(Gtk.Box):
    def __init__(self, store: Store, on_scanned=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.store = store
        self.on_scanned = on_scanned
        self.add_css_class("page")
        self.append(heading("Network"))
        self.append(muted("Reads Linux interfaces and ARP, then ping-sweeps private /24s on this host."))

        tools = Gtk.Box(spacing=8)
        self.scan_btn = Gtk.Button(label="Scan local subnets")
        self.scan_btn.add_css_class("suggested-action")
        self.scan_btn.connect("clicked", lambda *_: self._start_scan())
        tools.append(self.scan_btn)
        self.status = Gtk.Label(label="Idle", xalign=0, css_classes=["muted"])
        tools.append(self.status)
        self.append(tools)

        self.ifaces = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.neighbors = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        split = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        split.set_homogeneous(True)
        split.append(card("Interfaces", self.ifaces))
        split.append(card("Neighbors", self.neighbors))
        self.append(split)
        self.refresh()

    def refresh(self) -> None:
        while child := self.ifaces.get_first_child():
            self.ifaces.remove(child)
        for iface in network.list_interfaces():
            block = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            title = Gtk.Label(label=f"{iface.name}  ·  {iface.operstate}", xalign=0)
            title.add_css_class("heading")
            block.append(title)
            if iface.mac:
                block.append(kv_row("MAC", iface.mac))
            block.append(kv_row("Addresses", ", ".join(iface.cidrs) or "none"))
            block.append(kv_row("Traffic", f"↓ {network.format_bytes(iface.rx_bytes)}  ↑ {network.format_bytes(iface.tx_bytes)}"))
            self.ifaces.append(block)

        while child := self.neighbors.get_first_child():
            self.neighbors.remove(child)
        found = network.list_neighbors()
        if not found:
            self.neighbors.append(muted("No ARP/NDP neighbors yet. Run a scan."))
            return
        for item in found:
            line = Gtk.Box(spacing=8)
            reachable = item.state.upper() in {"REACHABLE", "STALE", "DELAY", "PROBE", "PERMANENT"}
            line.append(status_badge("online" if reachable else "unknown"))
            text = f"{item.ip}"
            if item.mac:
                text += f"  {item.mac}"
            if item.iface:
                text += f"  ({item.iface})"
            line.append(Gtk.Label(label=text, xalign=0, hexpand=True))
            self.neighbors.append(line)

    def _start_scan(self) -> None:
        self.scan_btn.set_sensitive(False)
        self.status.set_text("Scanning private subnets on this machine…")
        thread = threading.Thread(target=self._scan, daemon=True)
        thread.start()

    def _scan(self) -> None:
        alive, total = network.discover_lan(self.store)
        GLib.idle_add(self._done, alive, total)

    def _done(self, alive: int, total: int) -> bool:
        self.scan_btn.set_sensitive(True)
        self.status.set_text(f"Done. {alive} of {total} addresses answered ping.")
        self.refresh()
        if self.on_scanned:
            self.on_scanned()
        return False

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Pango

from helix_it.network import format_bytes


def badge(text: str, css: str) -> Gtk.Label:
    label = Gtk.Label(label=text)
    label.add_css_class("badge")
    label.add_css_class(css)
    label.set_valign(Gtk.Align.CENTER)
    return label


def status_badge(status: str) -> Gtk.Label:
    return badge(status, f"badge-{status}")


def priority_badge(priority: str) -> Gtk.Label:
    return badge(priority, f"badge-{priority}")


def heading(text: str, css: str = "page-title") -> Gtk.Label:
    label = Gtk.Label(label=text, xalign=0)
    label.add_css_class(css)
    return label


def muted(text: str) -> Gtk.Label:
    label = Gtk.Label(label=text, xalign=0)
    label.add_css_class("muted")
    label.set_wrap(True)
    return label


def stat_card(label: str, value: str, hint: str = "") -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    box.add_css_class("stat-card")
    box.append(Gtk.Label(label=label, xalign=0, css_classes=["stat-label"]))
    box.append(Gtk.Label(label=value, xalign=0, css_classes=["stat-value"]))
    if hint:
        box.append(Gtk.Label(label=hint, xalign=0, css_classes=["stat-hint"]))
    return box


def card(title: str, child: Gtk.Widget) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.add_css_class("card")
    box.append(Gtk.Label(label=title, xalign=0, css_classes=["card-title"]))
    box.append(child)
    return box


def kv_row(key: str, value: str | None) -> Gtk.Box:
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    k = Gtk.Label(label=key, xalign=0, css_classes=["muted"])
    k.set_size_request(120, -1)
    v = Gtk.Label(label=value or "—", xalign=0)
    v.set_selectable(True)
    v.set_wrap(True)
    v.set_hexpand(True)
    v.set_ellipsize(Pango.EllipsizeMode.END)
    row.append(k)
    row.append(v)
    return row


def search_entry(placeholder: str, on_change: Callable[[str], None]) -> Gtk.SearchEntry:
    entry = Gtk.SearchEntry()
    entry.set_placeholder_text(placeholder)
    entry.set_hexpand(True)

    def changed(_entry: Gtk.SearchEntry) -> None:
        on_change(entry.get_text())

    entry.connect("search-changed", changed)
    return entry


def pill_filters(labels: list[str], on_pick: Callable[[str], None]) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    group: list[Gtk.ToggleButton] = []
    for index, label in enumerate(labels):
        button = Gtk.ToggleButton(label=label.replace("_", " ").title())
        button.set_active(index == 0)
        group.append(button)

        def toggled(btn: Gtk.ToggleButton, name: str = label) -> None:
            if not btn.get_active():
                if not any(item.get_active() for item in group):
                    btn.set_active(True)
                return
            for item in group:
                if item is not btn:
                    item.set_active(False)
            on_pick(name)

        button.connect("toggled", toggled)
        box.append(button)
    return box


def human_bytes(value: int | None) -> str:
    if value is None:
        return "—"
    return format_bytes(int(value))


class BarChart(Gtk.DrawingArea):
    def __init__(self, rows: list[tuple[str, int]]) -> None:
        super().__init__()
        self.rows = rows
        self.set_content_height(max(120, 28 * max(len(rows), 1)))
        self.set_hexpand(True)
        self.set_draw_func(self._draw)

    def set_rows(self, rows: list[tuple[str, int]]) -> None:
        self.rows = rows
        self.set_content_height(max(120, 28 * max(len(rows), 1)))
        self.queue_draw()

    def _draw(self, _area: Gtk.DrawingArea, cr, width: int, height: int) -> None:  # noqa: ANN001
        if not self.rows:
            return
        peak = max(value for _, value in self.rows) or 1
        row_h = height / len(self.rows)
        for index, (label, value) in enumerate(self.rows):
            y = index * row_h + 6
            cr.set_source_rgb(0.58, 0.64, 0.72)
            cr.move_to(8, y + 12)
            cr.show_text(label[:18])
            bar_x = 130
            bar_w = max(4, (width - bar_x - 36) * (value / peak))
            cr.set_source_rgb(0.96, 0.62, 0.04)
            cr.rectangle(bar_x, y, bar_w, 16)
            cr.fill()
            cr.set_source_rgb(0.89, 0.91, 0.94)
            cr.move_to(bar_x + bar_w + 8, y + 12)
            cr.show_text(str(value))

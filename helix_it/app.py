from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio

from helix_it.db import Store
from helix_it.seed import seed_if_needed
from helix_it.window import HelixWindow


class HelixApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id="dev.helixit.HelixIT", flags=Gio.ApplicationFlags.FLAGS_NONE)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
        self.store = Store()
        seed_if_needed(self.store)
        self.connect("activate", self.on_activate)

    def on_activate(self, _app: Adw.Application) -> None:
        window = HelixWindow(self, self.store)
        window.present()


def main(argv: list[str] | None = None) -> int:
    app = HelixApp()
    return int(app.run(argv or sys.argv))


if __name__ == "__main__":
    raise SystemExit(main())

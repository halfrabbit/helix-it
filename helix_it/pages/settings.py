from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk

from helix_it import ad, secrets
from helix_it.db import Store
from helix_it.pages.common import alert, confirm
from helix_it.seed import seed
from helix_it.widgets import heading, muted


PROFILE_FLAGS = (
    ("software", "Applications"),
    ("hotfixes", "Hotfixes"),
    ("services", "Services"),
    ("hardware", "Hardware, disks, and NICs"),
    ("users", "Local users"),
    ("shares", "Shares"),
    ("printers", "Printers"),
    ("startup", "Startup programs"),
)


class SettingsPage(Gtk.Box):
    def __init__(self, store: Store, jobs, on_reset=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.store = store
        self.jobs = jobs
        self.on_reset = on_reset
        self.cred_name_loaded = ""
        self.add_css_class("page")
        self.append(heading("Settings"))
        self.append(muted("Directory and deploy accounts stay in a local file on this computer. They are not written into the SQLite inventory."))
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        scroll = Gtk.ScrolledWindow(vexpand=True, child=inner)
        self.append(scroll)

        inner.append(Gtk.Label(label="Shop", xalign=0, css_classes=["card-title"]))
        self.org = Gtk.Entry(placeholder_text="Organization name")
        self.tech = Gtk.Entry(placeholder_text="Default technician name")
        save = Gtk.Button(label="Save shop", css_classes=["suggested-action"])
        save.connect("clicked", self._save_shop)
        inner.append(self.org)
        inner.append(self.tech)
        inner.append(save)

        inner.append(Gtk.Label(label="Active Directory", xalign=0, css_classes=["card-title"]))
        inner.append(
            muted(
                "Point this at a domain controller. Sync pulls computers, OUs, groups, and users. "
                "Use a dedicated account. LDAPS is port 636."
            )
        )
        self.server = Gtk.Entry(placeholder_text="Domain controller host")
        self.port = Gtk.Entry(placeholder_text="389 or 636")
        self.use_ssl = Gtk.CheckButton(label="Use LDAPS")
        self.dns = Gtk.Entry(placeholder_text="DNS domain, for example shop.local")
        self.netbios = Gtk.Entry(placeholder_text="NetBIOS domain, for example SHOP")
        self.base = Gtk.Entry(placeholder_text="Base DN")
        fill = Gtk.Button(label="Fill base DN from domain")
        fill.connect("clicked", lambda *_: self.base.set_text(ad.base_dn_from_domain(self.dns.get_text())))
        self.bind_user = Gtk.Entry(placeholder_text="Directory username")
        self.bind_password = Gtk.PasswordEntry()
        self.bind_password.set_show_peek_icon(True)
        directory_buttons = Gtk.Box(spacing=8)
        save_dir = Gtk.Button(label="Save directory", css_classes=["suggested-action"])
        save_dir.connect("clicked", self._save_directory)
        test = Gtk.Button(label="Test connection")
        test.connect("clicked", self._test_directory)
        sync = Gtk.Button(label="Sync now")
        sync.connect("clicked", self._sync_directory)
        stale = Gtk.Button(label="Delete computers missing from AD", css_classes=["destructive-action"])
        stale.connect("clicked", self._delete_stale)
        for button in (save_dir, test, sync, stale):
            directory_buttons.append(button)
        self.directory_status = Gtk.Label(label="", xalign=0, wrap=True, css_classes=["muted"])
        self.directory_status.set_selectable(True)
        for widget in (
            self.server,
            self.port,
            self.use_ssl,
            self.dns,
            self.netbios,
            self.base,
            fill,
            self.bind_user,
            self.bind_password,
            directory_buttons,
            self.directory_status,
        ):
            inner.append(widget)

        inner.append(Gtk.Label(label="Scan and deploy accounts", xalign=0, css_classes=["card-title"]))
        inner.append(
            muted(
                "Windows computers are reached with WinRM (5985, or 5986 for HTTPS) and file copies use the C$ admin share. "
                "The account needs to be a local administrator on the targets. NTLM is the usual choice from Linux."
            )
        )
        self.cred_list = Gtk.ListBox(css_classes=["plain"])
        self.cred_list.connect("row-selected", self._on_credential)
        inner.append(Gtk.ScrolledWindow(child=self.cred_list, min_content_height=80))
        self.cred_name = Gtk.Entry(placeholder_text="Account name, for example Domain scan")
        self.cred_user = Gtk.Entry(placeholder_text="Username")
        self.cred_domain = Gtk.Entry(placeholder_text="NetBIOS domain")
        self.cred_password = Gtk.PasswordEntry()
        self.cred_password.set_show_peek_icon(True)
        cred_buttons = Gtk.Box(spacing=8)
        save_cred = Gtk.Button(label="Save account", css_classes=["suggested-action"])
        save_cred.connect("clicked", self._save_credential)
        delete_cred = Gtk.Button(label="Delete account", css_classes=["destructive-action"])
        delete_cred.connect("clicked", self._delete_credential)
        cred_buttons.append(save_cred)
        cred_buttons.append(delete_cred)
        inner.append(self.cred_name)
        inner.append(self.cred_user)
        inner.append(self.cred_domain)
        inner.append(self.cred_password)
        inner.append(cred_buttons)

        self.transport = Gtk.ComboBoxText()
        for item in ("ntlm", "kerberos", "basic"):
            self.transport.append(item, item)
        self.winrm_port = Gtk.Entry(placeholder_text="WinRM port")
        self.winrm_ssl = Gtk.CheckButton(label="WinRM over HTTPS")
        self.winrm_cred = Gtk.ComboBoxText()
        save_winrm = Gtk.Button(label="Save WinRM")
        save_winrm.connect("clicked", self._save_winrm)
        inner.append(self.transport)
        inner.append(self.winrm_port)
        inner.append(self.winrm_ssl)
        inner.append(Gtk.Label(label="Default scan account", xalign=0, css_classes=["muted"]))
        inner.append(self.winrm_cred)
        inner.append(save_winrm)

        inner.append(Gtk.Label(label="Scan profile", xalign=0, css_classes=["card-title"]))
        self.flags = {}
        for key, label in PROFILE_FLAGS:
            button = Gtk.CheckButton(label=label)
            self.flags[key] = button
            inner.append(button)
        self.custom = Gtk.TextView(monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.custom.add_css_class("mono")
        self.custom.set_size_request(-1, 80)
        inner.append(muted("Extra PowerShell run after a Windows scan. Its output is stored on the computer."))
        inner.append(Gtk.ScrolledWindow(child=self.custom, min_content_height=80))
        save_profile = Gtk.Button(label="Save scan profile")
        save_profile.connect("clicked", self._save_profile)
        inner.append(save_profile)

        self.path_label = Gtk.Label(xalign=0, selectable=True, wrap=True)
        inner.append(self.path_label)
        reset = Gtk.Button(label="Reload sample data", css_classes=["destructive-action"])
        reset.connect("clicked", self._reset)
        inner.append(reset)
        inner.append(muted("Reloading sample data clears inventory, tickets, packages, and collections on this computer."))
        self.refresh()

    def refresh(self) -> None:
        self.org.set_text(self.store.get_meta("org_name", "") or "")
        self.tech.set_text(self.store.get_meta("tech_name", "") or "")
        directory = secrets.directory()
        self.server.set_text(str(directory.get("server") or ""))
        self.port.set_text(str(directory.get("port") or 389))
        self.use_ssl.set_active(bool(directory.get("use_ssl")))
        self.dns.set_text(str(directory.get("dns_domain") or ""))
        self.netbios.set_text(str(directory.get("netbios") or ""))
        self.base.set_text(str(directory.get("base_dn") or ""))
        self.bind_user.set_text(str(directory.get("username") or ""))
        self.bind_password.set_text("")
        self._password_hint(self.bind_password, "Saved — type to replace" if directory.get("password") else "Password")
        status = self.store.get_meta("ad_status", "") or ""
        synced = self.store.get_meta("ad_synced_at", "") or ""
        self.directory_status.set_text(f"{status} {synced}".strip() or "Directory has not been synced.")
        self._load_credentials()
        winrm = secrets.winrm_config()
        self.transport.set_active_id(str(winrm.get("transport") or "ntlm"))
        self.winrm_port.set_text(str(winrm.get("port") or 5985))
        self.winrm_ssl.set_active(bool(winrm.get("use_ssl")))
        profile = self.store.scan_profile()
        for key, button in self.flags.items():
            button.set_active(bool(int(profile[key] if profile[key] is not None else 1)))
        self.custom.get_buffer().set_text(profile["custom_script"] or "")
        self.path_label.set_text(f"Database: {self.store.path}")

    def _load_credentials(self) -> None:
        current = self.winrm_cred.get_active_id() if self.winrm_cred.get_model() else None
        self.cred_list.remove_all()
        self.winrm_cred.remove_all()
        self.winrm_cred.append("", "First saved account")
        for cred in secrets.credentials():
            row = Gtk.ListBoxRow()
            row.set_child(Gtk.Label(label=cred["name"], xalign=0))
            row.cred_name = cred["name"]
            self.cred_list.append(row)
            self.winrm_cred.append(cred["name"], cred["name"])
        chosen = secrets.winrm_config().get("credential") or current or ""
        if not self.winrm_cred.set_active_id(str(chosen or "")):
            self.winrm_cred.set_active(0)

    def _on_credential(self, _list, row) -> None:
        if row is None or not hasattr(row, "cred_name"):
            return
        cred = secrets.get_credential(row.cred_name)
        if not cred:
            return
        self.cred_name_loaded = cred["name"]
        self.cred_name.set_text(cred["name"])
        self.cred_user.set_text(cred.get("username") or "")
        self.cred_domain.set_text(cred.get("domain") or "")
        self.cred_password.set_text("")
        self._password_hint(self.cred_password, "Saved — type to replace" if cred.get("password") else "Password")

    def _password_hint(self, entry: Gtk.PasswordEntry, text: str) -> None:
        child = entry.get_first_child()
        if child is not None and hasattr(child, "set_placeholder_text"):
            child.set_placeholder_text(text)

    def _save_shop(self, _btn) -> None:
        self.store.set_meta("org_name", self.org.get_text().strip() or "Helix IT")
        self.store.set_meta("tech_name", self.tech.get_text().strip() or "IT Desk")

    def _directory_payload(self) -> dict:
        try:
            port = int(self.port.get_text().strip() or ("636" if self.use_ssl.get_active() else "389"))
        except ValueError:
            port = 636 if self.use_ssl.get_active() else 389
        return {
            "server": self.server.get_text().strip(),
            "port": port,
            "use_ssl": self.use_ssl.get_active(),
            "dns_domain": self.dns.get_text().strip(),
            "netbios": self.netbios.get_text().strip(),
            "base_dn": self.base.get_text().strip(),
            "username": self.bind_user.get_text().strip(),
            "password": self.bind_password.get_text(),
        }

    def _save_directory(self, _btn) -> None:
        secrets.set_directory(self._directory_payload())
        self.bind_password.set_text("")
        self.directory_status.set_text("Directory settings saved on this computer.")

    def _test_directory(self, _btn) -> None:
        secrets.set_directory(self._directory_payload())
        self.directory_status.set_text("Testing…")
        self.jobs.test_directory(self._directory_done)

    def _sync_directory(self, _btn) -> None:
        secrets.set_directory(self._directory_payload())
        self.directory_status.set_text("Syncing…")
        self.jobs.sync_directory(self.directory_status.set_text, self._directory_done)

    def _directory_done(self, message, error) -> None:
        if error:
            self.directory_status.set_text(error)
            alert(self, error)
            return
        if self.on_reset:
            self.on_reset()
        else:
            self.refresh()
        self.directory_status.set_text(message or "Finished.")

    def _delete_stale(self, _btn) -> None:
        def go() -> None:
            count = self.store.delete_stale_directory_computers()
            self.directory_status.set_text(f"Removed {count} computers that were missing from the last sync.")
            if self.on_reset:
                self.on_reset()

        confirm(self, "Delete inventory computers that were not in the last directory sync?", go)

    def _save_credential(self, _btn) -> None:
        try:
            secrets.upsert_credential(
                {
                    "name": self.cred_name.get_text().strip(),
                    "username": self.cred_user.get_text().strip(),
                    "domain": self.cred_domain.get_text().strip(),
                    "password": self.cred_password.get_text(),
                },
                previous=self.cred_name_loaded or None,
            )
        except ValueError as exc:
            alert(self, str(exc))
            return
        self.cred_name_loaded = self.cred_name.get_text().strip()
        self.cred_password.set_text("")
        self._load_credentials()

    def _delete_credential(self, _btn) -> None:
        name = self.cred_name_loaded or self.cred_name.get_text().strip()
        if not name:
            return
        secrets.delete_credential(name)
        self.cred_name_loaded = ""
        self.cred_name.set_text("")
        self.cred_user.set_text("")
        self.cred_domain.set_text("")
        self.cred_password.set_text("")
        self._load_credentials()

    def _save_winrm(self, _btn) -> None:
        try:
            port = int(self.winrm_port.get_text().strip() or "5985")
        except ValueError:
            port = 5985
        secrets.set_winrm(
            {
                "transport": self.transport.get_active_id() or "ntlm",
                "port": port,
                "use_ssl": self.winrm_ssl.get_active(),
                "credential": self.winrm_cred.get_active_id() or "",
            }
        )
        self.directory_status.set_text("WinRM settings saved.")

    def _save_profile(self, _btn) -> None:
        buf = self.custom.get_buffer()
        script = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        fields = {key: 1 if button.get_active() else 0 for key, button in self.flags.items()}
        fields["custom_script"] = script.strip()
        self.store.update_scan_profile(**fields)

    def _reset(self, _btn) -> None:
        def go() -> None:
            seed(self.store)
            self.refresh()
            if self.on_reset:
                self.on_reset()

        confirm(self, "Replace the local database with the Northline Workshop sample?", go)

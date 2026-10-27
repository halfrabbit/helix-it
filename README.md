# Helix IT

A Linux console for a tech shop: inventory, help desk, and the two jobs PDQ Inventory and PDQ Deploy are used for. It reads Active Directory, scans Windows computers, and deploys packages. Data stays in SQLite on this machine.

Helix IT is a **GTK 4 / libadwaita** app.

## Needs

- Python 3.11+
- GTK 4 and libadwaita (PyGObject)
- `ip` and `ping` (iproute2 / iputils)

Directory sync, Windows scans, and package copies also need:

```bash
pip install ldap3 pywinrm smbprotocol
```

`smbclient` from Samba is a fallback when the Python SMB library is not installed. On Arch / CachyOS:

```bash
sudo pacman -S python python-gobject gtk4 libadwaita iproute2 iputils samba
```

## Run

```bash
python3 -m helix_it
```

The database is `~/.local/share/helix-it/helix.db`.

Directory passwords and scan accounts are stored separately in `~/.local/share/helix-it/secrets.json` (mode 0600). They are not put in the inventory database.

`Ctrl+1` … `Ctrl+9` and `Ctrl+0` switch pages.

## What it does

- **Dashboard** — devices, directory count, tickets, scan and deploy failures
- **Inventory** — computers and other gear, scan results, remote command, PowerShell, reboot, Wake-on-LAN
- **Collections** — dynamic filters and pinned computers
- **Deploy** — packages, steps, history, retry, schedules
- **Help desk, Network, Software, People, Reports, Settings**

Network scan only pings **private addresses** on this machine.

## Active Directory and Windows

In **Settings → Active Directory**, enter the domain controller, DNS domain, NetBIOS name, and a directory account. **Test connection** checks the bind. **Sync now** imports computers, OUs, groups, and users. Computers that later disappear from the directory stay in inventory until you delete the ones missing from the last sync.

Windows scans and installs use **WinRM**. On each target (or by Group Policy):

- `Enable-PSRemoting -Force`
- Allow TCP 5985 from this console (5986 if you turn on WinRM HTTPS)
- File and Printer Sharing, so the admin share `C$` can receive package files
- A scan account that is a local administrator on the computers you manage

Save that account under **Scan and deploy accounts** and choose it as the default WinRM account. NTLM is the usual authentication from Linux. Kerberos works after `kinit` if you select that transport.

A scan collects applications, hotfixes, services, hardware, local users, shares, printers, and startup programs. The scan profile can turn categories off, and an extra PowerShell script can be stored with the computer.

The console host itself is scanned locally, without WinRM.

## Packages

A package is an ordered list of steps:

| Step | What it does |
| --- | --- |
| Install | Copy a file from this computer and run it (MSI, EXE, MSIX, ps1, bat) |
| Command | `cmd.exe /c` on Windows, a shell command on this console |
| PowerShell | Script on the target |
| Copy | Copy a file to `C:\Windows\Temp\Helix\...` |
| Reboot | `shutdown.exe /r`. The Helix console is not rebooted |
| Sleep | Wait between steps |
| Message | `msg.exe` on Windows |
| Nested | Run another package |

Success codes, continue-on-error, and conditions (from the last scan) are on each step. `$(ComputerName)`, `$(Hostname)`, `$(IP)`, `$(OU)`, `$(Domain)`, and `$(OS)` expand in commands.

MSI steps default to success codes `0,1641,3010` and silent arguments `/qn /norestart` when you leave arguments empty.

**Deploy** runs the package against one computer or a collection. History keeps the log per computer. **Retry failed** runs the failures again.

Schedules run while Helix IT is open:

- **Interval** and **daily** (UTC) scan a collection or deploy a package
- **Heartbeat** deploys after a successful scan when the computer is in the collection and has never had a successful run of that package

The built-in package **Helix connectivity check** runs `echo` so you can prove WinRM, or run it on this console, before you point an install step at a real installer.

## Shared web console

Several technicians can use one Helix service in a browser. They share the inventory database. Scans, directory syncs, and deploys run one at a time; everyone else can keep browsing. The GTK app can stay on a single desk and use the same data directory.

```bash
HELIX_ADMIN_PASSWORD='choose-a-password' python3 -m helix_it.web
```

Open `http://127.0.0.1:8080/`. The first account is `admin` unless `HELIX_ADMIN_USER` is set. If you omit `HELIX_ADMIN_PASSWORD`, the generated password is written to `initial-admin.txt` in the data directory (mode 0600). Add the other technicians under **Agents**.

`HELIX_DATA` chooses the directory for the database, secrets, session key, and uploaded installers. `HELIX_BIND` defaults to `0.0.0.0` and `HELIX_PORT` defaults to `8080`. Set `HELIX_HTTPS=1` when a reverse proxy terminates TLS, so the session cookie is marked Secure. `HELIX_ORG` is the shop name on a fresh database. `HELIX_SAMPLE=1` loads the Northline Workshop sample into a fresh database.

### Docker on TrueNAS

The compose file joins the existing macvlan network `loc` (`192.168.1.0/24`) and assigns one static address. From that address Helix reaches Windows computers, the domain controller, and the firewall appliance on the same private network as the rest of the containers.

Copy `.env.example` to `.env`. Set `HELIX_IP` to a free address on `192.168.1.0/24` and keep that address out of the DHCP pool. Set `HELIX_DNS` to the firewall or the domain controller that resolves Active Directory names. Point `HELIX_DATA_PATH` and `HELIX_PACKAGES_PATH` at datasets on the pool, for example `/mnt/tank/apps/helix-it/data`.

```bash
cp .env.example .env
docker compose up -d --build
```

Open `http://<HELIX_IP>:8080/`. The database, secrets, and uploaded installers stay on the datasets mounted at `/data`. `NET_RAW` and `NET_BROADCAST` let the container ping the subnet and send Wake-on-LAN. The `loc` network must already exist on the TrueNAS host; Compose does not create it.

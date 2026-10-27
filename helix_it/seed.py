from __future__ import annotations

from helix_it import network
from helix_it.db import Store, utcnow


PEOPLE = [
    ("Ava Chen", "ava.chen@northline.local", "IT", "Systems admin"),
    ("Marcus Cole", "marcus.cole@northline.local", "IT", "Help desk"),
    ("Priya Nair", "priya.nair@northline.local", "Finance", "Controller"),
    ("Jonah Hale", "jonah.hale@northline.local", "Shop", "Floor lead"),
    ("Elena Ruiz", "elena.ruiz@northline.local", "Design", "CAD lead"),
    ("Sam Okonkwo", "sam.okonkwo@northline.local", "IT", "Network"),
]

DEVICES = [
    {
        "name": "fs-01",
        "hostname": "fs-01.northline.local",
        "ip": "10.20.0.10",
        "mac": "aa:00:00:00:00:10",
        "type": "server",
        "os": "Debian 13",
        "manufacturer": "Dell",
        "model": "PowerEdge R750",
        "serial": "SV-FS01-8841",
        "status": "online",
        "cpu": "Xeon Silver 4310",
        "ram_gb": 64,
        "disk_gb": 8000,
        "owner": "Ava Chen",
        "notes": "Department file shares and Time Machine targets.",
    },
    {
        "name": "sw-core-01",
        "hostname": "sw-core-01",
        "ip": "10.20.0.2",
        "mac": "aa:00:00:00:00:02",
        "type": "network",
        "os": "Cisco IOS",
        "manufacturer": "Cisco",
        "model": "C9200-48P",
        "serial": "FCW2441A1K2",
        "status": "online",
        "owner": "Sam Okonkwo",
        "notes": "Core switch, PoE for APs and phones.",
    },
    {
        "name": "fw-edge",
        "hostname": "fw-edge.northline.local",
        "ip": "10.20.0.1",
        "mac": "aa:00:00:00:00:01",
        "type": "network",
        "os": "OPNsense 25.7",
        "manufacturer": "Protectli",
        "model": "VP4670",
        "serial": "PL-FW-2291",
        "status": "online",
        "owner": "Sam Okonkwo",
        "notes": "Edge firewall / VPN concentrator.",
    },
    {
        "name": "ap-lobby",
        "hostname": "ap-lobby",
        "ip": "10.20.0.21",
        "mac": "aa:00:00:00:00:21",
        "type": "network",
        "os": "UniFi",
        "manufacturer": "Ubiquiti",
        "model": "U6-LR",
        "status": "online",
        "owner": "Sam Okonkwo",
    },
    {
        "name": "prn-shop-color",
        "hostname": "prn-shop-color",
        "ip": "10.20.0.40",
        "mac": "aa:00:00:00:00:40",
        "type": "printer",
        "os": "JetDirect",
        "manufacturer": "HP",
        "model": "Color LaserJet M454",
        "serial": "VNB4K12345",
        "status": "warning",
        "owner": "Jonah Hale",
        "notes": "Low cyan cartridge reported last week.",
    },
    {
        "name": "nas-01",
        "hostname": "nas-01.northline.local",
        "ip": "10.20.0.12",
        "mac": "aa:00:00:00:00:12",
        "type": "server",
        "os": "TrueNAS SCALE",
        "manufacturer": "Synology",
        "model": "RS1221+",
        "status": "online",
        "cpu": "Ryzen V1500B",
        "ram_gb": 32,
        "disk_gb": 48000,
        "owner": "Ava Chen",
    },
    {
        "name": "ws-priya",
        "hostname": "ws-priya",
        "ip": "10.20.14.32",
        "mac": "aa:00:00:14:00:32",
        "type": "computer",
        "os": "Windows 11 Pro",
        "manufacturer": "Lenovo",
        "model": "ThinkCentre M70q",
        "status": "online",
        "cpu": "i5-12500T",
        "ram_gb": 16,
        "disk_gb": 512,
        "owner": "Priya Nair",
        "domain": "northline.local",
        "ou": "Workstations/Finance",
        "architecture": "64-bit",
        "os_version": "10.0.22631",
    },
    {
        "name": "ws-elena",
        "hostname": "ws-elena",
        "ip": "10.20.14.41",
        "mac": "aa:00:00:14:00:41",
        "type": "computer",
        "os": "Windows 11 Pro",
        "manufacturer": "Dell",
        "model": "Precision 3660",
        "status": "online",
        "cpu": "i7-13700",
        "ram_gb": 64,
        "disk_gb": 2000,
        "owner": "Elena Ruiz",
        "notes": "CAD workstation. GPU: RTX 4070.",
        "domain": "northline.local",
        "ou": "Workstations/Design",
        "architecture": "64-bit",
        "os_version": "10.0.22631",
    },
    {
        "name": "dc-01",
        "hostname": "dc-01.northline.local",
        "ip": "10.20.0.5",
        "mac": "aa:00:00:00:00:05",
        "type": "server",
        "os": "Windows Server 2022",
        "domain": "northline.local",
        "ou": "Domain Controllers",
        "architecture": "64-bit",
        "os_version": "10.0.20348",
        "manufacturer": "Dell",
        "model": "PowerEdge R550",
        "status": "online",
        "owner": "Ava Chen",
        "notes": "Sample directory record until a live Active Directory sync replaces it.",
    },
    {
        "name": "lt-marcus",
        "hostname": "lt-marcus",
        "ip": "10.20.14.18",
        "mac": "aa:00:00:14:00:18",
        "type": "computer",
        "os": "Fedora 42",
        "manufacturer": "Framework",
        "model": "Laptop 13",
        "status": "online",
        "cpu": "i5-1340P",
        "ram_gb": 32,
        "disk_gb": 1024,
        "owner": "Marcus Cole",
    },
    {
        "name": "ws-shop-kiosk",
        "hostname": "ws-shop-kiosk",
        "ip": "10.20.30.8",
        "mac": "aa:00:00:30:00:08",
        "type": "computer",
        "os": "Ubuntu 24.04",
        "manufacturer": "Intel",
        "model": "NUC13",
        "status": "offline",
        "cpu": "i5-1340P",
        "ram_gb": 16,
        "disk_gb": 512,
        "owner": "Jonah Hale",
        "notes": "Work order kiosk. Last seen yesterday.",
    },
    {
        "name": "cam-lot-west",
        "hostname": "cam-lot-west",
        "ip": "10.20.40.5",
        "mac": "aa:00:00:40:00:05",
        "type": "other",
        "os": "Hikvision",
        "manufacturer": "Hikvision",
        "model": "DS-2CD2143",
        "status": "online",
        "owner": "Sam Okonkwo",
    },
]

SOFTWARE = {
    "fs-01": [
        ("Samba", "4.21", "Samba Team"),
        ("Cockpit", "332", "Red Hat"),
        ("restic", "0.17", "restic"),
    ],
    "ws-priya": [
        ("Microsoft 365", "2509", "Microsoft"),
        ("Chrome", "129", "Google"),
        ("QuickBooks", "2024", "Intuit"),
    ],
    "ws-elena": [
        ("SolidWorks", "2025 SP2", "Dassault"),
        ("Adobe Acrobat", "24.4", "Adobe"),
        ("Chrome", "129", "Google"),
    ],
    "lt-marcus": [
        ("Firefox", "131", "Mozilla"),
        ("Remmina", "1.4", "Remmina"),
        ("Helix IT", "0.1.0", "Helix"),
    ],
    "ws-shop-kiosk": [
        ("Chrome", "128", "Google"),
        ("CUPS", "2.4", "OpenPrinting"),
    ],
    "nas-01": [
        ("ZFS", "2.3", "OpenZFS"),
        ("Syncthing", "1.27", "Syncthing"),
    ],
}

TICKETS = [
    (
        "Shop kiosk will not boot past GRUB",
        "Jonah says the work-order PC in bay 2 sits on a black GRUB screen after last week's power blip.",
        "open",
        "high",
        "Jonah Hale",
        "Marcus Cole",
        "ws-shop-kiosk",
    ),
    (
        "Color printer banding on shop packets",
        "Cyan looks washed out and every 4th page has a stripe. Cartridge may be empty.",
        "waiting",
        "medium",
        "Jonah Hale",
        "Marcus Cole",
        "prn-shop-color",
    ),
    (
        "VPN drops for remote CAD users after 20 minutes",
        "Elena can connect from home but the tunnel dies during large assembly checkouts.",
        "open",
        "critical",
        "Elena Ruiz",
        "Sam Okonkwo",
        "fw-edge",
    ),
    (
        "Need QuickBooks access for temp accountant",
        "Priya requested a license and a mapped Q: drive on fs-01.",
        "new",
        "low",
        "Priya Nair",
        "Ava Chen",
        "fs-01",
    ),
    (
        "Replace lobby AP — roaming complaints",
        "Phones stick to 2.4 GHz near the front desk. AP is due for a swap to U7.",
        "open",
        "medium",
        "Sam Okonkwo",
        "Sam Okonkwo",
        "ap-lobby",
    ),
    (
        "Onboard Framework laptop for help desk",
        "Install inventory agent, VPN profile, and printer queues.",
        "closed",
        "low",
        "Marcus Cole",
        "Ava Chen",
        "lt-marcus",
    ),
    (
        "NAS scrub found 2 checksum errors",
        "TrueNAS reported checksum mismatches on tank/archive. Disks otherwise healthy.",
        "open",
        "high",
        "Ava Chen",
        "Ava Chen",
        "nas-01",
    ),
]


def seed_if_needed(store: Store) -> None:
    if store.get_meta("seeded"):
        upsert_this_machine(store)
        return
    seed(store)


def seed(store: Store) -> None:
    store.reset_demo()
    store.set_meta("org_name", "Northline Workshop")
    store.set_meta("tech_name", "IT Desk")
    people_ids: dict[str, int] = {}
    for name, email, department, title in PEOPLE:
        people_ids[name] = store.add_person(name, email, department, title)

    names: dict[str, int] = {}
    now = utcnow()
    for device in DEVICES:
        payload = dict(device)
        owner = people_ids.get(payload.pop("owner"))
        device_id = store.add_device(
            last_seen=now,
            owner_id=owner,
            discovered=0,
            **payload,
        )
        names[payload["name"]] = device_id
        for pkg in SOFTWARE.get(payload["name"], []):
            store.execute(
                "INSERT INTO software(device_id, name, version, publisher) VALUES (?, ?, ?, ?)",
                (device_id, *pkg),
            )

    for title, description, status, priority, requester, assignee, device_name in TICKETS:
        store.add_ticket(
            title,
            description,
            priority,
            people_ids.get(requester),
            assignee,
            names.get(device_name),
        )
        ticket = store.fetchone("SELECT id FROM tickets WHERE title = ?", (title,))
        if ticket and status != "open":
            store.update_ticket(ticket["id"], status=status)

    store.execute(
        "INSERT INTO comments(ticket_id, author, body, created_at) VALUES (?, ?, ?, ?)",
        (
            store.fetchone("SELECT id FROM tickets WHERE title LIKE 'Shop kiosk%'")["id"],
            "Marcus Cole",
            "Checked in person — drive is visible in BIOS. Will try a live USB next.",
            now,
        ),
    )
    upsert_this_machine(store)
    store.log("system", "Loaded sample inventory for Northline Workshop")
    store.set_meta("seeded", "1")
    store.ensure_builtin()


def upsert_this_machine(store: Store) -> None:
    host = network.local_hostname()
    ip = network.default_ip()
    mac = network.default_mac()
    row = store.fetchone("SELECT id FROM devices WHERE discovered = 2 LIMIT 1")
    fields = {
        "name": host,
        "hostname": host,
        "ip": ip,
        "mac": mac,
        "type": "computer",
        "os": network.os_pretty_name(),
        "manufacturer": "Local",
        "model": "This Linux workstation",
        "status": "online",
        "last_seen": utcnow(),
        "cpu": network.cpu_model(),
        "ram_gb": network.ram_gb(),
        "notes": "Helix IT console host. Added automatically from this machine.",
        "discovered": 2,
    }
    if row:
        store.update_device(row["id"], **fields)
        return
    store.add_device(**fields)
    store.log("system", f"Registered this workstation as {host}")

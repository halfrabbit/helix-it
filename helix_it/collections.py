from __future__ import annotations

TEXT_FIELDS = (
    "name",
    "hostname",
    "os",
    "os_version",
    "ou",
    "ip",
    "status",
    "architecture",
    "domain",
    "manufacturer",
    "model",
    "type",
    "scan_status",
    "description",
    "current_user",
)

LIST_FIELDS = ("software", "hotfix", "group")

FIELDS = (
    ("name", "Computer name"),
    ("hostname", "Hostname"),
    ("os", "Operating system"),
    ("os_version", "OS version"),
    ("ou", "OU"),
    ("ip", "IP address"),
    ("status", "Status"),
    ("architecture", "Architecture"),
    ("domain", "Domain"),
    ("manufacturer", "Manufacturer"),
    ("model", "Model"),
    ("type", "Type"),
    ("scan_status", "Scan status"),
    ("description", "Description"),
    ("current_user", "Current user"),
    ("software", "Installed software"),
    ("hotfix", "Hotfix"),
    ("group", "AD group"),
)

OPS = (
    ("contains", "contains"),
    ("equals", "equals"),
    ("starts", "starts with"),
    ("not_contains", "does not contain"),
    ("not_equals", "does not equal"),
    ("missing", "is missing"),
    ("present", "is present"),
)


def _has(items: set[str], op: str, needle: str) -> bool:
    value = needle.strip().lower()
    if op == "missing":
        return not any(value in item for item in items) if value else not items
    if op == "present":
        return any(value in item for item in items) if value else bool(items)
    if op == "equals":
        return any(item == value for item in items)
    if op == "starts":
        return any(item.startswith(value) for item in items)
    if op == "not_equals":
        return all(item != value for item in items)
    if op == "not_contains":
        return all(value not in item for item in items)
    return any(value in item for item in items)


def _text(hay: str, op: str, needle: str) -> bool:
    left = hay.strip().lower()
    value = needle.strip().lower()
    if op == "missing":
        return left == ""
    if op == "present":
        return left != ""
    if op == "equals":
        return left == value
    if op == "starts":
        return left.startswith(value)
    if op == "not_equals":
        return left != value
    if op == "not_contains":
        return value not in left
    return value in left


def matches(text: dict[str, str], lists: dict[str, set[str]], field: str, op: str, value: str) -> bool:
    if field in LIST_FIELDS:
        return _has(lists.get(field) or set(), op or "contains", value or "")
    return _text(text.get(field, ""), op or "contains", value or "")


def select_ids(
    kind: str,
    match_mode: str,
    filters: list[tuple[str, str, str]],
    static_ids: set[int],
    facts: list[dict],
) -> list[int]:
    dynamic: list[int] = []
    if kind in {"dynamic", "mixed"} and filters:
        want_all = (match_mode or "all") != "any"
        for fact in facts:
            hits = [
                matches(fact["text"], fact["lists"], field, op, value) for field, op, value in filters
            ]
            if hits and (all(hits) if want_all else any(hits)):
                dynamic.append(int(fact["id"]))
    if kind == "static":
        allowed = static_ids
        return [int(fact["id"]) for fact in facts if int(fact["id"]) in allowed]
    if kind == "mixed":
        allowed = set(dynamic) | set(static_ids)
        return [int(fact["id"]) for fact in facts if int(fact["id"]) in allowed]
    return dynamic

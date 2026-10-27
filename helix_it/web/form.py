from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import parse_qs


MAX_BODY = 512 * 1024 * 1024


@dataclass
class Form:
    fields: dict[str, str] = field(default_factory=dict)
    files: dict[str, tuple[str, bytes]] = field(default_factory=dict)

    def get(self, key: str, default: str = "") -> str:
        return self.fields.get(key, default)


def parse_body(content_type: str, body: bytes) -> Form:
    if len(body) > MAX_BODY:
        raise ValueError("Upload is larger than 512 MB.")
    if "multipart/form-data" in content_type.lower():
        return _multipart(content_type, body)
    text = body.decode("utf-8", errors="replace")
    parsed = parse_qs(text, keep_blank_values=True)
    return Form({key: values[-1] for key, values in parsed.items()})


def _boundary(content_type: str) -> bytes:
    for part in content_type.split(";"):
        item = part.strip()
        if item.lower().startswith("boundary="):
            value = item.split("=", 1)[1].strip().strip('"')
            return value.encode("utf-8")
    raise ValueError("Upload is missing a boundary.")


def _disposition(headers: str) -> tuple[str, str]:
    name = ""
    filename = ""
    for line in headers.splitlines():
        if not line.lower().startswith("content-disposition"):
            continue
        for piece in line.split(";"):
            item = piece.strip()
            lowered = item.lower()
            if lowered.startswith("name="):
                name = item.split("=", 1)[1].strip().strip('"')
            elif lowered.startswith("filename="):
                filename = item.split("=", 1)[1].strip().strip('"')
    return name, filename


def _multipart(content_type: str, body: bytes) -> Form:
    boundary = b"--" + _boundary(content_type)
    form = Form()
    for chunk in body.split(boundary):
        if not chunk or chunk in {b"--", b"--\r\n"}:
            continue
        chunk = chunk.removeprefix(b"\r\n").removesuffix(b"\r\n").removesuffix(b"--")
        if chunk.endswith(b"--"):
            chunk = chunk[:-2]
        header_blob, sep, data = chunk.partition(b"\r\n\r\n")
        if not sep:
            continue
        if data.endswith(b"\r\n"):
            data = data[:-2]
        headers = header_blob.decode("utf-8", errors="replace")
        name, filename = _disposition(headers)
        if not name:
            continue
        if filename:
            form.files[name] = (filename, data)
        else:
            form.fields[name] = data.decode("utf-8", errors="replace")
    return form

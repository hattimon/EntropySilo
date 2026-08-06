#!/usr/bin/env python3
"""One-shot systemd broker for the closed GUI-to-root operation protocol."""
from __future__ import annotations

import json
import os
import subprocess
import sys

HELPER = "/usr/local/sbin/entropysilo-usb"
INPUT_LIMITS = {
    "read-psbt": 0, "list-psbts": 0, "read-selected-psbt": 128,
    "read-secret": 0, "list-backups": 0,
    "read-backup": 128, "read-qr-png": 0, "read-qr-jpg": 0,
    "write-signed-psbt": 2 * 1024 * 1024,
    "write-signed-txn": 2 * 1024 * 1024,
    "write-selected-signed-psbt": 2 * 1024 * 1024 + 128,
    "write-selected-signed-txn": 2 * 1024 * 1024 + 128,
    "write-backup": 16 * 1024 * 1024,
    "probe": 0, "poweroff": 0,
}
OUTPUT_LIMITS = {
    "read-psbt": 2 * 1024 * 1024, "list-psbts": 256 * 1024,
    "read-selected-psbt": 2 * 1024 * 1024, "read-secret": 64 * 1024,
    "list-backups": 256 * 1024, "read-backup": 16 * 1024 * 1024,
    "read-qr-png": 16 * 1024 * 1024, "read-qr-jpg": 16 * 1024 * 1024,
    "write-signed-psbt": 4096, "write-signed-txn": 4096,
    "write-selected-signed-psbt": 4096, "write-selected-signed-txn": 4096,
    "write-backup": 4096, "probe": 4096, "poweroff": 4096,
}


def response(ok: bool, payload: bytes = b"", error: str = "") -> None:
    header = {"ok": ok, "size": len(payload)}
    if error: header["error"] = error[:4096]
    sys.stdout.buffer.write(json.dumps(header, separators=(",", ":")).encode("utf-8") + b"\n" + payload)
    sys.stdout.buffer.flush()


def read_exact(size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining:
        chunk = sys.stdin.buffer.read(min(65536, remaining))
        if not chunk: raise ValueError("Niepełne dane żądania.")
        chunks.append(chunk); remaining -= len(chunk)
    return b"".join(chunks)


def main() -> None:
    header_line = sys.stdin.buffer.readline(4097)
    if not header_line or len(header_line) > 4096 or not header_line.endswith(b"\n"):
        raise ValueError("Nieprawidłowy nagłówek żądania.")
    header = json.loads(header_line)
    action = header.get("action"); size = header.get("size")
    if action not in INPUT_LIMITS or not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ValueError("Niedozwolona operacja uprzywilejowana.")
    if size > INPUT_LIMITS[action]: raise ValueError("Dane wejściowe przekraczają limit operacji.")
    payload = read_exact(size)
    if sys.stdin.buffer.read(1): raise ValueError("Nadmiarowe dane żądania.")

    if action == "poweroff":
        response(True, b"POWERING_OFF\n")
        subprocess.run(["/usr/bin/systemctl", "poweroff", "--no-block"], timeout=10, check=True,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"})
        return

    completed = subprocess.run([HELPER, action], input=payload, capture_output=True, timeout=180,
        check=False, env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"})
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", "replace").strip() or "Operacja helpera USB nie powiodła się."
        response(False, error=message); return
    if len(completed.stdout) > OUTPUT_LIMITS[action]: raise ValueError("Odpowiedź przekracza limit operacji.")
    response(True, completed.stdout)


try:
    main()
except Exception as error:
    response(False, error=str(error))

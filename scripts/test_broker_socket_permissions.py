#!/usr/bin/env python3
"""Regression test for root-owned broker directory and group-restricted socket."""
import os
import socket
import tempfile


if os.geteuid() != 0:
    raise SystemExit("run as root")

test_uid = 29001
test_gid = 29001
with tempfile.TemporaryDirectory(prefix="entropysilo-socket-test-") as root:
    os.chmod(root, 0o755)
    broker = os.path.join(root, "entropysilo-privileged")
    os.mkdir(broker, 0o755)
    endpoint = os.path.join(broker, "control.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(endpoint)
    os.chown(endpoint, 0, test_gid)
    os.chmod(endpoint, 0o660)
    server.listen(1)
    server.settimeout(5)

    child = os.fork()
    if child == 0:
        try:
            os.setgroups([])
            os.setgid(test_gid)
            os.setuid(test_uid)
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.connect(endpoint)
            client.sendall(b"OK")
            client.close()
            os._exit(0)
        except Exception:
            os._exit(1)

    connection, _ = server.accept()
    payload = connection.recv(2)
    connection.close()
    _, status = os.waitpid(child, 0)
    if payload != b"OK" or os.waitstatus_to_exitcode(status) != 0:
        raise SystemExit("wallet-group socket connection failed")

print("BROKER_SOCKET_PERMISSION_TEST_OK")

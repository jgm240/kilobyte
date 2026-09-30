#!/usr/bin/python3
"""deskrun.py ARGS...: ask Kilobyte Windows to run kb-play ARGS on the whole
screen (see screen_request in desk.py) and wait until it has ended.
Exit status: that of kb-play; 125 when Kilobyte Windows cannot be reached."""
import json
import os
import socket
import sys

try:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(os.environ["KB_DESK_SOCK"])
    s.sendall(json.dumps({"run": "kb-play", "args": sys.argv[1:], "cwd": os.getcwd()}).encode("utf-8") + b"\n")
    reply = b""
    while not reply.endswith(b"\n"):
        chunk = s.recv(64)
        if not chunk:
            break
        reply += chunk
    sys.exit(int(reply.strip() or 125))
except (KeyError, OSError, ValueError):
    sys.exit(125)

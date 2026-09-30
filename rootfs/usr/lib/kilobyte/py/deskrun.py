#!/usr/bin/python3
"""Ask Kilobyte Windows for something (see screen_request in desk.py).

    deskrun.py play ARGS...              kb-play ARGS on the whole screen; waits
    deskrun.py lock                      the lock screen on the whole screen
    deskrun.py window TITLE SIZE ARGV... a new window running ARGV (S, M or L)
    deskrun.py notify TITLE [TEXT]       a note in the corner of the screen
    deskrun.py clip                      put standard input on the clipboard

Exit status: that of the program for play and lock, otherwise 0;
125 when Kilobyte Windows cannot be reached."""
import json
import os
import socket
import sys


def ask(request):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(os.environ["KB_DESK_SOCK"])
    s.sendall(json.dumps(request).encode("utf-8") + b"\n")
    reply = b""
    while not reply.endswith(b"\n"):
        chunk = s.recv(64)
        if not chunk:
            break
        reply += chunk
    return int(reply.strip() or 125)


def main(argv):
    if not argv:
        return 2
    what, args = argv[0], argv[1:]
    request = {"run": what, "cwd": os.getcwd()}
    if what == "play":
        request = {"run": "kb-play", "args": args, "cwd": os.getcwd()}
    elif what == "window" and len(args) >= 3:
        request.update(title=args[0], size=args[1], argv=args[2:])
    elif what == "notify" and args:
        request.update(title=args[0], text=" ".join(args[1:]))
    elif what == "clip":
        request.update(text=sys.stdin.read())
    elif what != "lock":
        return 2
    return ask(request)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (KeyError, OSError, ValueError):
        sys.exit(125)

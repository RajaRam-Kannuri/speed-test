#!/usr/bin/env python3
"""Development SMTP server that saves each message as a .eml file instead of delivering it.

    python3 scripts/smtp-sink.py --port 2525 --dir .dev/mail

Point the API at it with LLX_SMTP_HOST=127.0.0.1 LLX_SMTP_PORT=2525 LLX_SMTP_SECURITY=none.
Used by the end-to-end tests to follow password reset links. Not for production.
"""

from __future__ import annotations

import argparse
import socketserver
import time
from pathlib import Path


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        def say(line: str):
            self.wfile.write((line + "\r\n").encode())

        say("220 smtp-sink ready")
        while True:
            line = self.rfile.readline()
            if not line:
                return
            cmd = line.decode(errors="replace").strip().upper()
            if cmd.startswith(("EHLO", "HELO")):
                say("250-smtp-sink")
                say("250 OK")
            elif cmd == "DATA":
                say("354 end with <CRLF>.<CRLF>")
                data = b""
                while True:
                    chunk = self.rfile.readline()
                    if chunk in (b".\r\n", b""):
                        break
                    data += chunk[1:] if chunk.startswith(b"..") else chunk
                path = self.server.maildir / f"{time.time_ns()}.eml"
                path.write_bytes(data)
                say("250 queued")
            elif cmd == "QUIT":
                say("221 bye")
                return
            else:
                say("250 OK")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=2525)
    parser.add_argument("--dir", default=".dev/mail")
    args = parser.parse_args()
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    server = socketserver.ThreadingTCPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    server.maildir = Path(args.dir)
    server.maildir.mkdir(parents=True, exist_ok=True)
    print(f"smtp-sink listening on 127.0.0.1:{args.port}, saving to {server.maildir}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

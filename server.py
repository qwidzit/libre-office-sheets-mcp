#!/usr/bin/env python3
"""MCP server for LibreOffice Calc.

Run this with LibreOffice's own Python, which bundles the UNO bindings:

    "C:\\Program Files\\LibreOffice\\program\\python.exe" server.py

It speaks MCP over stdio and needs nothing from PyPI.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from locmcp import tools  # noqa: F401,E402  (import registers the tools)
from locmcp.jsonrpc import Server, log  # noqa: E402
from locmcp.protocol import HANDLERS  # noqa: E402
from locmcp.registry import all_tools  # noqa: E402


def main():
    log("starting, %d tools registered, python %s" % (len(all_tools()), sys.version.split()[0]))
    try:
        Server(HANDLERS).serve_forever()
    except KeyboardInterrupt:
        pass
    log("stopped")


if __name__ == "__main__":
    main()

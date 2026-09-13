#!/usr/bin/env python3
"""Diagnose a LibreOffice Calc MCP setup, and print the config to paste into
Claude Desktop. Run it with LibreOffice's own Python:

    "C:\\Program Files\\LibreOffice\\program\\python.exe" scripts\\check-setup.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("interpreter : %s" % sys.executable)
print("  is a file : %s" % (os.path.isfile(sys.executable) if sys.executable else "n/a"))
print("version     : %s" % sys.version.split()[0])
print("prefix      : %s" % getattr(sys, "prefix", ""))

try:
    import uno  # noqa: F401
    print("uno module  : OK")
except ImportError as exc:
    print("uno module  : MISSING (%s)" % exc)
    print("\nRun this with LibreOffice's bundled Python, usually:")
    print(r"  C:\Program Files\LibreOffice\program\python.exe")
    sys.exit(1)

from locmcp import bridge  # noqa: E402


def _spawnable():
    try:
        bridge.find_interpreter()
        return True
    except Exception:
        return False

print("spawnable   : %s" % (bridge.find_interpreter()
                            if _spawnable() else "NONE FOUND"))
print("search dirs : %s" % ", ".join(bridge.interpreter_dirs()))

found = bridge._soffice_path()
print("soffice     : %s" % (found or "NOT FOUND"))
print("\nsoffice candidates, in order:")
for candidate in bridge._soffice_candidates():
    print("   [%s] %s" % ("x" if os.path.exists(candidate) else " ", candidate))
if not found:
    print("\nSet LOCALC_MCP_SOFFICE to the full path of soffice if it is elsewhere.")
print("target      : %s:%d" % (bridge.HOST, bridge.PORT))
print("autolaunch  : %s" % ("on" if bridge.AUTOLAUNCH else "off"))

try:
    conn = bridge.connect()
except Exception as exc:
    print("connection  : FAILED\n\n%s" % exc)
    sys.exit(1)

print("connection  : OK")
docs = bridge.calc_documents(conn)
print("open sheets : %d" % len(docs))
for doc in docs:
    print("   - %s (%s)" % (bridge.doc_label(doc), bridge.doc_path(doc) or "unsaved"))

from locmcp import tools  # noqa: F401,E402  (registers the tools)
from locmcp.registry import all_tools  # noqa: E402

print("tools       : %d registered" % len(all_tools()))

print("\n" + "=" * 68)
print("Everything works. Copy the block below into Claude Desktop's config file")
print("(Settings > Developer > Edit Config), then restart Claude Desktop.")
print("=" * 68 + "\n")
print(json.dumps({
    "mcpServers": {
        "libreoffice-calc": {
            "command": sys.executable,
            "args": [os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "server.py")],
        }
    }
}, indent=2))
print()

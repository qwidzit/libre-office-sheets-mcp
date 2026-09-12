#!/usr/bin/env python3
"""Diagnose a LibreOffice Calc MCP setup. Run it with LibreOffice's own Python:

    "C:\\Program Files\\LibreOffice\\program\\python.exe" scripts\\check-setup.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("interpreter : %s" % sys.executable)
print("version     : %s" % sys.version.split()[0])

try:
    import uno  # noqa: F401
    print("uno module  : OK")
except ImportError as exc:
    print("uno module  : MISSING (%s)" % exc)
    print("\nRun this with LibreOffice's bundled Python, usually:")
    print(r"  C:\Program Files\LibreOffice\program\python.exe")
    sys.exit(1)

from locmcp import bridge  # noqa: E402

print("soffice     : %s" % (bridge._soffice_path() or "NOT FOUND"))
print("target      : %s:%d" % (bridge.HOST, bridge.PORT))

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
print("\nSetup looks good.")

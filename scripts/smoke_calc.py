#!/usr/bin/env python3
"""End-to-end test: drives server.py over MCP against a live LibreOffice Calc.

Requires LibreOffice already listening:
    soffice --calc --accept="socket,host=127.0.0.1,port=2002;urp;"
"""

import json
import os
import queue
import subprocess
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import direct_uno  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from locmcp.bridge import find_interpreter  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.environ.get("SMOKE_OUT", "/tmp/calc-smoke")


# A UNO call that blocks -- a modal dialog in LibreOffice is the usual cause --
# would otherwise hang the suite until CI kills the job hours later, with no
# indication of which call was responsible.
CALL_TIMEOUT = float(os.environ.get("SMOKE_CALL_TIMEOUT", "120"))


class Client(object):
    def __init__(self):
        env = dict(os.environ, LOCALC_MCP_ENABLE_EXEC="1")
        self.proc = subprocess.Popen(
            [find_interpreter(), os.path.join(ROOT, "server.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, bufsize=1, env=env,
        )
        self.next_id = 0
        self._lines = queue.Queue()
        self._pump = threading.Thread(target=self._read_stdout, daemon=True)
        self._pump.start()
        self.request("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "smoke-calc", "version": "0"},
        })
        self.notify("notifications/initialized")

    def _read_stdout(self):
        try:
            for line in self.proc.stdout:
                self._lines.put(line)
        finally:
            self._lines.put(None)

    def notify(self, method, params=None):
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method,
                                          "params": params or {}}) + "\n")
        self.proc.stdin.flush()

    def request(self, method, params, label=None):
        self.next_id += 1
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.next_id,
                                          "method": method, "params": params}) + "\n")
        self.proc.stdin.flush()
        what = label or method
        try:
            line = self._lines.get(timeout=CALL_TIMEOUT)
        except queue.Empty:
            raise AssertionError(
                "TIMEOUT: no reply to %s after %.0fs. The server is most likely "
                "blocked on a UNO call -- a modal LibreOffice dialog will do it. "
                "The last 'operation:' line on stderr says how far it got."
                % (what, CALL_TIMEOUT))
        if line is None:
            raise AssertionError("The server exited while handling %s." % what)
        return json.loads(line)

    def call(self, _tool, **arguments):
        reply = self.request(
            "tools/call", {"name": _tool, "arguments": arguments}, label="tool %s" % _tool)
        if "error" in reply:
            return False, json.dumps(reply["error"])
        result = reply["result"]
        return not result.get("isError", False), result["content"][0]["text"]

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


FAILURES = []
STEP = [0]


def step(label, ok, text, expect=None, quiet=False):
    STEP[0] += 1
    good = ok
    if good and expect:
        for needle in ([expect] if isinstance(expect, str) else expect):
            if needle.lower() not in text.lower():
                good = False
                text += "\n  (expected to contain %r)" % needle
    print("\n%2d. %s %s" % (STEP[0], "PASS" if good else "FAIL", label), flush=True)
    if not good or not quiet:
        for line in text.splitlines()[:18]:
            print("      " + line)
        sys.stdout.flush()
    if not good:
        FAILURES.append(label)
    return good


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    target = os.path.join(OUT_DIR, "budget.ods")
    # Start from a known state: a document left open by an earlier suite
    # would otherwise be picked up as the target.
    direct_uno.close_all()
    client = Client()

    ok, text = client.call("calc_status")
    step("calc_status connects", ok, text)

    ok, text = client.call("open_document")
    step("open a new blank spreadsheet", ok, text, expect="Sheets:")

    ok, text = client.call("manage_sheets", operation="rename", name="0", new_name="Budget")
    step("rename the first sheet", ok, text, expect="Budget")

    rows = [
        ["Item", "Qty", "Unit price", "Total"],
        ["Widget", 10, 2.5, "=B2*C2"],
        ["Gadget", 3, 19.99, "=B3*C3"],
        ["Doohickey", 7, 4.25, "=B4*C4"],
        ["Sprocket", 22, 1.1, "=B5*C5"],
    ]
    ok, text = client.call("write_range", range="A1", values=rows)
    step("write a table with formulas", ok, text,
         expect=["5 rows x 4 cols", "recalculated cleanly"])

    ok, text = client.call("write_range", range="A7",
                           values=[["Grand total", "", "", "=SUM(D2:D5)"]])
    step("write a SUM row", ok, text, expect="recalculated cleanly")

    ok, text = client.call("read_range", range="A1:D7", include_formulas=True)
    step("read back values and formulas", ok, text,
         expect=["Widget", "25", "=SUM(D2:D5)", "FORMULAS"])
    # 10*2.5 + 3*19.99 + 7*4.25 + 22*1.1 = 25 + 59.97 + 29.75 + 24.2 = 138.92
    step("computed grand total is correct", "138.92" in text, text, quiet=True)

    ok, text = client.call("write_range", range="F1", values=[["=BROKEN(1)"]])
    step("a bad formula is reported, not silently accepted", ok, text, expect="#NAME?")
    client.call("clear_range", range="F1", what="all")

    ok, text = client.call("format_range", range="A1:D1", bold=True,
                           background_color="#4472c4", text_color="white",
                           align="center", borders="outer")
    step("format the header row", ok, text, expect=["bold=True", "fill=", "borders=outer"])

    ok, text = client.call("format_range", range="C2:D7", number_format="#,##0.00")
    step("apply a number format", ok, text, expect="number_format")

    ok, text = client.call("size_cells", columns="A:D", optimal=True)
    step("fit columns to contents", ok, text, expect="fitted to contents")

    ok, text = client.call("freeze_panes", at="A2")
    step("freeze the header row", ok, text, expect="Froze")

    ok, text = client.call("sort_range", range="A1:D5",
                           by=[{"column": "Qty", "descending": True}], has_header=True)
    step("sort by a header name, descending", ok, text, expect=["Qty (B) desc", "header row kept"])

    ok, text = client.call("read_range", range="A1:B5")
    order = [line.split("\t")[1] for line in text.splitlines()
             if line[:1].isdigit() and "\t" in line]
    step("sort actually reordered the rows",
         ok and order == ["Item", "Sprocket", "Widget", "Doohickey", "Gadget"],
         text + "\n  (order was %r)" % (order,), quiet=True)

    ok, text = client.call("find_cells", query="Gadget")
    step("find a cell", ok, text, expect="Gadget")

    ok, text = client.call("find_replace", query="Doohickey", replacement="Bracket")
    step("find and replace", ok, text, expect="1 cell")

    ok, text = client.call("structure_edit", operation="insert_rows", at="1", count=2)
    step("insert two rows at the top", ok, text, expect="Inserted 2 rows")

    ok, text = client.call("write_range", range="A1", values=[["Q3 parts budget"]])
    step("write a title into the new space", ok, text, expect="1 rows x 1 cols")

    ok, text = client.call("read_range", range="A1:D9")
    step("formulas survived the row insert", ok and "138.92" in text, text, quiet=True)

    ok, text = client.call("create_chart", range="A3:B7", chart_type="column",
                           title="Quantity by item", anchor="F3")
    step("create a chart", ok, text, expect="column chart")

    ok, text = client.call("manage_sheets", operation="add", name="Notes")
    step("add a sheet", ok, text, expect="Notes")

    ok, text = client.call("write_range", sheet="Notes", range="A1",
                           values=[["Cross-sheet check"], ["=Budget.D9"]])
    step("write a cross-sheet formula", ok, text, expect="recalculated cleanly")

    ok, text = client.call("read_range", range="Notes.A1:A2")
    step("cross-sheet reference resolves", ok and "138.92" in text, text, quiet=True)

    ok, text = client.call("manage_sheets", operation="copy", name="Notes", new_name="Notes copy")
    step("copy a sheet", ok, text, expect="Notes copy")

    ok, text = client.call("manage_sheets", operation="delete", name="Notes copy")
    step("delete a sheet", ok, text, expect="Deleted")

    ok, text = client.call("save_document", path=target)
    step("save as .ods", ok and os.path.exists(target), text, expect="ods")

    xlsx = os.path.join(OUT_DIR, "budget.xlsx")
    ok, text = client.call("save_document", path=xlsx)
    step("save as .xlsx", ok and os.path.exists(xlsx), text, expect="xlsx")

    ok, text = client.call("run_uno_script",
                           code="result = sheet.Name + ' has ' + str(sheets.Count) + ' sheets'")
    step("run_uno_script escape hatch", ok, text, expect="sheets")

    ok, text = client.call("read_range", range="ZZ:ZZ")
    step("reading an empty column is handled", ok, text, quiet=True)

    ok, text = client.call("write_range", range="A1:B2", values=[[1, 2, 3]])
    step("shape mismatch is rejected with a clear message", not ok, text, expect="values")

    ok, text = client.call("read_range", sheet="NoSuchSheet")
    step("a bad sheet name lists the real sheets", not ok, text, expect="Sheets:")

    ok, text = client.call("read_range", range="!!bogus!!")
    step("a bad range is rejected clearly", not ok, text, expect="parse")

    ok, text = client.call("calc_status")
    step("final status", ok, text)

    direct_uno.close_all()
    client.close()
    print("\n" + "=" * 60)
    if FAILURES:
        print("FAILURES (%d): %s" % (len(FAILURES), FAILURES))
        return 1
    print("ALL %d END-TO-END CHECKS PASSED" % STEP[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())

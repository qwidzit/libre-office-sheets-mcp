#!/usr/bin/env python3
"""Second end-to-end pass: dates, undo grouping, and reopening saved files."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import direct_uno  # noqa: E402
from smoke_calc import Client, FAILURES, step  # noqa: E402

OUT_DIR = os.environ.get("SMOKE_OUT", "/tmp/calc-smoke")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "extras.ods")
    # Start from a known state: a document left open by an earlier suite
    # would otherwise be picked up as the target.
    direct_uno.close_all()
    client = Client()

    client.call("open_document")
    client.call("manage_sheets", operation="rename", name="0", new_name="Data")

    # --- dates ---------------------------------------------------------------
    client.call("write_range", range="A1", values=[
        ["Date", "Amount"],
        ["=DATE(2026,3,15)", 100],
        ["=DATE(2026,4,1)", 250],
    ])
    client.call("format_range", range="A2:A3", number_format="YYYY-MM-DD")
    ok, text = client.call("read_range", range="A1:B3")
    step("date cells read back as dates, not serial numbers",
         ok and "2026-03-15" in text and "2026-04-01" in text, text)

    ok, text = client.call("read_range", range="B1:B3")
    step("plain numbers are not mistaken for dates",
         ok and "100" in text and "1899" not in text and "1970" not in text, text)

    # --- undo grouping -------------------------------------------------------
    # getAllUndoActionTitles() is newest-first, and undo() must be called from
    # outside any open undo context -- so drive it over a direct UNO connection,
    # which is what pressing Ctrl+Z in the window actually does.
    before = direct_uno.undo_titles()
    client.call("write_range", range="D1", values=[
        ["x", 1], ["y", 2], ["z", 3], ["w", 4],
    ])
    after = direct_uno.undo_titles()
    step("a multi-cell write is a single undo entry",
         len(after) == len(before) + 1,
         "undo entries went from %d to %d (newest: %r)" % (len(before), len(after), after[:2]))

    ok, text = client.call("read_range", range="D1:E4")
    step("the block was written", ok and "w" in text and "4" in text, text, quiet=True)

    # The guarantee that matters: a write which destroys existing data is
    # reversible. (Writing into cells that were empty is the documented
    # LibreOffice exception, and it loses nothing.)
    client.call("write_range", range="D1", values=[
        ["a", 9], ["b", 8], ["c", 7], ["d", 6],
    ])
    direct_uno.undo()
    ok, text = client.call("read_range", range="D1:E4")
    step("one Ctrl+Z restores data an overwrite destroyed",
         ok and "x" in text and "w" in text and "a" not in text.split("\n", 1)[1],
         text)

    # --- save and reopen -----------------------------------------------------
    client.call("write_range", range="A5", values=[["Total", "=SUM(B2:B3)"]])
    ok, text = client.call("save_document", path=path)
    step("save to .ods", ok and os.path.exists(path), text, quiet=True)

    ok, text = client.call("run_uno_script", code="doc.setModified(False); doc.close(False)")
    step("close the document", ok, text, quiet=True)

    ok, text = client.call("open_document", path=path)
    step("reopen the saved file", ok, text, expect="Data")

    ok, text = client.call("read_range", range="A1:B5", include_formulas=True)
    step("saved values, dates and formulas all survived the round trip",
         ok and "2026-03-15" in text and "350" in text and "=SUM(B2:B3)" in text, text)

    ok, text = client.call("size_cells", columns="A:B", visible=False)
    step("hide columns", ok, text, expect="visible=False")
    ok, text = client.call("size_cells", columns="A:B", visible=True)
    step("show columns again", ok, text, expect="visible=True")

    ok, text = client.call("find_replace", query="Tot.l", replacement="Sum", regex=True)
    step("regex replace", ok, text, expect="1 cell")

    ok, text = client.call("clear_range", range="A5:B5", what="all")
    step("clear a range", ok, text, expect="Cleared all")

    client.call("run_uno_script", code="doc.setModified(False); doc.close(False)")
    client.close()

    print("\n" + "=" * 60)
    if FAILURES:
        print("FAILURES (%d): %s" % (len(FAILURES), FAILURES))
        return 1
    print("ALL EXTRA CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

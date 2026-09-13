#!/usr/bin/env python3
"""End-to-end tests for outline grouping and advanced filtering."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from smoke_calc import Client, FAILURES, step  # noqa: E402

TABLE = [
    ["Region", "Rep", "Amount"],
    ["North", "Ann", 100],
    ["North", "Bob", 50],
    ["South", "Cid", 70],
    ["South", "Ann", 30],
    ["East", "Bob", 20],
]


def col(text, index=0):
    """One column of a read_range grid, header row included."""
    out = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) > 1 and parts[0].isdigit():
            out.append(parts[1 + index])
    return out


def main():
    client = Client()
    client.call("open_document")
    client.call("manage_sheets", operation="rename", name="0", new_name="Sales")
    client.call("write_range", range="A1", values=TABLE)

    # ---- outline grouping -------------------------------------------------
    ok, text = client.call("outline", operation="group", range="2:3")
    step("group rows 2:3", ok, text, expect="Grouped rows 2:3")

    ok, text = client.call("outline", operation="collapse", range="2:3")
    step("collapse the group", ok, text, expect="Collapsed")
    ok, text = client.call("read_range", range="A1:C6", visible_only=True)
    step("collapsed rows are hidden",
         ok and col(text) == ["Region", "South", "South", "East"], text)

    ok, text = client.call("outline", operation="expand", range="2:3")
    step("expand the group", ok, text, expect="Expanded")
    ok, text = client.call("read_range", range="A1:C6", visible_only=True)
    step("expanding brings the rows back", ok and len(col(text)) == 6, text, quiet=True)

    ok, text = client.call("outline", operation="ungroup", range="2:3")
    step("ungroup the rows", ok, text, expect="Ungrouped rows 2:3")

    # Outline levels only mean something once groups sit inside one another.
    client.call("outline", operation="group", range="2:5")
    client.call("outline", operation="group", range="3:4")
    ok, text = client.call("outline", operation="show_level", level=1)
    step("show the least-detailed outline level", ok, text, expect="level 1")
    ok, text = client.call("read_range", range="A1:C6", visible_only=True)
    step("level 1 hides the nested detail",
         ok and col(text) == ["Region", "North", "South", "East"], text)
    client.call("outline", operation="show_level", level=3)
    ok, text = client.call("read_range", range="A1:C6", visible_only=True)
    step("a higher level reveals it again", ok and len(col(text)) == 6, text, quiet=True)
    client.call("outline", operation="clear")

    ok, text = client.call("outline", operation="group", range="B:C")
    step("grouping columns is inferred from the reference", ok, text,
         expect="Grouped columns B:C")
    ok, text = client.call("outline", operation="collapse", range="B:C")
    step("collapse the column group", ok, text, expect="Collapsed")
    ok, text = client.call("run_uno_script",
                           code="cols = sheet.Columns\n"
                                "result = [cols.getByIndex(i).IsVisible for i in range(3)]")
    step("the grouped columns are hidden", ok and "False, False]" in text, text)
    client.call("outline", operation="expand", range="B:C")

    ok, text = client.call("outline", operation="clear")
    step("clear every group", ok, text, expect="Removed every row and column group")

    client.call("write_range", range="E1", values=[
        ["Item", "Qty"], ["a", 1], ["b", 2], ["Subtotal", "=SUM(F2:F3)"],
        ["c", 4], ["d", 5], ["Subtotal", "=SUM(F5:F6)"],
    ])
    ok, text = client.call("outline", operation="auto", range="E1:F7")
    step("build an outline automatically from the formulas", ok, text,
         expect="Built an outline")
    client.call("outline", operation="clear")

    ok, text = client.call("outline", operation="show_level")
    step("show_level without a level is rejected", not ok, text, expect="'level' must be")

    # ---- advanced filter: criteria block ----------------------------------
    # (Region=North AND Amount>60) OR (Region=South)
    client.call("write_range", range="H1", values=[
        ["Region", "Amount"],
        ["North", ">60"],
        ["South", ""],
    ])
    ok, text = client.call("filter_range", range="A1:C6", criteria_range="H1:I3")
    step("advanced filter from a criteria block", ok, text, expect="3 of 5")
    ok, text = client.call("read_range", range="A1:C6", visible_only=True)
    step("criteria rows are ORed, columns ANDed",
         ok and col(text) == ["Region", "North", "South", "South"]
         and col(text, 1) == ["Rep", "Ann", "Cid", "Ann"], text)
    client.call("filter_range", range="A1:C6", operation="clear")

    ok, text = client.call("filter_range", range="A1:C6",
                           criteria_range="H1:I1")
    step("a criteria block with no conditions is rejected", not ok, text,
         expect="header row")

    ok, text = client.call("filter_range", range="A1:C6",
                           criteria_range="H1:I3",
                           conditions=[{"column": "Region", "operator": "equals",
                                        "value": "North"}])
    step("giving both conditions and a criteria range is rejected", not ok, text,
         expect="not both")

    # ---- advanced filter: copy results elsewhere --------------------------
    ok, text = client.call("filter_range", range="A1:C6", copy_to="A20",
                           conditions=[{"column": "Region", "operator": "equals",
                                        "value": "North"}])
    step("copy matching rows elsewhere", ok, text,
         expect=["Copied 2 matching row(s)", "source table is unchanged"])
    ok, text = client.call("read_range", range="A20:C22")
    step("the copy carries the header and the matches",
         ok and col(text) == ["Region", "North", "North"], text)
    ok, text = client.call("read_range", range="A1:C6", visible_only=True)
    step("the source table still shows every row", ok and len(col(text)) == 6,
         text, quiet=True)

    ok, text = client.call("filter_range", range="A1:A6", copy_to="E20",
                           unique_only=True,
                           conditions=[{"column": "Region", "operator": "not_empty"}])
    step("unique_only drops duplicate rows", ok, text, expect="Copied 3 matching")
    ok, text = client.call("read_range", range="E20:E23")
    step("each region appears once",
         ok and col(text) == ["Region", "North", "South", "East"], text)

    ok, text = client.call("filter_range", range="A1:C6", copy_to="A30",
                           conditions=[{"column": "Region", "operator": "equals",
                                        "value": "Nowhere"}])
    step("a copy that matches nothing says so", ok, text, expect="Nothing matched")

    client.close()
    print("\n" + "=" * 60)
    if FAILURES:
        print("FAILURES (%d): %s" % (len(FAILURES), FAILURES))
        return 1
    print("ALL OUTLINE AND ADVANCED-FILTER CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""End-to-end tests for filtering and for formula handling."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from smoke_calc import Client, FAILURES, step  # noqa: E402

TABLE = [
    ["Item", "Qty", "Region", "Price"],
    ["Widget", 10, "North", 2.5],
    ["Gadget", 3, "South", 19.99],
    ["Bolt", 22, "North", 1.1],
    ["Nut", 7, "East", 0.35],
    ["Cog", 15, "South", 4.0],
    ["Pin", 1, "", 0.05],
]


def visible_items(text):
    """Item names from a read_range grid, skipping title/header lines."""
    out = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) > 1 and parts[0].isdigit() and parts[1] not in ("Item", ""):
            out.append(parts[1])
    return out


def main():
    client = Client()
    client.call("open_document")
    client.call("manage_sheets", operation="rename", name="0", new_name="Stock")
    client.call("write_range", range="A1", values=TABLE)

    # ---- filtering ---------------------------------------------------------
    ok, text = client.call("filter_range", range="A1:D7",
                           conditions=[{"column": "Qty", "operator": "greater", "value": 5}])
    step("filter Qty > 5", ok, text, expect=["4 of 6 data rows", "2 hidden"])

    ok, text = client.call("read_range", range="A1:D7", visible_only=True)
    step("visible_only reads back only matching rows",
         ok and visible_items(text) == ["Widget", "Bolt", "Nut", "Cog"], text)

    ok, text = client.call("read_range", range="A1:D7")
    step("a normal read still sees every row",
         ok and len(visible_items(text)) == 6, text, quiet=True)

    ok, text = client.call("calc_status")
    step("calc_status flags the sheet as filtered", ok, text, expect="FILTERED")

    ok, text = client.call("filter_range", range="A1:D7", match="any", conditions=[
        {"column": "Region", "operator": "equals", "value": "North"},
        {"column": "Region", "operator": "equals", "value": "East"},
    ])
    step("filter Region = North OR East", ok, text, expect="3 of 6")
    ok, text = client.call("read_range", range="A1:D7", visible_only=True)
    step("OR filter kept the right rows",
         ok and visible_items(text) == ["Widget", "Bolt", "Nut"], text, quiet=True)

    ok, text = client.call("filter_range", range="A1:D7", conditions=[
        {"column": "Region", "operator": "equals", "value": "South"},
        {"column": "Price", "operator": "greater", "value": 10},
    ])
    step("two conditions combine with AND", ok, text, expect="1 of 6")

    ok, text = client.call("filter_range", range="A1:D7",
                           conditions=[{"column": "Item", "operator": "begins_with", "value": "B"}])
    step("text operator: begins_with", ok, text, expect="1 of 6")

    ok, text = client.call("filter_range", range="A1:D7",
                           conditions=[{"column": "Region", "operator": "empty"}])
    step("empty operator needs no value", ok, text, expect="1 of 6")
    ok, text = client.call("read_range", range="A1:D7", visible_only=True)
    step("the blank-region row is the one showing",
         ok and visible_items(text) == ["Pin"], text, quiet=True)

    ok, text = client.call("filter_range", range="A1:D7",
                           conditions=[{"column": "Qty", "operator": "top_values", "value": 2}])
    step("top_values keeps the two largest", ok, text, expect="2 of 6")
    ok, text = client.call("read_range", range="A1:D7", visible_only=True)
    step("top 2 by Qty are Bolt and Cog",
         ok and sorted(visible_items(text)) == ["Bolt", "Cog"], text, quiet=True)

    ok, text = client.call("filter_range", range="A1:D7",
                           conditions=[{"column": "Item", "operator": "equals", "value": "Nothing"}])
    step("a filter matching nothing says so", ok, text, expect="Nothing matched")

    ok, text = client.call("filter_range", range="A1:D7", operation="clear")
    step("clear the filter", ok, text, expect="every row is visible")
    ok, text = client.call("read_range", range="A1:D7", visible_only=True)
    step("all rows are back", ok and len(visible_items(text)) == 6, text, quiet=True)

    ok, text = client.call("filter_range", range="A1:D7", operation="show_dropdowns")
    step("turn on AutoFilter dropdowns", ok, text, expect="dropdowns are now on")
    ok, text = client.call("filter_range", range="A1:D7", operation="hide_dropdowns")
    step("turn AutoFilter dropdowns off", ok, text, expect="Removed the AutoFilter")

    ok, text = client.call("filter_range", range="A1:D7",
                           conditions=[{"column": "Nonexistent", "operator": "equals", "value": 1}])
    step("an unknown column is rejected clearly", not ok, text, expect="Cannot resolve")

    ok, text = client.call("filter_range", range="A1:D7",
                           conditions=[{"column": "Qty", "operator": "wobbles", "value": 1}])
    step("an unknown operator lists the valid ones", not ok, text, expect="Unknown operator")

    # ---- formulas ----------------------------------------------------------
    formulas = [
        ["Sum", "=SUM(B2:B7)"],
        ["Count over 5", "=COUNTIF(B2:B7,\">5\")"],
        ["North total", "=SUMIF(C2:C7,\"North\",B2:B7)"],
        ["Lookup Bolt", "=VLOOKUP(\"Bolt\",A2:D7,2,0)"],
        ["Nested IF", "=IF(B2>20,\"high\",IF(B2>5,\"mid\",\"low\"))"],
        ["Text join", "=CONCATENATE(A2,\" / \",C2)"],
        ["Rounded", "=ROUND(AVERAGE(D2:D7),2)"],
        ["Date", "=TEXT(DATE(2026,3,15),\"YYYY-MM-DD\")"],
        ["Visible only", "=SUBTOTAL(109,B2:B7)"],
    ]
    ok, text = client.call("write_range", range="F1", values=formulas)
    step("write nine multi-argument formulas with comma separators", ok, text,
         expect=["recalculated cleanly", "Rewrote ',' to ';'"])

    ok, text = client.call("read_range", range="F1:G9")
    step("every formula evaluated correctly",
         ok and all(v in text for v in ["58", "4", "32", "22", "mid", "Widget / North", "2026-03-15"]),
         text)

    ok, text = client.call("filter_range", range="A1:D7",
                           conditions=[{"column": "Region", "operator": "equals", "value": "North"}])
    step("filter while formulas are present", ok, text, expect="2 of 6")
    ok, text = client.call("read_range", range="F1:G9")
    step("SUBTOTAL(109) follows the filter while SUM does not",
         ok and "58" in text and "32" in text, text)

    client.call("filter_range", range="A1:D7", operation="clear")
    client.close()

    print("\n" + "=" * 60)
    if FAILURES:
        print("FAILURES (%d): %s" % (len(FAILURES), FAILURES))
        return 1
    print("ALL FILTER AND FORMULA CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

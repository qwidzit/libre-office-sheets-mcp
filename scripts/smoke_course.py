#!/usr/bin/env python3
"""End-to-end tests for the features a spreadsheet course covers."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from smoke_calc import Client, FAILURES, step  # noqa: E402


def cells(text):
    """Rows of a read_range grid as lists of strings, header row excluded."""
    out = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) > 1 and parts[0].isdigit():
            out.append(parts[1:])
    return out


def main():
    client = Client()
    client.call("open_document")
    client.call("manage_sheets", operation="rename", name="0", new_name="Sales")

    client.call("write_range", range="A1", values=[
        ["Item", "Qty", "Price", "Total"],
        ["Widget", 10, 2.5, "=B2*C2"],
        ["Gadget", 3, 19.99, None],
        ["Bolt", 22, 1.1, None],
        ["Nut", 7, 0.35, None],
    ])

    # ---- fill -------------------------------------------------------------
    ok, text = client.call("fill_cells", source="D2", through="D5")
    step("fill a formula down, adjusting references", ok, text,
         expect=["=B3*C3", "down"])
    ok, text = client.call("read_range", range="D2:D5")
    step("filled formulas computed correct values",
         ok and [r[0] for r in cells(text)] == ["25", "59.97", "24.2", "2.45"], text)

    ok, text = client.call("fill_cells", source="F1", through="F5", mode="linear", step=1)
    step("filling from an empty seed is handled, not a crash", ok or "CalcError" in text,
         text, quiet=True)
    client.call("write_range", range="F1", values=[[1]])
    ok, text = client.call("fill_cells", source="F1", through="F5", mode="linear", step=2)
    step("fill a numeric series", ok, text, quiet=True)
    ok, text = client.call("read_range", range="F1:F5")
    step("series stepped by 2",
         ok and [r[0] for r in cells(text)] == ["1", "3", "5", "7", "9"], text)

    client.call("write_range", range="G1", values=[["Jan"]])
    client.call("fill_cells", source="G1", through="G4")
    ok, text = client.call("read_range", range="G1:G4")
    step("fill a recognised series (months)",
         ok and [r[0] for r in cells(text)] == ["Jan", "Feb", "Mar", "Apr"], text)

    # ---- copy / paste special --------------------------------------------
    ok, text = client.call("copy_range", source="A1:D5", destination="A10", what="values")
    step("paste values only", ok, text, expect="values")
    ok, text = client.call("read_range", range="D11:D11", include_formulas=True)
    step("pasted values carry no formulas", ok and "FORMULAS: none" in text, text)

    ok, text = client.call("copy_range", source="A1:D5", destination="A20", what="all")
    step("paste everything", ok, text, quiet=True)
    ok, text = client.call("read_range", range="D21:D21", include_formulas=True)
    step("a full copy adjusts relative references", ok and "=B21*C21" in text, text)

    ok, text = client.call("copy_range", source="A1:B3", destination="I1", transpose=True)
    step("transposed paste", ok, text, expect="transposed")
    ok, text = client.call("read_range", range="I1:K2")
    step("transpose flipped rows and columns",
         ok and cells(text)[0] == ["Item", "Widget", "Gadget"], text)

    # ---- clean data -------------------------------------------------------
    client.call("write_range", range="A30", values=[
        ["Name", "Team"], ["Ann", "Red"], ["Bob", "Blue"],
        ["Ann", "Red"], ["Cid", "Green"], ["Bob", "Blue"],
    ])
    ok, text = client.call("clean_data", operation="remove_duplicates", range="A30:B35")
    step("remove duplicate rows", ok, text, expect=["Removed 2 duplicate"])
    ok, text = client.call("read_range", range="A30:B33")
    step("the unique rows survived in order",
         ok and [r[0] for r in cells(text)] == ["Name", "Ann", "Bob", "Cid"], text)

    client.call("write_range", range="A40", values=[["Smith, John"], ["Doe, Jane"]])
    ok, text = client.call("clean_data", operation="split_column", range="A40:A41",
                           separator=",")
    step("split a column on a separator", ok, text, expect="2 column(s)")
    ok, text = client.call("read_range", range="A40:B41")
    step("text to columns produced surname and first name",
         ok and cells(text)[0] == ["Smith", "John"], text)

    # ---- named ranges -----------------------------------------------------
    ok, text = client.call("manage_names", operation="add", name="Prices", range="C2:C5")
    step("create a named range", ok, text, expect="Prices")
    client.call("write_range", range="F10", values=[["=SUM(Prices)"]])
    ok, text = client.call("read_range", range="F10:F10")
    step("a formula can use the name", ok and "23.94" in text, text)
    ok, text = client.call("manage_names", operation="list")
    step("list named ranges", ok, text, expect="Prices")
    ok, text = client.call("manage_names", operation="delete", name="Prices")
    step("delete a named range", ok, text, expect="Deleted")

    # ---- conditional formatting ------------------------------------------
    ok, text = client.call("conditional_format", range="B2:B5", operator="greater",
                           value="9", background_color="#ffc7ce", text_color="#9c0006")
    step("conditional format from colours alone", ok, text, expect="1 rule")
    ok, text = client.call("conditional_format", range="C2:C5", operator="less",
                           value="1", style="Bad")
    step("conditional format with a built-in style", ok, text, expect="Bad")
    ok, text = client.call("conditional_format", range="C2:C5", style="NoSuchStyle",
                           operator="less", value="1")
    step("an unknown style lists the real ones", not ok, text, expect="Available")
    ok, text = client.call("conditional_format", range="B2:B5", operation="clear")
    step("clear conditional formatting", ok, text, expect="Cleared")

    # ---- data validation --------------------------------------------------
    ok, text = client.call("data_validation", range="E2:E5", type="list",
                           values=["Yes", "No", "Maybe"],
                           error_title="Invalid", error_message="Pick from the list")
    step("dropdown list validation", ok, text, expect=["Yes, No, Maybe", "dropdown"])
    ok, text = client.call("run_uno_script",
                           code="v = sheet.getCellRangeByName('E2:E5').Validation\n"
                                "result = '%s|%s' % (v.Type.value, v.getFormula1())")
    step("validation is really on the cells", ok, text, expect=["LIST", "Yes"])
    ok, text = client.call("data_validation", range="B2:B5", type="whole_number",
                           operator="between", min="1", max="100")
    step("whole-number range validation", ok, text, expect="between 1 and 100")
    ok, text = client.call("data_validation", range="B2:B5", operation="clear")
    step("clear validation", ok, text, expect="Removed validation")

    # ---- page setup -------------------------------------------------------
    ok, text = client.call("page_setup", print_area="A1:D5", orientation="landscape",
                           fit_to_pages_wide=1, repeat_rows="1", header_text="Q3 Sales",
                           margin_mm=15, print_gridlines=True)
    step("page setup accepts every option at once", ok, text,
         expect=["print area A1:D5", "landscape", "repeat row(s) 1", "margins 15mm"])
    ok, text = client.call("run_uno_script",
                           code="ps = doc.StyleFamilies.getByName('PageStyles').getByName(sheet.PageStyle)\n"
                                "result = '%s|%s|%s' % (ps.IsLandscape, ps.ScaleToPagesX, len(sheet.getPrintAreas()))")
    step("page settings really landed", ok, text, expect="True|1|1")

    # ---- comments ---------------------------------------------------------
    ok, text = client.call("manage_comments", operation="add", cell="A2",
                           text="Check this figure")
    step("add a cell comment", ok, text, expect="Added a comment")
    ok, text = client.call("manage_comments", operation="list")
    step("list comments", ok, text, expect=["A2", "Check this figure"])
    ok, text = client.call("manage_comments", operation="delete", cell="A2")
    step("delete a comment", ok, text, expect="Deleted")

    # ---- pivot ------------------------------------------------------------
    client.call("write_range", range="A50", values=[
        ["Region", "Rep", "Amount"],
        ["North", "Ann", 100], ["South", "Bob", 50],
        ["North", "Cid", 70], ["South", "Ann", 30],
    ])
    ok, text = client.call("create_pivot_table", range="A50:C54", destination="F50",
                           rows=["Region"], values=[{"field": "Amount", "function": "sum"}],
                           name="ByRegion")
    step("create a pivot table", ok, text, expect="ByRegion")
    ok, text = client.call("read_range", range="F50:G56")
    step("pivot totalled by region",
         ok and "170" in text and "80" in text, text)
    ok, text = client.call("create_pivot_table", operation="list")
    step("list pivot tables", ok, text, expect="ByRegion")
    ok, text = client.call("create_pivot_table", operation="delete", name="ByRegion")
    step("delete a pivot table", ok, text, expect="Deleted")

    # ---- styles and charts ------------------------------------------------
    ok, text = client.call("format_range", range="A1:D1", style="Heading 1", bold=True)
    step("apply a named cell style", ok, text, expect="style=Heading 1")

    ok, text = client.call("create_chart", range="A1:B5", chart_type="column",
                           title="Quantity", x_axis_title="Item", y_axis_title="Qty",
                           legend="bottom", data_labels=True, anchor="M1")
    step("chart with axis titles, legend and labels", ok, text, expect="column chart")

    # ---- protection -------------------------------------------------------
    ok, text = client.call("protect_sheet", operation="unlock_cells", range="B2:B5")
    step("unlock the input cells", ok, text, expect="stay editable")
    ok, text = client.call("protect_sheet", operation="protect")
    step("protect the sheet", ok, text, expect="Protected")
    ok, text = client.call("protect_sheet", operation="status")
    step("status reports protection", ok, text, expect="is protected")
    ok, text = client.call("write_range", range="A2", values=[["hacked"]])
    step("a locked cell rejects writes while protected", not ok, text, quiet=True)
    ok, text = client.call("write_range", range="B2", values=[[11]])
    step("an unlocked cell still accepts writes", ok, text, quiet=True)
    ok, text = client.call("protect_sheet", operation="unprotect")
    step("unprotect the sheet", ok, text, expect="Unprotected")
    ok, text = client.call("write_range", range="A2", values=[["Widget"]])
    step("writes work again after unprotecting", ok, text, quiet=True)

    client.close()
    print("\n" + "=" * 60)
    if FAILURES:
        print("FAILURES (%d): %s" % (len(FAILURES), FAILURES))
        return 1
    print("ALL COURSE-FEATURE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

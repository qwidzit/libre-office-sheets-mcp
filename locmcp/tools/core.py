"""Status, document lifecycle, and the read/write workhorses."""

import os

from .. import convert
from ..bridge import (
    CalcError, calc_documents, cell_range, doc_label, doc_path, null_date, prop,
    set_active_document, to_file_url, undo_step, uno_get, visible_rows,
    with_reconnect,
)
from ..registry import DOCUMENT, SHEET, array, boolean, enum, integer, string, tool
from .base import bool_arg, check_size, describe_used, doc_only, int_arg, target

RANGE = string(
    "A1-style range: 'B2', 'A1:D20', 'Sheet2.A1:C9', 'A:C' for whole columns, or a "
    "named range. Omit to use the sheet's whole used area."
)

SAVE_FILTERS = {
    "ods": "calc8",
    "xlsx": "Calc MS Excel 2007 XML",
    "xls": "MS Excel 97",
    "csv": "Text - txt - csv (StarCalc)",
    "pdf": "calc_pdf_Export",
    "html": "HTML (StarCalc)",
}


# --- status ------------------------------------------------------------------

@tool(
    "calc_status",
    "Show the LibreOffice connection, every open spreadsheet, and each sheet with "
    "its used range. Call this first -- it tells you what you can address.",
    properties={},
    title="Calc status",
    read_only=True,
)
def calc_status(args):
    def run(conn):
        lines = []
        try:
            info = conn.create("com.sun.star.configuration.ConfigurationProvider")
            del info
        except Exception:
            pass
        docs = calc_documents(conn)
        if not docs:
            return "Connected to LibreOffice, but no spreadsheet is open.\nUse open_document to open a file or create a new one."

        try:
            current = conn.desktop.getCurrentComponent()
        except Exception:
            current = None

        lines.append("Connected to LibreOffice. %d spreadsheet(s) open." % len(docs))
        for index, doc in enumerate(docs):
            marker = " <- active" if doc == current else ""
            path = doc_path(doc)
            modified = " [unsaved changes]" if doc.isModified() else ""
            lines.append("")
            lines.append("[%d] %s%s%s" % (index, doc_label(doc), modified, marker))
            if path:
                lines.append("    path: %s" % path)
            else:
                lines.append("    path: (never saved)")
            try:
                active_sheet = doc.CurrentController.getActiveSheet().Name
            except Exception:
                active_sheet = None
            for name in doc.Sheets.ElementNames:
                sheet = doc.Sheets.getByName(name)
                flag = " *" if name == active_sheet else "  "
                lines.append("   %s %s: %s" % (flag, name, describe_used(sheet)))
            try:
                named = list(doc.NamedRanges.ElementNames)
                if named:
                    lines.append("    named ranges: %s" % ", ".join(named))
            except Exception:
                pass
        lines.append("")
        lines.append("(* = active sheet)")
        return "\n".join(lines)

    return with_reconnect(run)


# --- document lifecycle ------------------------------------------------------

@tool(
    "open_document",
    "Open a spreadsheet file in LibreOffice, or create a new empty one. The window "
    "becomes visible so the user can watch subsequent edits.",
    properties={
        "path": string(
            "Absolute path of the file to open. Omit to create a new empty spreadsheet."
        ),
        "read_only": boolean("Open without allowing edits. Default false."),
    },
    title="Open document",
)
def open_document(args):
    path = args.get("path")

    def run(conn):
        if path:
            expanded = os.path.abspath(os.path.expanduser(str(path)))
            if not os.path.exists(expanded):
                raise CalcError("No such file: %s" % expanded)
            url = to_file_url(expanded)
            options = [prop("ReadOnly", bool_arg(args, "read_only"))]
        else:
            url = "private:factory/scalc"
            options = []
        doc = conn.desktop.loadComponentFromURL(url, "_blank", 0, tuple(options))
        if doc is None:
            raise CalcError("LibreOffice did not return a document for %s" % url)
        if not doc.supportsService("com.sun.star.sheet.SpreadsheetDocument"):
            doc.close(False)
            raise CalcError("%s is not a spreadsheet." % path)
        set_active_document(doc)
        sheets = ", ".join(doc.Sheets.ElementNames)
        return "Opened '%s'.\nSheets: %s\nUsed range of first sheet: %s" % (
            doc_label(doc), sheets, describe_used(doc.Sheets.getByIndex(0)),
        )

    return with_reconnect(run)


@tool(
    "save_document",
    "Save the document. With no path it saves in place; with a path it saves a copy "
    "(and can convert to xlsx, csv, pdf and so on). Edits are live in the window but "
    "only persist to disk once this is called.",
    properties={
        "document": DOCUMENT,
        "path": string("Absolute path to save to. Omit to save in place."),
        "format": enum(
            "Output format. Inferred from the path extension when omitted.",
            sorted(SAVE_FILTERS),
        ),
    },
    title="Save document",
)
def save_document(args):
    conn, doc = doc_only(args)
    path = args.get("path")
    fmt = args.get("format")

    if not path:
        if not uno_get(doc, "URL", ""):
            raise CalcError(
                "This document has never been saved, so it has no path. Call "
                "save_document again with an explicit 'path'."
            )
        doc.store()
        return "Saved %s in place (%s)." % (doc_label(doc), doc_path(doc))

    expanded = os.path.abspath(os.path.expanduser(str(path)))
    if not fmt:
        fmt = os.path.splitext(expanded)[1].lstrip(".").lower()
    if fmt not in SAVE_FILTERS:
        raise CalcError(
            "Unsupported format %r. Choose one of: %s"
            % (fmt, ", ".join(sorted(SAVE_FILTERS)))
        )
    parent = os.path.dirname(expanded)
    if parent and not os.path.isdir(parent):
        raise CalcError("Directory does not exist: %s" % parent)

    options = [prop("FilterName", SAVE_FILTERS[fmt]), prop("Overwrite", True)]
    try:
        doc.storeToURL(to_file_url(expanded), tuple(options))
    except Exception as exc:
        if "IOException" in type(exc).__name__:
            raise CalcError(
                "LibreOffice could not write %s. It is usually already open in "
                "another window, locked by a .~lock file, or on a read-only path. "
                "(%s)" % (expanded, exc)
            )
        raise
    return "Saved a copy of %s to %s (%s)." % (doc_label(doc), expanded, fmt)


# --- reading -----------------------------------------------------------------

def _date_columns(doc, sheet, spec, data):
    """Columns whose first numeric cell carries a date/time number format.

    Driven off the already-fetched data array rather than each cell's content
    type: a date produced by a formula has type FORMULA, not VALUE, and testing
    the type would skip exactly the cells most worth converting.
    """
    try:
        formats = doc.getNumberFormats()
    except Exception:
        return set()
    found = set()
    sample_rows = min(spec.rows, 20)
    for i in range(spec.cols):
        for j in range(sample_rows):
            if not isinstance(data[j][i], float):
                continue
            cell = sheet.getCellByPosition(spec.start_col + i, spec.start_row + j)
            try:
                kind = formats.getByKey(cell.NumberFormat).Type
            except Exception:
                break
            if kind & 2:  # com.sun.star.util.NumberFormat.DATE
                found.add(i)
            break
    return found


@tool(
    "read_range",
    "Read cell values from a range as a tab-separated grid with real row numbers and "
    "column letters. Date-formatted columns are returned as dates, not serial numbers.",
    properties={
        "document": DOCUMENT,
        "sheet": SHEET,
        "range": RANGE,
        "include_formulas": boolean(
            "Also list the formula behind every formula cell. Default false."
        ),
        "format": enum("Output layout. Default tsv.", ["tsv", "markdown", "json"]),
        "visible_only": boolean(
            "Skip rows hidden by a filter, so you read back exactly what the user "
            "sees. Default false."
        ),
        "max_rows": integer("Stop after this many rows. Default 500."),
    },
    title="Read range",
    read_only=True,
)
def read_range(args):
    conn, doc, sheet, spec = target(args)
    max_rows = int_arg(args, "max_rows", 500) or 500
    truncated = False
    if spec.rows > max_rows:
        spec = convert.RangeSpec(
            spec.start_col, spec.start_row, spec.end_col, spec.start_row + max_rows - 1
        )
        truncated = True
    check_size(spec)

    rng = cell_range(sheet, spec)
    data = rng.getDataArray()
    date_cols = _date_columns(doc, sheet, spec, data)
    nd = null_date(doc)

    grid = []
    for row in data:
        out = []
        for i, value in enumerate(row):
            if i in date_cols and isinstance(value, float) and value:
                try:
                    value = convert.serial_to_datetime(value, nd)
                except Exception:
                    pass
            out.append(value)
        grid.append(out)

    row_numbers = None
    hidden = 0
    if bool_arg(args, "visible_only"):
        shown = visible_rows(rng)
        if shown is not None:
            kept = [r for r in range(spec.rows) if (spec.start_row + r) in shown]
            hidden = spec.rows - len(kept)
            grid = [grid[r] for r in kept]
            row_numbers = [spec.start_row + r for r in kept]

    layout = (args.get("format") or "tsv").lower()
    if layout == "json":
        import json
        body = json.dumps(
            {
                "sheet": sheet.Name,
                "range": spec.name(),
                "rows": len(grid),
                "cols": spec.cols,
                "row_numbers": [n + 1 for n in row_numbers] if row_numbers else None,
                "values": [[convert.cell_text(v) for v in row] for row in grid],
            },
            ensure_ascii=False,
            indent=1,
        )
    elif layout == "markdown":
        body = convert.to_markdown(grid, spec, sheet.Name, row_numbers)
    else:
        body = convert.to_tsv(grid, spec, sheet.Name, row_numbers)

    if hidden:
        body += "\n\n(%d row(s) hidden by a filter were skipped.)" % hidden

    if bool_arg(args, "include_formulas"):
        formulas = rng.getFormulaArray()
        listed = []
        for r, row in enumerate(formulas):
            for c, value in enumerate(row):
                if isinstance(value, str) and value.startswith("="):
                    listed.append(
                        "%s\t%s"
                        % (convert.cell_name(spec.start_col + c, spec.start_row + r), value)
                    )
        if listed:
            body += "\n\nFORMULAS (%d):\n" % len(listed) + "\n".join(listed[:300])
            if len(listed) > 300:
                body += "\n... %d more" % (len(listed) - 300)
        else:
            body += "\n\nFORMULAS: none in this range."

    if truncated:
        body += "\n\n(Truncated to %d rows; raise max_rows or read further down.)" % max_rows
    return body


# --- writing -----------------------------------------------------------------

def _normalise_grid(values, spec):
    """Accept a 2D array, or a flat list shaped by the target range."""
    if not isinstance(values, list) or not values:
        raise CalcError("'values' must be a non-empty array of rows.")
    if all(isinstance(row, list) for row in values):
        return values
    if any(isinstance(row, list) for row in values):
        raise CalcError("'values' mixes rows and scalars; make every element an array.")
    # Flat list: let an explicit single-column range mean a column.
    if spec is not None and spec.cols == 1 and spec.rows == len(values):
        return [[v] for v in values]
    return [values]


def _as_data_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return str(value)


@tool(
    "write_range",
    "Write values and/or formulas into a range. Any string starting with '=' is "
    "entered as a formula, and either ',' or ';' works as the argument separator. "
    "Give the top-left cell alone (e.g. 'B2') and the block is sized from the data. "
    "The whole block is a single Ctrl+Z for the user.",
    properties={
        "document": DOCUMENT,
        "sheet": SHEET,
        "range": string(
            "Target: either the top-left anchor cell ('B2') or the exact range "
            "('B2:D10'). A full range must match the shape of 'values'."
        ),
        "values": array(
            "Rows of cell values, e.g. [[\"Item\",\"Qty\"],[\"Nut\",12]]. Strings "
            "beginning with '=' become formulas; null leaves the cell empty.",
            {"type": "array", "items": {}},
        ),
        "raw_text": boolean(
            "Write everything as literal text, so '=SUM(A1)' or '007' is not "
            "interpreted. Default false."
        ),
    },
    required=["range", "values"],
    title="Write range",
)
def write_range(args):
    conn, doc, sheet, anchor = target(args, require_range=True)
    grid = _normalise_grid(args.get("values"), anchor)
    width = max(len(row) for row in grid)
    height = len(grid)
    grid = [list(row) + [None] * (width - len(row)) for row in grid]

    if anchor.rows == 1 and anchor.cols == 1 and (height > 1 or width > 1):
        spec = convert.RangeSpec(
            anchor.start_col, anchor.start_row,
            anchor.start_col + width - 1, anchor.start_row + height - 1,
        )
    else:
        spec = anchor
        if spec.rows != height or spec.cols != width:
            raise CalcError(
                "Range %s is %d rows x %d cols but 'values' is %d x %d. Pass the "
                "top-left cell alone to size it automatically."
                % (spec.name(), spec.rows, spec.cols, height, width)
            )
    check_size(spec)

    raw = bool_arg(args, "raw_text")
    has_formula = not raw and any(
        isinstance(v, str) and v.startswith("=") for row in grid for v in row
    )

    converted = []

    def formula_entry(value):
        if value is None:
            return ""
        if not isinstance(value, str):
            return convert.cell_text(value)
        if not value.startswith("="):
            return value
        fixed = convert.normalise_formula(value)
        if fixed != value:
            converted.append(value)
        return fixed

    rng = cell_range(sheet, spec)
    with undo_step(doc, "Claude: write %s.%s" % (sheet.Name, spec.name())):
        if raw:
            payload = tuple(tuple("" if v is None else str(v) for v in row) for row in grid)
            rng.setDataArray(payload)
        elif has_formula:
            # setFormulaArray parses each entry like typed input, which is what we
            # want once formulas are in play.
            payload = tuple(tuple(formula_entry(v) for v in row) for row in grid)
            rng.setFormulaArray(payload)
        else:
            payload = tuple(tuple(_as_data_value(v) for v in row) for row in grid)
            rng.setDataArray(payload)

    summary = "Wrote %d rows x %d cols to %s.%s." % (
        spec.rows, spec.cols, sheet.Name, spec.name()
    )

    if converted:
        summary += (
            " Rewrote ',' to ';' as the argument separator in %d formula(s), which "
            "is what Calc's API grammar expects." % len(converted)
        )

    if has_formula:
        doc.calculateAll()
        problems = []
        for r, row in enumerate(grid):
            for c, value in enumerate(row):
                if not (isinstance(value, str) and value.startswith("=")):
                    continue
                if len(problems) >= 20:
                    break
                cell = sheet.getCellByPosition(spec.start_col + c, spec.start_row + r)
                code = cell.getError()
                if code:
                    problems.append(
                        "%s -> %s"
                        % (convert.cell_name(spec.start_col + c, spec.start_row + r),
                           convert.error_name(code))
                    )
        if problems:
            summary += "\n\nFormula errors:\n" + "\n".join(problems)
        else:
            summary += " Formulas recalculated cleanly."
    return summary


@tool(
    "clear_range",
    "Clear cells: contents only, formatting only, or everything.",
    properties={
        "document": DOCUMENT,
        "sheet": SHEET,
        "range": RANGE,
        "what": enum(
            "What to remove. Default contents.",
            ["contents", "formats", "all"],
        ),
    },
    required=["range"],
    title="Clear range",
)
def clear_range(args):
    conn, doc, sheet, spec = target(args, require_range=True)
    what = (args.get("what") or "contents").lower()
    # com.sun.star.sheet.CellFlags
    VALUE, DATETIME, STRING, ANNOTATION, FORMULA = 1, 2, 4, 8, 16
    HARDATTR, STYLES, OBJECTS, EDITATTR, FORMATTED = 32, 64, 128, 256, 512
    contents = VALUE | DATETIME | STRING | ANNOTATION | FORMULA
    formats = HARDATTR | STYLES | EDITATTR | FORMATTED
    flags = {
        "contents": contents,
        "formats": formats,
        "all": contents | formats | OBJECTS,
    }[what]

    with undo_step(doc, "Claude: clear %s.%s" % (sheet.Name, spec.name())):
        cell_range(sheet, spec).clearContents(flags)
    return "Cleared %s from %s.%s (%d cells)." % (what, sheet.Name, spec.name(), spec.cells)


@tool(
    "recalculate",
    "Force a recalculation of the document's formulas.",
    properties={"document": DOCUMENT, "hard": boolean("Recalculate every formula, "
                "including cached ones. Default false.")},
    title="Recalculate",
)
def recalculate(args):
    conn, doc = doc_only(args)
    if bool_arg(args, "hard"):
        doc.calculateAll()
        return "Recalculated all formulas in %s." % doc_label(doc)
    doc.calculate()
    return "Recalculated %s." % doc_label(doc)

"""Filling, copying, cleaning and summarising data.

These are the operations a spreadsheet course spends most of its time on:
dragging a formula down a column, pasting values only, splitting a name field,
and building a pivot table.
"""

from .. import convert
from ..bridge import (
    CalcError, cell_range, make_struct, undo_step, uno_module, used_range,
)
from ..registry import DOCUMENT, SHEET, array, boolean, enum, number, string, tool
from .base import bool_arg, check_size, doc_and_sheet, target

FILL_DIRECTIONS = {
    "down": "TO_BOTTOM",
    "up": "TO_TOP",
    "right": "TO_RIGHT",
    "left": "TO_LEFT",
}
DATE_UNITS = {
    "day": "FILL_DATE_DAY",
    "weekday": "FILL_DATE_WEEKDAY",
    "month": "FILL_DATE_MONTH",
    "year": "FILL_DATE_YEAR",
}
NO_LIMIT = 1e300  # fillSeries wants an end value; this stands in for "no limit"


def _enum(type_name, value):
    return uno_module().Enum(type_name, value)


def _address(sheet, spec):
    return make_struct(
        "com.sun.star.table.CellRangeAddress",
        Sheet=sheet.RangeAddress.Sheet,
        StartColumn=spec.start_col,
        StartRow=spec.start_row,
        EndColumn=spec.end_col,
        EndRow=spec.end_row,
    )


def _cell_address(sheet, col, row):
    return make_struct(
        "com.sun.star.table.CellAddress",
        Sheet=sheet.RangeAddress.Sheet, Column=col, Row=row,
    )


@tool(
    "fill_cells",
    "Fill a formula, value or series from a seed cell across a range -- the "
    "equivalent of dragging the fill handle. Relative references shift as they "
    "would in Calc, so =A1*B1 becomes =A2*B2 on the next row. Also fills series "
    "like 1,2,3 or Jan,Feb,Mar.",
    properties={
        "document": DOCUMENT,
        "sheet": SHEET,
        "source": string(
            "The seed cell or cells already holding the value or formula, e.g. 'D2' "
            "or 'B1:D1'."
        ),
        "through": string(
            "The cell to fill as far as, e.g. 'D50'. Must extend the source in one "
            "direction."
        ),
        "mode": enum(
            "How to extend. 'auto' copies formulas (adjusting references) and "
            "continues recognised series like months. The others build a number or "
            "date series from 'step'. Default auto.",
            ["auto", "linear", "growth", "date"],
        ),
        "step": number("Increment for linear, growth and date modes. Default 1."),
        "stop": number("Stop once the series passes this value. Optional."),
        "date_unit": enum(
            "Which part of the date to step in date mode. Default day.",
            sorted(DATE_UNITS),
        ),
    },
    required=["source", "through"],
    title="Fill cells",
)
def fill_cells(args):
    # This tool calls its range 'source', so hand target() the name it expects.
    conn, doc, sheet, source = target(dict(args, range=args["source"]), require_range=True)
    through = convert.parse_range(
        convert.split_sheet(str(args["through"]))[1], used_range(sheet)
    )

    combined = convert.RangeSpec(
        min(source.start_col, through.start_col),
        min(source.start_row, through.start_row),
        max(source.end_col, through.end_col),
        max(source.end_row, through.end_row),
    )
    check_size(combined)

    if combined.end_row > source.end_row:
        direction, count = "down", source.rows
    elif combined.start_row < source.start_row:
        direction, count = "up", source.rows
    elif combined.end_col > source.end_col:
        direction, count = "right", source.cols
    elif combined.start_col < source.start_col:
        direction, count = "left", source.cols
    else:
        raise CalcError(
            "'through' (%s) does not extend the source (%s), so there is nothing to "
            "fill." % (through.name(), source.name())
        )

    rng = cell_range(sheet, combined)
    mode = (args.get("mode") or "auto").lower()
    step = float(args.get("step") if args.get("step") is not None else 1)
    stop = float(args["stop"]) if args.get("stop") is not None else NO_LIMIT

    with undo_step(doc, "Claude: fill %s.%s" % (sheet.Name, combined.name())):
        if mode == "auto":
            rng.fillAuto(_enum("com.sun.star.sheet.FillDirection", FILL_DIRECTIONS[direction]), count)
        else:
            fill_mode = {"linear": "LINEAR", "growth": "GROWTH", "date": "DATE"}[mode]
            unit = DATE_UNITS[(args.get("date_unit") or "day").lower()]
            rng.fillSeries(
                _enum("com.sun.star.sheet.FillDirection", FILL_DIRECTIONS[direction]),
                _enum("com.sun.star.sheet.FillMode", fill_mode),
                _enum("com.sun.star.sheet.FillDateMode", unit),
                step,
                stop,
            )

    filled = convert.RangeSpec(
        combined.start_col, combined.start_row, combined.end_col, combined.end_row
    )
    preview = rng.getFormulaArray()
    sample = []
    for r, row in enumerate(preview[:4]):
        sample.append(
            "%s\t%s"
            % (convert.cell_name(combined.start_col, combined.start_row + r),
               convert.cell_text(row[0]))
        )
    return "Filled %s.%s %s from %s (%s mode).\nFirst cells:\n%s" % (
        sheet.Name, filled.name(), direction, source.name(), mode, "\n".join(sample),
    )


@tool(
    "copy_range",
    "Copy cells elsewhere. 'all' behaves like a normal copy and paste, adjusting "
    "relative references and bringing formatting; 'values' pastes results only, "
    "dropping formulas; 'formats' paints the formatting across without touching "
    "the contents.",
    properties={
        "document": DOCUMENT,
        "sheet": SHEET,
        "source": string("Range to copy, e.g. 'A1:D10'."),
        "destination": string(
            "Top-left cell to paste at, e.g. 'F1' or 'Summary.A1'. May be on "
            "another sheet."
        ),
        "what": enum("What to paste. Default all.", ["all", "values", "formats"]),
        "transpose": boolean(
            "Flip rows and columns. Values only, since transposed formulas would "
            "point at the wrong cells. Default false."
        ),
    },
    required=["source", "destination"],
    title="Copy range",
)
def copy_range(args):
    conn, doc, sheet, source = target(dict(args, range=args["source"]), require_range=True)
    dest_sheet_name, dest_ref = convert.split_sheet(str(args["destination"]))
    if dest_sheet_name:
        from ..bridge import resolve_sheet
        dest_sheet = resolve_sheet(doc, dest_sheet_name)
    else:
        dest_sheet = sheet
    dest_anchor = convert.parse_range(dest_ref, used_range(dest_sheet))

    what = (args.get("what") or "all").lower()
    transpose = bool_arg(args, "transpose")
    if transpose and what != "values":
        what = "values"

    rows, cols = (source.cols, source.rows) if transpose else (source.rows, source.cols)
    dest = convert.RangeSpec(
        dest_anchor.start_col, dest_anchor.start_row,
        dest_anchor.start_col + cols - 1, dest_anchor.start_row + rows - 1,
    )
    check_size(dest)

    src_range = cell_range(sheet, source)
    dst_range = cell_range(dest_sheet, dest)

    with undo_step(doc, "Claude: copy %s.%s" % (sheet.Name, source.name())):
        if what == "values":
            data = src_range.getDataArray()
            if transpose:
                data = tuple(zip(*data))
            dst_range.setDataArray(tuple(tuple(row) for row in data))
        elif what == "formats":
            # There is no formats-only paste in the API, so copy everything and
            # then put the destination's own contents back.
            keep = dst_range.getFormulaArray()
            dest_sheet.copyRange(
                _cell_address(dest_sheet, dest.start_col, dest.start_row),
                _address(sheet, source),
            )
            cell_range(dest_sheet, dest).setFormulaArray(keep)
        else:
            dest_sheet.copyRange(
                _cell_address(dest_sheet, dest.start_col, dest.start_row),
                _address(sheet, source),
            )

    note = " (transposed)" if transpose else ""
    return "Copied %s (%s) from %s.%s to %s.%s%s." % (
        what, "%d x %d" % (rows, cols), sheet.Name, source.name(),
        dest_sheet.Name, dest.name(), note,
    )


@tool(
    "clean_data",
    "Tidy a table: delete duplicate rows, or split one column into several on a "
    "separator (the 'text to columns' exercise, e.g. 'Smith, John' into two "
    "columns).",
    properties={
        "document": DOCUMENT,
        "sheet": SHEET,
        "operation": enum("What to do.", ["remove_duplicates", "split_column"]),
        "range": string(
            "For remove_duplicates, the table including its header. For "
            "split_column, the single column to split, e.g. 'A2:A40'."
        ),
        "has_header": boolean("Treat the first row as headers. Default true."),
        "columns": array(
            "For remove_duplicates: which columns decide whether two rows match "
            "(header names or column letters). Defaults to every column.",
            {"type": "string"},
        ),
        "separator": string(
            "For split_column: the text to split on, e.g. ',' or ' ' or ' - '."
        ),
        "destination": string(
            "For split_column: top-left cell for the results. Defaults to the "
            "source column, overwriting it and the columns to its right."
        ),
        "trim": boolean("For split_column: strip surrounding spaces. Default true."),
    },
    required=["operation", "range"],
    title="Clean data",
)
def clean_data(args):
    conn, doc, sheet, spec = target(args, require_range=True)
    operation = args["operation"]

    if operation == "remove_duplicates":
        return _remove_duplicates(doc, sheet, spec, args)
    if operation == "split_column":
        return _split_column(doc, sheet, spec, args)
    raise CalcError("Unknown operation %r." % operation)


def _remove_duplicates(doc, sheet, spec, args):
    from .edit import column_offset, header_map

    has_header = bool_arg(args, "has_header", True)
    data = cell_range(sheet, spec).getDataArray()
    headers = header_map(sheet, spec, has_header)

    wanted = args.get("columns") or []
    if wanted:
        offsets = [column_offset(c, headers, spec, "duplicate") for c in wanted]
    else:
        offsets = list(range(spec.cols))

    seen = set()
    doomed = []
    start = 1 if has_header else 0
    for index in range(start, len(data)):
        key = tuple(convert.cell_text(data[index][o]) for o in offsets)
        if key in seen:
            doomed.append(spec.start_row + index)
        else:
            seen.add(key)

    if not doomed:
        return "No duplicate rows in %s.%s; nothing removed." % (sheet.Name, spec.name())

    # Remove from the bottom up so earlier indices stay valid.
    with undo_step(doc, "Claude: remove duplicates %s.%s" % (sheet.Name, spec.name())):
        for row in sorted(doomed, reverse=True):
            sheet.Rows.removeByIndex(row, 1)

    by = ", ".join(convert.index_to_col(spec.start_col + o) for o in offsets)
    return (
        "Removed %d duplicate row(s) from %s.%s, matching on column(s) %s. %d unique "
        "row(s) remain. Whole rows were deleted, so anything alongside the table on "
        "those rows went too."
        % (len(doomed), sheet.Name, spec.name(), by, len(seen))
    )


def _split_column(doc, sheet, spec, args):
    separator = args.get("separator")
    if not separator:
        raise CalcError("'separator' is required to split a column.")
    if spec.cols != 1:
        raise CalcError(
            "split_column works on a single column; %s spans %d."
            % (spec.name(), spec.cols)
        )
    trim = bool_arg(args, "trim", True)

    data = cell_range(sheet, spec).getDataArray()
    parts = []
    width = 1
    for row in data:
        text = convert.cell_text(row[0])
        pieces = text.split(separator) if text else [""]
        if trim:
            pieces = [p.strip() for p in pieces]
        width = max(width, len(pieces))
        parts.append(pieces)
    grid = [p + [""] * (width - len(p)) for p in parts]

    if args.get("destination"):
        dest_anchor = convert.parse_range(
            convert.split_sheet(str(args["destination"]))[1], used_range(sheet))
        start_col, start_row = dest_anchor.start_col, dest_anchor.start_row
    else:
        start_col, start_row = spec.start_col, spec.start_row

    dest = convert.RangeSpec(
        start_col, start_row, start_col + width - 1, start_row + len(grid) - 1)
    check_size(dest)

    with undo_step(doc, "Claude: split %s.%s" % (sheet.Name, spec.name())):
        cell_range(sheet, dest).setDataArray(tuple(tuple(row) for row in grid))

    return "Split %s.%s on %r into %d column(s) at %s." % (
        sheet.Name, spec.name(), separator, width, dest.name()
    )


PIVOT_FUNCTIONS = {
    "sum": "SUM", "count": "COUNT", "average": "AVERAGE", "max": "MAX",
    "min": "MIN", "product": "PRODUCT", "count_numbers": "COUNTNUMS",
    "stdev": "STDEV", "var": "VAR",
}


@tool(
    "create_pivot_table",
    "Build a pivot table summarising a range -- group by one or more fields and "
    "aggregate another. Also lists and deletes existing pivot tables.",
    properties={
        "document": DOCUMENT,
        "sheet": SHEET,
        "operation": enum("What to do. Default create.", ["create", "delete", "list"]),
        "range": string("Source data including its header row, e.g. 'A1:D100'."),
        "destination": string("Top-left cell for the result. Default 'H1'."),
        "rows": array("Header names to group down the side.", {"type": "string"}),
        "columns": array("Header names to group across the top.", {"type": "string"}),
        "values": array(
            "Fields to aggregate, each a header name and a function.",
            {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "function": {"type": "string", "enum": sorted(PIVOT_FUNCTIONS)},
                },
                "required": ["field"],
                "additionalProperties": False,
            },
        ),
        "name": string("Pivot table name. Defaults to 'Pivot N'."),
    },
    title="Create pivot table",
)
def create_pivot_table(args):
    operation = (args.get("operation") or "create").lower()
    if operation == "list":
        conn, doc, sheet = doc_and_sheet(args)
        tables = sheet.DataPilotTables
        names = list(tables.ElementNames)
        if not names:
            return "No pivot tables on sheet '%s'." % sheet.Name
        return "Pivot tables on '%s': %s" % (sheet.Name, ", ".join(names))

    if operation == "delete":
        conn, doc, sheet = doc_and_sheet(args)
        name = args.get("name")
        if not name:
            raise CalcError("'name' is required to delete a pivot table.")
        tables = sheet.DataPilotTables
        if not tables.hasByName(name):
            raise CalcError(
                "No pivot table named %r on sheet '%s'. Present: %s"
                % (name, sheet.Name, ", ".join(tables.ElementNames) or "none")
            )
        with undo_step(doc, "Claude: delete pivot %s" % name):
            tables.removeByName(name)
        return "Deleted pivot table '%s'." % name

    conn, doc, sheet, spec = target(args, require_range=True)
    values = args.get("values") or []
    if not values:
        raise CalcError("'values' needs at least one field to aggregate.")

    tables = sheet.DataPilotTables
    name = args.get("name") or "Pivot %d" % (tables.Count + 1)
    if tables.hasByName(name):
        raise CalcError("A pivot table named %r already exists on this sheet." % name)

    descriptor = tables.createDataPilotDescriptor()
    descriptor.setSourceRange(_address(sheet, spec))
    fields = descriptor.getDataPilotFields()
    available = {}
    for index in range(fields.Count):
        field = fields.getByIndex(index)
        available[field.Name.strip().lower()] = field

    def pick(label):
        found = available.get(str(label).strip().lower())
        if found is None:
            raise CalcError(
                "No field named %r in the source range. Fields: %s"
                % (label, ", ".join(sorted(f.Name for f in
                                           (fields.getByIndex(i) for i in range(fields.Count)))))
            )
        return found

    described = []
    for label in args.get("rows") or []:
        pick(label).Orientation = _enum(
            "com.sun.star.sheet.DataPilotFieldOrientation", "ROW")
        described.append("rows: %s" % label)
    for label in args.get("columns") or []:
        pick(label).Orientation = _enum(
            "com.sun.star.sheet.DataPilotFieldOrientation", "COLUMN")
        described.append("columns: %s" % label)
    for entry in values:
        field = pick(entry.get("field"))
        function = str(entry.get("function") or "sum").lower()
        if function not in PIVOT_FUNCTIONS:
            raise CalcError(
                "Unknown function %r. Choose from: %s"
                % (function, ", ".join(sorted(PIVOT_FUNCTIONS)))
            )
        field.Orientation = _enum(
            "com.sun.star.sheet.DataPilotFieldOrientation", "DATA")
        field.Function = _enum(
            "com.sun.star.sheet.GeneralFunction", PIVOT_FUNCTIONS[function])
        described.append("%s of %s" % (function, entry.get("field")))

    anchor = convert.parse_range(
        convert.split_sheet(str(args.get("destination") or "H1"))[1], used_range(sheet))

    with undo_step(doc, "Claude: create pivot %s" % name):
        tables.insertNewByName(
            name, _cell_address(sheet, anchor.start_col, anchor.start_row), descriptor)

    output = tables.getByName(name).getOutputRange()
    result = convert.RangeSpec(
        output.StartColumn, output.StartRow, output.EndColumn, output.EndRow)
    return "Created pivot table '%s' at %s.%s from %s (%s)." % (
        name, sheet.Name, result.name(), spec.name(), "; ".join(described)
    )

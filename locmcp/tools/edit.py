"""Structural edits: rows and columns, sheets, sorting, filtering, search."""

import re

from .. import convert
from ..bridge import (
    CalcError, cell_range, make_struct, resolve_range, resolve_sheet, typed_any,
    undo_step, uno_module, used_range, visible_rows,
)
from ..registry import DOCUMENT, SHEET, array, boolean, enum, integer, string, tool
from .base import bool_arg, describe_used, doc_and_sheet, doc_only, int_arg, target


def header_map(sheet, spec, has_header):
    """Lower-cased header text -> column offset within the range."""
    if not has_header:
        return {}
    header_row = cell_range(
        sheet,
        convert.RangeSpec(spec.start_col, spec.start_row, spec.end_col, spec.start_row),
    ).getDataArray()[0]
    headers = {}
    for index, value in enumerate(header_row):
        text = convert.cell_text(value).strip().lower()
        if text:
            headers.setdefault(text, index)
    return headers


def column_offset(raw, headers, spec, what):
    """Resolve a header name, column letter or 0-based index to a range offset."""
    raw = "" if raw is None else str(raw).strip()
    if not raw:
        raise CalcError("Every %s key needs a 'column'." % what)
    if raw.lower() in headers:
        offset = headers[raw.lower()]
    elif raw.isdigit():
        offset = int(raw)
    elif raw.isalpha() and len(raw) <= 3:
        offset = convert.col_to_index(raw) - spec.start_col
    else:
        known = ", ".join(sorted(headers)) if headers else "none read"
        raise CalcError(
            "Cannot resolve %s column %r. Use a column letter, a 0-based index "
            "within the range, or a header name (headers here: %s)."
            % (what, raw, known)
        )
    if not (0 <= offset < spec.cols):
        raise CalcError(
            "%s column %r resolves outside the range %s."
            % (what.capitalize(), raw, spec.name())
        )
    return offset


@tool(
    "structure_edit",
    "Insert or delete whole rows or columns. Everything below or to the right shifts, "
    "and formulas are adjusted by Calc.",
    properties={
        "document": DOCUMENT,
        "sheet": SHEET,
        "operation": enum(
            "What to do.",
            ["insert_rows", "delete_rows", "insert_columns", "delete_columns"],
        ),
        "at": string(
            "Where: a 1-based row number ('5') for row operations, or a column "
            "letter ('C') for column operations."
        ),
        "count": integer("How many rows or columns. Default 1."),
    },
    required=["operation", "at"],
    title="Insert or delete rows/columns",
)
def structure_edit(args):
    conn, doc, sheet = doc_and_sheet(args)
    operation = args["operation"]
    count = int_arg(args, "count", 1) or 1
    if count < 1:
        raise CalcError("'count' must be at least 1.")
    at = str(args["at"]).strip().lstrip("$")

    is_row = operation.endswith("rows")
    if is_row:
        if not at.isdigit():
            raise CalcError("For row operations 'at' must be a row number, e.g. '5'.")
        index = int(at) - 1
        container = sheet.Rows
        label = "row %s" % at
    else:
        if at.isdigit():
            index = int(at) - 1
        else:
            index = convert.col_to_index(at)
        container = sheet.Columns
        label = "column %s" % convert.index_to_col(index)
    if index < 0:
        raise CalcError("'at' must be positive.")

    verb = "insert" if operation.startswith("insert") else "delete"
    with undo_step(doc, "Claude: %s %d at %s" % (verb, count, label)):
        if verb == "insert":
            container.insertByIndex(index, count)
        else:
            container.removeByIndex(index, count)

    return "%s %d %s at %s on sheet '%s'. Used range is now %s." % (
        {"insert": "Inserted", "delete": "Deleted"}[verb], count,
        ("row" if is_row else "column") + ("s" if count > 1 else ""),
        label, sheet.Name, describe_used(sheet),
    )


@tool(
    "manage_sheets",
    "Add, delete, rename, move, copy or activate a sheet.",
    properties={
        "document": DOCUMENT,
        "operation": enum(
            "What to do.",
            ["add", "delete", "rename", "move", "copy", "activate"],
        ),
        "name": string("The sheet to act on (for add, the name of the new sheet)."),
        "new_name": string("New name, for rename and copy."),
        "position": integer(
            "0-based position for add, move and copy. Defaults to the end."
        ),
    },
    required=["operation"],
    title="Manage sheets",
)
def manage_sheets(args):
    conn, doc = doc_only(args)
    sheets = doc.Sheets
    operation = args["operation"]
    name = args.get("name")
    new_name = args.get("new_name")
    position = int_arg(args, "position", None)

    def listing():
        return "Sheets: %s" % ", ".join(sheets.ElementNames)

    with undo_step(doc, "Claude: %s sheet" % operation):
        if operation == "add":
            if not name:
                raise CalcError("'name' is required to add a sheet.")
            if sheets.hasByName(name):
                raise CalcError("A sheet named %r already exists." % name)
            index = sheets.Count if position is None else max(0, min(position, sheets.Count))
            sheets.insertNewByName(name, index)
            return "Added sheet '%s' at position %d. %s" % (name, index, listing())

        if operation == "delete":
            if not name:
                raise CalcError("'name' is required to delete a sheet.")
            sheet = resolve_sheet(doc, name)
            if sheets.Count == 1:
                raise CalcError("Cannot delete the only sheet in the document.")
            actual = sheet.Name
            sheets.removeByName(actual)
            return "Deleted sheet '%s'. %s" % (actual, listing())

        if operation == "rename":
            if not (name and new_name):
                raise CalcError("'name' and 'new_name' are both required to rename.")
            sheet = resolve_sheet(doc, name)
            old = sheet.Name
            sheet.setName(new_name)
            return "Renamed sheet '%s' to '%s'. %s" % (old, new_name, listing())

        if operation == "move":
            if not name:
                raise CalcError("'name' is required to move a sheet.")
            sheet = resolve_sheet(doc, name)
            index = sheets.Count - 1 if position is None else max(0, min(position, sheets.Count - 1))
            sheets.moveByName(sheet.Name, index)
            return "Moved sheet '%s' to position %d. %s" % (sheet.Name, index, listing())

        if operation == "copy":
            if not name:
                raise CalcError("'name' is required to copy a sheet.")
            sheet = resolve_sheet(doc, name)
            target_name = new_name or ("%s (copy)" % sheet.Name)
            if sheets.hasByName(target_name):
                raise CalcError("A sheet named %r already exists." % target_name)
            index = sheets.Count if position is None else max(0, min(position, sheets.Count))
            sheets.copyByName(sheet.Name, target_name, index)
            return "Copied sheet '%s' to '%s'. %s" % (sheet.Name, target_name, listing())

        if operation == "activate":
            if not name:
                raise CalcError("'name' is required to activate a sheet.")
            sheet = resolve_sheet(doc, name)
            doc.CurrentController.setActiveSheet(sheet)
            return "Sheet '%s' is now active in the window." % sheet.Name

    raise CalcError("Unknown operation %r." % operation)


@tool(
    "sort_range",
    "Sort a range by one or more columns. Set has_header so the first row stays put.",
    properties={
        "document": DOCUMENT,
        "sheet": SHEET,
        "range": string(
            "Range to sort, e.g. 'A1:D50'. Omit to sort the whole used area."
        ),
        "by": array(
            "Sort keys, applied in order. Each is a column letter ('B'), a 0-based "
            "index within the range, or a header name when has_header is true.",
            {
                "type": "object",
                "properties": {
                    "column": {"type": "string"},
                    "descending": {"type": "boolean"},
                },
                "required": ["column"],
                "additionalProperties": False,
            },
        ),
        "has_header": boolean("Treat the first row as headers. Default true."),
    },
    required=["by"],
    title="Sort range",
)
def sort_range(args):
    conn, doc, sheet, spec = target(args)
    has_header = bool_arg(args, "has_header", True)
    keys = args.get("by") or []
    if not keys:
        raise CalcError("'by' needs at least one sort key.")

    headers = header_map(sheet, spec, has_header)

    fields = []
    described = []
    for key in keys:
        offset = column_offset(key.get("column"), headers, spec, "sort")
        raw = str(key.get("column")).strip()
        ascending = not bool(key.get("descending"))
        fields.append(
            make_struct(
                "com.sun.star.table.TableSortField",
                Field=offset,
                IsAscending=ascending,
                IsCaseSensitive=False,
            )
        )
        letter = convert.index_to_col(spec.start_col + offset)
        label = letter if raw.lower() == letter.lower() else "%s (%s)" % (raw, letter)
        described.append("%s %s" % (label, "asc" if ascending else "desc"))

    rng = cell_range(sheet, spec)
    descriptor = rng.createSortDescriptor()
    for entry in descriptor:
        if entry.Name == "SortFields":
            entry.Value = typed_any(
                "[]com.sun.star.table.TableSortField", tuple(fields)
            )
        elif entry.Name == "ContainsHeader":
            entry.Value = has_header
        elif entry.Name == "BindFormatsToContent":
            entry.Value = False

    with undo_step(doc, "Claude: sort %s.%s" % (sheet.Name, spec.name())):
        rng.sort(descriptor)

    return "Sorted %s.%s by %s (%s)." % (
        sheet.Name, spec.name(), ", ".join(described),
        "header row kept" if has_header else "no header",
    )


def _search_descriptor(source, args):
    desc = source.createSearchDescriptor()
    desc.SearchString = str(args.get("query", ""))
    desc.SearchCaseSensitive = bool_arg(args, "case_sensitive")
    desc.SearchRegularExpression = bool_arg(args, "regex")
    desc.SearchWords = bool_arg(args, "whole_cell")
    return desc


@tool(
    "find_cells",
    "Find every cell matching a string or regular expression, and report their "
    "addresses and contents.",
    properties={
        "document": DOCUMENT,
        "sheet": SHEET,
        "query": string("Text or regular expression to look for."),
        "regex": boolean("Treat the query as a regular expression. Default false."),
        "case_sensitive": boolean("Default false."),
        "whole_cell": boolean("Match whole cells only. Default false."),
        "all_sheets": boolean("Search the entire document. Default false."),
        "limit": integer("Maximum matches to report. Default 100."),
    },
    required=["query"],
    title="Find cells",
    read_only=True,
)
def find_cells(args):
    conn, doc = doc_only(args)
    limit = int_arg(args, "limit", 100) or 100

    if bool_arg(args, "all_sheets"):
        source = doc
        scope = "the whole document"
    else:
        source = resolve_sheet(doc, args.get("sheet"))
        scope = "sheet '%s'" % source.Name

    desc = _search_descriptor(source, args)
    found = source.findAll(desc)
    if found is None or found.getCount() == 0:
        return "No cells in %s match %r." % (scope, args["query"])

    total = found.getCount()
    lines = []
    for i in range(min(total, limit)):
        entry = found.getByIndex(i)
        try:
            address = entry.AbsoluteName.replace("$", "")
        except Exception:
            address = "?"
        try:
            text = convert.cell_text(entry.getCellByPosition(0, 0).getString())
        except Exception:
            text = ""
        lines.append("%s\t%s" % (address, text))

    header = "%d match(es) in %s for %r:" % (total, scope, args["query"])
    body = header + "\n" + "\n".join(lines)
    if total > limit:
        body += "\n... %d more (raise 'limit' to see them)." % (total - limit)
    return body


@tool(
    "find_replace",
    "Replace text across a range, a sheet, or the whole document. Returns how many "
    "cells changed, and is reversible with Ctrl+Z.",
    properties={
        "document": DOCUMENT,
        "sheet": SHEET,
        "range": string("Restrict to this range. Omit to cover the whole sheet."),
        "query": string("Text or regular expression to find."),
        "replacement": string("Replacement text. Use $1, $2 for regex groups."),
        "regex": boolean("Treat the query as a regular expression. Default false."),
        "case_sensitive": boolean("Default false."),
        "whole_cell": boolean("Match whole cells only. Default false."),
        "all_sheets": boolean("Replace across the entire document. Default false."),
    },
    required=["query", "replacement"],
    title="Find and replace",
)
def find_replace(args):
    if args.get("range"):
        conn, doc, sheet, spec = target(args, require_range=True)
        source = cell_range(sheet, spec)
        scope = "%s.%s" % (sheet.Name, spec.name())
    else:
        conn, doc = doc_only(args)
        if bool_arg(args, "all_sheets"):
            source = doc
            scope = "the whole document"
        else:
            source = resolve_sheet(doc, args.get("sheet"))
            scope = "sheet '%s'" % source.Name

    desc = source.createReplaceDescriptor()
    desc.SearchString = str(args["query"])
    desc.ReplaceString = str(args["replacement"])
    desc.SearchCaseSensitive = bool_arg(args, "case_sensitive")
    desc.SearchRegularExpression = bool_arg(args, "regex")
    desc.SearchWords = bool_arg(args, "whole_cell")

    with undo_step(doc, "Claude: replace in %s" % scope):
        count = source.replaceAll(desc)

    if not count:
        return "Nothing in %s matched %r; no changes made." % (scope, args["query"])
    return "Replaced %r with %r in %d cell(s) across %s." % (
        args["query"], args["replacement"], count, scope,
    )


# com.sun.star.sheet.FilterOperator2, by the name a person would reach for.
FILTER_OPERATORS = {
    "equals": "EQUAL",
    "not_equals": "NOT_EQUAL",
    "greater": "GREATER",
    "greater_equal": "GREATER_EQUAL",
    "less": "LESS",
    "less_equal": "LESS_EQUAL",
    "contains": "CONTAINS",
    "not_contains": "DOES_NOT_CONTAIN",
    "begins_with": "BEGINS_WITH",
    "not_begins_with": "DOES_NOT_BEGIN_WITH",
    "ends_with": "ENDS_WITH",
    "not_ends_with": "DOES_NOT_END_WITH",
    # LibreOffice 24.2 returns non-blank rows for both FilterOperator2.EMPTY and
    # NOT_EMPTY, so these map onto comparisons against an empty string, which
    # behave correctly for text and numeric columns alike.
    "empty": "EQUAL",
    "not_empty": "NOT_EQUAL",
    "top_values": "TOP_VALUES",
    "bottom_values": "BOTTOM_VALUES",
    "top_percent": "TOP_PERCENT",
    "bottom_percent": "BOTTOM_PERCENT",
}
VALUELESS_OPERATORS = ("empty", "not_empty")


def _filter_constant(name):
    return uno_module().getConstantByName(
        "com.sun.star.sheet.FilterOperator2." + FILTER_OPERATORS[name]
    )


def _database_range_name(sheet):
    safe = "".join(ch if ch.isalnum() else "_" for ch in sheet.Name)
    return "Claude_Filter_%s" % (safe or "Sheet")


def _autofilter(doc, sheet, spec, enable):
    ranges = doc.DatabaseRanges
    name = _database_range_name(sheet)
    address = make_struct(
        "com.sun.star.table.CellRangeAddress",
        Sheet=sheet.RangeAddress.Sheet,
        StartColumn=spec.start_col,
        StartRow=spec.start_row,
        EndColumn=spec.end_col,
        EndRow=spec.end_row,
    )
    if enable:
        if ranges.hasByName(name):
            # Re-point it, in case the table has grown since last time.
            ranges.removeByName(name)
        ranges.addNewByName(name, address)
        ranges.getByName(name).AutoFilter = True
        return name
    if ranges.hasByName(name):
        ranges.getByName(name).AutoFilter = False
        ranges.removeByName(name)
        return name
    return None


# Calc writes conditions into criteria cells as a comparison prefix followed by
# a value: ">100", "<>North". Longest prefixes first so ">=" wins over ">".
CRITERIA_PREFIXES = (
    (">=", "greater_equal"),
    ("<=", "less_equal"),
    ("<>", "not_equals"),
    (">", "greater"),
    ("<", "less"),
    ("=", "equals"),
)
MAX_FILTER_FIELDS = 8


def _parse_criterion(text):
    """'>100' -> ('greater', '100'); 'North' -> ('equals', 'North')."""
    text = text.strip()
    if not text:
        return None
    for prefix, operator in CRITERIA_PREFIXES:
        if text.startswith(prefix):
            return operator, text[len(prefix):].strip()
    return "equals", text


def _coerce(raw):
    try:
        return float(raw)
    except (TypeError, ValueError):
        return raw


def criteria_conditions(doc, criteria_ref):
    """Read a Calc-style criteria block into (condition, starts_a_row) pairs.

    The block's first row names columns; each row beneath holds one set of
    conditions, ANDed across its columns, and the rows are ORed with each other.
    That is the layout Calc's own Advanced Filter dialog expects, and it is not
    reachable through the UNO API -- createFilterDescriptorByObject returns null
    for a criteria range -- so the block is parsed here instead.
    """
    sheet, spec = resolve_range(doc, criteria_ref, None, default_to_used=False)
    grid = cell_range(sheet, spec).getDataArray()
    if len(grid) < 2:
        raise CalcError(
            "The criteria range %s needs a header row naming the columns and at "
            "least one row of conditions beneath it." % spec.name())

    names = [convert.cell_text(value).strip() for value in grid[0]]
    parsed = []
    for row in grid[1:]:
        started = False
        for index, value in enumerate(row):
            criterion = _parse_criterion(convert.cell_text(value))
            if criterion is None:
                continue
            if index >= len(names) or not names[index]:
                raise CalcError(
                    "The criteria block has a condition in a column with no header "
                    "(column %d of %s)." % (index + 1, spec.name()))
            operator, raw = criterion
            parsed.append((
                {"column": names[index], "operator": operator, "value": _coerce(raw)},
                not started,
            ))
            started = True
    if not parsed:
        raise CalcError(
            "The criteria range %s has a header row but no conditions under it."
            % spec.name())
    return parsed


def _copied_rows(sheet, anchor, source_spec):
    """How many rows the filter actually wrote at the destination."""
    end_row = min(anchor.start_row + source_spec.rows, anchor.start_row + 1000)
    block = cell_range(sheet, convert.RangeSpec(
        anchor.start_col, anchor.start_row,
        anchor.start_col + source_spec.cols - 1, end_row - 1)).getDataArray()
    count = 0
    for row in block:
        if all(convert.cell_text(value) == "" for value in row):
            break
        count += 1
    return count


@tool(
    "filter_range",
    "Filter a table so only matching rows stay visible, clear a filter, or show "
    "Calc's AutoFilter dropdown arrows. Filtering hides rows rather than deleting "
    "anything, and read_range with visible_only=true reads back just what is showing.",
    properties={
        "document": DOCUMENT,
        "sheet": SHEET,
        "range": string(
            "The table including its header row, e.g. 'A1:D50'. Omit to use the "
            "sheet's used area."
        ),
        "operation": enum(
            "What to do. Default apply.",
            ["apply", "clear", "show_dropdowns", "hide_dropdowns"],
        ),
        "conditions": array(
            "Conditions to apply. Each names a column (header name, column letter, "
            "or 0-based index within the range), an operator, and a value.",
            {
                "type": "object",
                "properties": {
                    "column": {"type": "string"},
                    "operator": {"type": "string", "enum": sorted(FILTER_OPERATORS)},
                    "value": {"type": ["string", "number", "boolean", "null"]},
                },
                "required": ["column", "operator"],
                "additionalProperties": False,
            },
        ),
        "match": enum(
            "Whether a row must satisfy all conditions or any of them. Default all.",
            ["all", "any"],
        ),
        "has_header": boolean("Treat the first row as headers. Default true."),
        "regex": boolean("Interpret text values as regular expressions. Default false."),
        "case_sensitive": boolean("Default false."),
        "criteria_range": string(
            "An advanced filter: a block of cells holding the conditions, laid out "
            "the way Calc's Advanced Filter expects -- a header row naming columns, "
            "then one row per set of conditions. Conditions across a row are ANDed, "
            "separate rows are ORed. Cells may carry a comparison, e.g. '>100' or "
            "'<>North'. Use instead of 'conditions'."
        ),
        "copy_to": string(
            "Copy the matching rows here instead of hiding the rest, e.g. 'H1' or "
            "'Results.A1'. The source table is left untouched."
        ),
        "unique_only": boolean(
            "Drop duplicate rows from the result. Default false."
        ),
    },
    title="Filter table",
)
def filter_range(args):
    conn, doc, sheet, spec = target(args)
    operation = (args.get("operation") or "apply").lower()
    has_header = bool_arg(args, "has_header", True)
    rng = cell_range(sheet, spec)

    if operation in ("show_dropdowns", "hide_dropdowns"):
        enable = operation == "show_dropdowns"
        with undo_step(doc, "Claude: autofilter %s.%s" % (sheet.Name, spec.name())):
            name = _autofilter(doc, sheet, spec, enable)
        if enable:
            return (
                "AutoFilter dropdowns are now on %s.%s, so you or the user can filter "
                "from the column headers." % (sheet.Name, spec.name())
            )
        if name is None:
            return "There were no AutoFilter dropdowns on sheet '%s' to remove." % sheet.Name
        return "Removed the AutoFilter dropdowns from sheet '%s'." % sheet.Name

    descriptor = rng.createFilterDescriptor(True)
    descriptor.ContainsHeader = has_header
    descriptor.UseRegularExpressions = bool_arg(args, "regex")
    descriptor.IsCaseSensitive = bool_arg(args, "case_sensitive")

    if operation == "clear":
        with undo_step(doc, "Claude: clear filter %s.%s" % (sheet.Name, spec.name())):
            descriptor.setFilterFields2(())
            rng.filter(descriptor)
        return "Cleared the filter on %s.%s; every row is visible again." % (
            sheet.Name, spec.name()
        )

    # Either an explicit list of conditions, or an advanced filter's criteria
    # block. Each entry carries whether it starts a new OR group.
    if args.get("criteria_range"):
        if args.get("conditions"):
            raise CalcError(
                "Give either 'conditions' or 'criteria_range', not both.")
        entries = criteria_conditions(doc, args["criteria_range"])
        source = "the criteria in %s" % args["criteria_range"]
    else:
        conditions = args.get("conditions") or []
        if not conditions:
            raise CalcError(
                "'conditions' or 'criteria_range' is required to apply a filter. To "
                "remove one, call this with operation='clear'."
            )
        any_match = (args.get("match") or "all").lower() == "any"
        entries = [(condition, any_match) for condition in conditions]
        source = None

    if len(entries) > MAX_FILTER_FIELDS:
        raise CalcError(
            "Calc accepts at most %d filter conditions at once; %d were given."
            % (MAX_FILTER_FIELDS, len(entries)))

    headers = header_map(sheet, spec, has_header)
    fields = []
    described = []
    for index, (condition, starts_group) in enumerate(entries):
        operator = str(condition.get("operator") or "equals").lower()
        if operator not in FILTER_OPERATORS:
            raise CalcError(
                "Unknown operator %r. Choose from: %s"
                % (operator, ", ".join(sorted(FILTER_OPERATORS)))
            )
        offset = column_offset(condition.get("column"), headers, spec, "filter")
        value = condition.get("value")
        if operator not in VALUELESS_OPERATORS and value is None:
            raise CalcError("Operator %r needs a 'value'." % operator)

        field = make_struct(
            "com.sun.star.sheet.TableFilterField2",
            Field=offset,
            Operator=_filter_constant(operator),
            # The first field's Connection is ignored; each later one joins it to
            # what came before, and AND binds tighter than OR, so marking the
            # first condition of each group OR gives (a AND b) OR (c AND d).
            Connection=uno_module().Enum(
                "com.sun.star.sheet.FilterConnection",
                "OR" if (index and starts_group) else "AND"),
        )
        if operator in VALUELESS_OPERATORS:
            field.IsNumeric = False
            field.StringValue = ""  # with EQUAL / NOT_EQUAL, this tests blankness
        elif isinstance(value, bool):
            field.IsNumeric = True
            field.NumericValue = 1.0 if value else 0.0
        elif isinstance(value, (int, float)):
            field.IsNumeric = True
            field.NumericValue = float(value)
        else:
            field.IsNumeric = False
            field.StringValue = str(value)
        fields.append(field)

        letter = convert.index_to_col(spec.start_col + offset)
        raw = str(condition.get("column")).strip()
        label = letter if raw.lower() == letter.lower() else "%s (%s)" % (raw, letter)
        joiner = " OR " if (index and starts_group) else (" AND " if index else "")
        described.append(joiner + (
            "%s %s" % (label, operator) if operator in VALUELESS_OPERATORS
            else "%s %s %r" % (label, operator, value)))

    destination = None
    if args.get("copy_to"):
        dest_sheet, dest_anchor = resolve_range(
            doc, args["copy_to"], None, default_to_used=False)
        descriptor.CopyOutputData = True
        descriptor.OutputPosition = make_struct(
            "com.sun.star.table.CellAddress",
            Sheet=dest_sheet.RangeAddress.Sheet,
            Column=dest_anchor.start_col, Row=dest_anchor.start_row)
        destination = (dest_sheet, dest_anchor)
    if bool_arg(args, "unique_only"):
        descriptor.SkipDuplicates = True

    with undo_step(doc, "Claude: filter %s.%s" % (sheet.Name, spec.name())):
        descriptor.setFilterFields2(tuple(fields))
        rng.filter(descriptor)

    where = "".join(described)
    if source:
        where = "%s (%s)" % (where, source)
    summary = "Filtered %s.%s where %s." % (sheet.Name, spec.name(), where)

    if destination is not None:
        dest_sheet, dest_anchor = destination
        copied = _copied_rows(dest_sheet, dest_anchor, spec)
        data_rows = max(copied - (1 if has_header else 0), 0)
        summary += (
            " Copied %d matching row(s) to %s.%s; the source table is unchanged and "
            "still shows every row." % (data_rows, dest_sheet.Name,
                                        convert.cell_name(dest_anchor.start_col,
                                                          dest_anchor.start_row)))
        if not data_rows:
            summary += " Nothing matched -- check the values."
        return summary

    shown = visible_rows(rng)
    if shown is not None:
        data_rows = spec.rows - (1 if has_header else 0)
        visible_data = len([r for r in shown if not (has_header and r == spec.start_row)])
        summary += " %d of %d data rows are now visible (%d hidden)." % (
            visible_data, data_rows, data_rows - visible_data
        )
        if visible_data == 0:
            summary += " Nothing matched -- check the values, or clear the filter."
    summary += (
        " Rows are hidden, not deleted; read_range with visible_only=true returns "
        "only what is showing."
    )
    return summary


ORIENTATIONS = {"rows": "ROWS", "columns": "COLUMNS"}
_ROWS_REF = re.compile(r"^\d+(:\d+)?$")
_COLS_REF = re.compile(r"^[A-Za-z]{1,3}(:[A-Za-z]{1,3})?$")


def _outline_target(sheet, raw, orientation):
    """Parse a rows ('5:10') or columns ('C:F') reference for an outline call."""
    text = convert.split_sheet(str(raw).strip())[1].replace("$", "")
    if not orientation:
        if _ROWS_REF.match(text):
            orientation = "rows"
        elif _COLS_REF.match(text):
            orientation = "columns"
        else:
            orientation = "rows"
    spec = convert.parse_range(text, used_range(sheet))
    return spec, orientation


@tool(
    "outline",
    "Group rows or columns so they can be collapsed and expanded from the margin "
    "(Data > Group and Outline), collapse or expand a group, show everything down "
    "to a given level, or build the outline automatically from subtotal formulas.",
    properties={
        "document": DOCUMENT,
        "sheet": SHEET,
        "operation": enum(
            "What to do. 'auto' derives groups from formulas that total the rows "
            "above them; 'clear' removes every group on the sheet.",
            ["group", "ungroup", "collapse", "expand", "show_level", "auto", "clear"],
        ),
        "range": string(
            "Rows as '5:10' (or '7' for one), columns as 'C:F'. For 'auto', the "
            "whole table, e.g. 'A1:D40'."
        ),
        "orientation": enum(
            "Whether the range means rows or columns. Inferred from the reference "
            "when omitted.",
            sorted(ORIENTATIONS),
        ),
        "level": integer(
            "For show_level: 1 shows the least detail, higher numbers reveal more. "
            "Only meaningful where groups are nested inside one another -- with a "
            "single level of grouping it changes nothing, and collapse/expand is "
            "what you want."
        ),
    },
    required=["operation"],
    title="Group and outline",
)
def outline(args):
    conn, doc, sheet = doc_and_sheet(args)
    operation = args["operation"]
    requested = (args.get("orientation") or "").lower() or None
    if requested and requested not in ORIENTATIONS:
        raise CalcError("orientation must be 'rows' or 'columns'.")

    if operation == "clear":
        with undo_step(doc, "Claude: clear outline %s" % sheet.Name):
            sheet.clearOutline()
        return "Removed every row and column group from sheet '%s'." % sheet.Name

    if operation == "show_level":
        level = int_arg(args, "level", 0) or 0
        if level < 1:
            raise CalcError("'level' must be 1 or more.")
        orientation = requested or "rows"
        with undo_step(doc, "Claude: outline level %d" % level):
            sheet.showLevel(
                level, uno_module().Enum(
                    "com.sun.star.table.TableOrientation", ORIENTATIONS[orientation]))
        return (
            "Showing outline level %d for %s on sheet '%s'. (Levels only do "
            "anything where groups are nested; for a single group use collapse "
            "and expand.)" % (level, orientation, sheet.Name))

    if not args.get("range"):
        raise CalcError("'range' is required for %s." % operation)
    spec, orientation = _outline_target(sheet, args["range"], requested)
    address = make_struct(
        "com.sun.star.table.CellRangeAddress",
        Sheet=sheet.RangeAddress.Sheet,
        StartColumn=spec.start_col, StartRow=spec.start_row,
        EndColumn=spec.end_col, EndRow=spec.end_row,
    )
    unit = uno_module().Enum(
        "com.sun.star.table.TableOrientation", ORIENTATIONS[orientation])

    def label():
        if orientation == "rows":
            return "rows %d:%d" % (spec.start_row + 1, spec.end_row + 1)
        return "columns %s:%s" % (convert.index_to_col(spec.start_col),
                                  convert.index_to_col(spec.end_col))

    with undo_step(doc, "Claude: outline %s %s" % (operation, spec.name())):
        if operation == "group":
            sheet.group(address, unit)
            done = "Grouped %s" % label()
        elif operation == "ungroup":
            sheet.ungroup(address, unit)
            done = "Ungrouped %s" % label()
        elif operation == "collapse":
            sheet.hideDetail(address)
            done = "Collapsed the group covering %s" % label()
        elif operation == "expand":
            sheet.showDetail(address)
            done = "Expanded the group covering %s" % label()
        elif operation == "auto":
            sheet.autoOutline(address)
            done = "Built an outline over %s from its formulas" % spec.name()
        else:
            raise CalcError("Unknown operation %r." % operation)

    return "%s on sheet '%s'." % (done, sheet.Name)

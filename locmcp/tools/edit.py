"""Structural edits: rows and columns, sheets, sorting, search and replace."""

from .. import convert
from ..bridge import (
    CalcError, cell_range, make_struct, resolve_sheet, typed_any, undo_step,
)
from ..registry import DOCUMENT, SHEET, array, boolean, enum, integer, string, tool
from .base import bool_arg, describe_used, doc_and_sheet, doc_only, int_arg, target


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

    headers = {}
    if has_header:
        header_row = cell_range(
            sheet,
            convert.RangeSpec(spec.start_col, spec.start_row, spec.end_col, spec.start_row),
        ).getDataArray()[0]
        for i, value in enumerate(header_row):
            text = convert.cell_text(value).strip().lower()
            if text:
                headers.setdefault(text, i)

    fields = []
    described = []
    for key in keys:
        raw = str(key.get("column", "")).strip()
        if not raw:
            raise CalcError("Every sort key needs a 'column'.")
        lowered = raw.lower()
        if lowered in headers:
            offset = headers[lowered]
        elif raw.isdigit():
            offset = int(raw)
        else:
            try:
                offset = convert.col_to_index(raw) - spec.start_col
            except ValueError:
                raise CalcError(
                    "Cannot resolve sort column %r. Use a column letter, a 0-based "
                    "index, or a header name." % raw
                )
        if not (0 <= offset < spec.cols):
            raise CalcError(
                "Sort column %r resolves outside the range %s." % (raw, spec.name())
            )
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

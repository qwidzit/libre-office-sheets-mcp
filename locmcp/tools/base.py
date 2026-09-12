"""Helpers shared by the tool modules."""

from .. import convert
from ..bridge import (
    CalcError, cell_range, connect, resolve_document, resolve_range,
    resolve_sheet, used_range, visible_rows, with_reconnect,
)

MAX_CELLS = 50000


def target(args, require_range=False):
    """Resolve (conn, doc, sheet, spec) from the common document/sheet/range args.

    Returned inside `with_reconnect` so a stale UNO bridge is retried once.
    """

    def run(conn):
        doc = resolve_document(conn, args.get("document"))
        sheet, spec = resolve_range(
            doc,
            args.get("range"),
            args.get("sheet"),
            default_to_used=not require_range,
        )
        return conn, doc, sheet, spec

    return with_reconnect(run)


def doc_only(args):
    def run(conn):
        return conn, resolve_document(conn, args.get("document"))

    return with_reconnect(run)


def doc_and_sheet(args):
    def run(conn):
        doc = resolve_document(conn, args.get("document"))
        return conn, doc, resolve_sheet(doc, args.get("sheet"))

    return with_reconnect(run)


def check_size(spec, limit=MAX_CELLS):
    if spec.cells > limit:
        raise CalcError(
            "Range %s covers %d cells, over the %d-cell limit. Read or write it in "
            "smaller chunks." % (spec.name(), spec.cells, limit)
        )


def sheet_name(sheet):
    return sheet.Name


def bool_arg(args, key, default=False):
    value = args.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def int_arg(args, key, default=None):
    value = args.get(key, default)
    if value in (None, ""):
        return default
    return int(value)


def describe_used(sheet):
    spec = used_range(sheet)
    cell = sheet.getCellByPosition(spec.start_col, spec.start_row)
    if spec.cells == 1 and cell.getType().value == "EMPTY":
        return "empty"
    text = "%s (%d rows x %d cols)" % (spec.name(), spec.rows, spec.cols)
    # A filtered sheet shows fewer rows than it holds; say so, or a reader will
    # wonder why the window and the data disagree.
    shown = visible_rows(cell_range(sheet, spec))
    if shown is not None and len(shown) < spec.rows:
        text += " -- FILTERED, %d of %d rows visible" % (len(shown), spec.rows)
    return text


__all__ = [
    "CalcError", "MAX_CELLS", "bool_arg", "cell_range", "check_size", "connect",
    "convert", "describe_used", "doc_and_sheet", "doc_only",
    "int_arg", "resolve_document", "resolve_range", "resolve_sheet",
    "sheet_name", "target", "used_range", "with_reconnect",
]

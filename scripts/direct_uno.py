"""A direct UNO connection, for test assertions that must bypass the server."""

import uno


def _documents():
    """Every open Calc document, in the order LibreOffice enumerates them."""
    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local)
    ctx = resolver.resolve(
        "uno:socket,host=127.0.0.1,port=2002;urp;StarOffice.ComponentContext")
    desktop = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.frame.Desktop", ctx)
    enum = desktop.getComponents().createEnumeration()
    docs = []
    while enum.hasMoreElements():
        component = enum.nextElement()
        try:
            if component.supportsService("com.sun.star.sheet.SpreadsheetDocument"):
                docs.append(component)
        except Exception:
            continue
    return docs


def _document():
    docs = _documents()
    if not docs:
        raise RuntimeError("no spreadsheet open")
    return docs[-1]


def document_with_sheet(name):
    """The newest open document containing a sheet of this name.

    Suites run against their own document but share one LibreOffice, so
    identify the right one by a sheet the suite created rather than by
    position.
    """
    for doc in reversed(_documents()):
        try:
            if doc.Sheets.hasByName(name):
                return doc
        except Exception:
            continue
    raise RuntimeError("no open document has a sheet named %r" % name)


def undo_titles_for(sheet_name):
    return list(document_with_sheet(sheet_name).getUndoManager().getAllUndoActionTitles())


def undo_for(sheet_name):
    document_with_sheet(sheet_name).getUndoManager().undo()

"""A direct UNO connection, for test assertions that must bypass the server."""

import uno


def _documents():
    """Every open Calc document. LibreOffice enumerates these newest first."""
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


def document_with_sheet(name):
    """The newest open document containing a sheet of this name.

    Suites run against their own document but share one LibreOffice, so
    identify the right one by a sheet the suite created rather than by
    position.
    """
    # Newest first, so a suite finds the document it just created rather than
    # one left over from an earlier run.
    for doc in _documents():
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

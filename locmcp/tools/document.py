"""Conditional formatting, validation, page setup, names, comments, protection.

Several of these UNO objects are returned by value: you read the struct, change
it, then assign it back, or nothing happens. That pattern repeats throughout.
"""

from .. import convert
from ..bridge import (
    CalcError, cell_range, make_struct, prop, undo_step,
    uno_module, used_range,
)
from ..registry import DOCUMENT, SHEET, array, boolean, enum, number, string, tool
from .base import bool_arg, doc_and_sheet, doc_only, target

MM100 = 100.0

CONDITION_OPERATORS = {
    "equals": "EQUAL",
    "not_equals": "NOT_EQUAL",
    "greater": "GREATER",
    "greater_equal": "GREATER_EQUAL",
    "less": "LESS",
    "less_equal": "LESS_EQUAL",
    "between": "BETWEEN",
    "not_between": "NOT_BETWEEN",
    "formula": "FORMULA",
}

VALIDATION_TYPES = {
    "any": "ANY",
    "whole_number": "WHOLE",
    "decimal": "DECIMAL",
    "date": "DATE",
    "time": "TIME",
    "text_length": "TEXT_LEN",
    "list": "LIST",
    "custom": "CUSTOM",
}


def _enum(type_name, value):
    return uno_module().Enum(type_name, value)


def _cell_address(sheet, col, row):
    return make_struct(
        "com.sun.star.table.CellAddress",
        Sheet=sheet.RangeAddress.Sheet, Column=col, Row=row,
    )


def _quote_sheet(name):
    if any(ch in name for ch in " '.!$-+()"):
        return "'%s'" % name.replace("'", "''")
    return name


def _absolute_ref(sheet, spec):
    return "$%s.$%s$%d:$%s$%d" % (
        _quote_sheet(sheet.Name),
        convert.index_to_col(spec.start_col), spec.start_row + 1,
        convert.index_to_col(spec.end_col), spec.end_row + 1,
    )


def _ensure_style(doc, name, background=None, text_colour=None, bold=None):
    """Find or create a cell style, so 'highlight in red' needs no style admin."""
    styles = doc.StyleFamilies.getByName("CellStyles")
    if not styles.hasByName(name):
        style = doc.createInstance("com.sun.star.style.CellStyle")
        styles.insertByName(name, style)
    style = styles.getByName(name)
    if background is not None:
        style.CellBackColor = background
        style.IsCellBackgroundTransparent = background == -1
    if text_colour is not None:
        style.CharColor = text_colour
    if bold is not None:
        style.CharWeight = 150.0 if bold else 100.0
    return name


@tool(
    "conditional_format",
    "Colour cells automatically based on their value -- 'anything over 50 in red'. "
    "Give a built-in style name, or just colours and one is made for you.",
    properties={
        "document": DOCUMENT,
        "sheet": SHEET,
        "range": string("Range the rule applies to, e.g. 'B2:B50'."),
        "operation": enum("Default add.", ["add", "clear"]),
        "operator": enum("How to compare. Default greater.", sorted(CONDITION_OPERATORS)),
        "value": string("Value to compare against, or the formula for operator=formula."),
        "value2": string("Upper bound, for between and not_between."),
        "style": string(
            "Existing cell style to apply, e.g. 'Bad', 'Good', 'Neutral', 'Error', "
            "'Warning', 'Accent 1'. Omit and give colours instead."
        ),
        "background_color": string("Fill for matching cells, e.g. '#ffc7ce' or 'red'."),
        "text_color": string("Font colour for matching cells."),
        "bold": boolean("Bold matching cells."),
    },
    required=["range"],
    title="Conditional formatting",
)
def conditional_format(args):
    conn, doc, sheet, spec = target(args, require_range=True)
    rng = cell_range(sheet, spec)
    operation = (args.get("operation") or "add").lower()

    if operation == "clear":
        with undo_step(doc, "Claude: clear conditional format %s" % spec.name()):
            entries = rng.ConditionalFormat
            entries.clear()
            rng.ConditionalFormat = entries
        return "Cleared conditional formatting from %s.%s." % (sheet.Name, spec.name())

    operator = (args.get("operator") or "greater").lower()
    if operator not in CONDITION_OPERATORS:
        raise CalcError(
            "Unknown operator %r. Choose from: %s"
            % (operator, ", ".join(sorted(CONDITION_OPERATORS)))
        )
    if args.get("value") is None:
        raise CalcError("'value' is required (the number, text or formula to test).")

    style = args.get("style")
    if not style:
        if not any(args.get(k) is not None for k in ("background_color", "text_color", "bold")):
            raise CalcError(
                "Give a 'style' name, or colours (background_color / text_color / "
                "bold) for the matching cells."
            )
        background = convert.parse_color(args.get("background_color")) \
            if args.get("background_color") else None
        text_colour = convert.parse_color(args.get("text_color")) \
            if args.get("text_color") else None
        label = "Claude_%s" % (
            ("%06X" % background) if background is not None else "Highlight")
        style = _ensure_style(doc, label, background, text_colour,
                              bool_arg(args, "bold") if "bold" in args else None)
    elif not doc.StyleFamilies.getByName("CellStyles").hasByName(style):
        raise CalcError(
            "No cell style named %r. Available: %s"
            % (style, ", ".join(sorted(doc.StyleFamilies.getByName("CellStyles").ElementNames)))
        )

    settings = [
        prop("Operator", _enum("com.sun.star.sheet.ConditionOperator",
                               CONDITION_OPERATORS[operator])),
        prop("Formula1", str(args["value"])),
        prop("StyleName", style),
        prop("SourcePosition", _cell_address(sheet, spec.start_col, spec.start_row)),
    ]
    if args.get("value2") is not None:
        settings.append(prop("Formula2", str(args["value2"])))

    with undo_step(doc, "Claude: conditional format %s" % spec.name()):
        entries = rng.ConditionalFormat
        entries.addNew(tuple(settings))
        rng.ConditionalFormat = entries

    bound = " and %s" % args["value2"] if args.get("value2") is not None else ""
    return "Cells in %s.%s that are %s %s%s now use the '%s' style (%d rule(s) total)." % (
        sheet.Name, spec.name(), operator, args["value"], bound, style,
        rng.ConditionalFormat.getCount(),
    )


@tool(
    "data_validation",
    "Restrict what may be typed into cells -- a dropdown list, a number range, a "
    "date, a text length -- with optional input hints and error messages.",
    properties={
        "document": DOCUMENT,
        "sheet": SHEET,
        "range": string("Range to validate, e.g. 'C2:C100'."),
        "operation": enum("Default set.", ["set", "clear"]),
        "type": enum("What to allow. Default list.", sorted(VALIDATION_TYPES)),
        "values": array(
            "The allowed entries, for type=list.", {"type": "string"}),
        "operator": enum(
            "How to compare, for the numeric and date types. Default between.",
            sorted(CONDITION_OPERATORS)),
        "min": string("Lower bound, or the single value for non-range operators."),
        "max": string("Upper bound, for between and not_between."),
        "formula": string("Formula returning TRUE for valid entries, for type=custom."),
        "allow_blank": boolean("Permit empty cells. Default true."),
        "input_title": string("Title of the hint shown when the cell is selected."),
        "input_message": string("Body of that hint."),
        "error_title": string("Title of the message shown on a bad entry."),
        "error_message": string("Body of that message."),
        "error_style": enum(
            "How firmly to reject a bad entry. Default stop.",
            ["stop", "warning", "info"]),
    },
    required=["range"],
    title="Data validation",
)
def data_validation(args):
    conn, doc, sheet, spec = target(args, require_range=True)
    rng = cell_range(sheet, spec)
    operation = (args.get("operation") or "set").lower()

    if operation == "clear":
        with undo_step(doc, "Claude: clear validation %s" % spec.name()):
            validation = rng.Validation
            validation.Type = _enum("com.sun.star.sheet.ValidationType", "ANY")
            validation.ShowErrorMessage = False
            validation.ShowInputMessage = False
            rng.Validation = validation
        return "Removed validation from %s.%s." % (sheet.Name, spec.name())

    kind = (args.get("type") or "list").lower()
    if kind not in VALIDATION_TYPES:
        raise CalcError(
            "Unknown type %r. Choose from: %s" % (kind, ", ".join(sorted(VALIDATION_TYPES)))
        )

    validation = rng.Validation
    validation.Type = _enum("com.sun.star.sheet.ValidationType", VALIDATION_TYPES[kind])
    validation.IgnoreBlankCells = bool_arg(args, "allow_blank", True)

    if kind == "list":
        values = args.get("values") or []
        if not values:
            raise CalcError("'values' is required for a dropdown list.")
        # Calc wants the entries as quoted strings joined with semicolons.
        validation.setFormula1(
            ";".join('"%s"' % str(v).replace('"', '""') for v in values))
        validation.ShowList = 1
        described = "one of %s" % ", ".join(str(v) for v in values)
    elif kind == "custom":
        if not args.get("formula"):
            raise CalcError("'formula' is required for type=custom.")
        validation.setFormula1(convert.normalise_formula(str(args["formula"])))
        described = "matching %s" % args["formula"]
    elif kind == "any":
        described = "anything"
    else:
        operator = (args.get("operator") or "between").lower()
        if operator not in CONDITION_OPERATORS:
            raise CalcError("Unknown operator %r." % operator)
        if args.get("min") is None:
            raise CalcError("'min' is required for a %s validation." % kind)
        validation.Operator = _enum(
            "com.sun.star.sheet.ConditionOperator", CONDITION_OPERATORS[operator])
        validation.setFormula1(str(args["min"]))
        if args.get("max") is not None:
            validation.setFormula2(str(args["max"]))
        described = "%s %s%s" % (
            kind.replace("_", " "), operator.replace("_", " "),
            " %s and %s" % (args["min"], args["max"]) if args.get("max") is not None
            else " %s" % args["min"])

    if args.get("input_message") or args.get("input_title"):
        validation.ShowInputMessage = True
        validation.InputTitle = str(args.get("input_title") or "")
        validation.InputMessage = str(args.get("input_message") or "")
    if args.get("error_message") or args.get("error_title"):
        validation.ShowErrorMessage = True
        validation.ErrorTitle = str(args.get("error_title") or "")
        validation.ErrorMessage = str(args.get("error_message") or "")
        validation.ErrorAlertStyle = _enum(
            "com.sun.star.sheet.ValidationAlertStyle",
            (args.get("error_style") or "stop").upper())
    elif kind != "any":
        validation.ShowErrorMessage = True

    with undo_step(doc, "Claude: validation %s" % spec.name()):
        rng.Validation = validation

    return "%s.%s now accepts %s.%s" % (
        sheet.Name, spec.name(), described,
        " A dropdown arrow appears on each cell." if kind == "list" else "",
    )


@tool(
    "page_setup",
    "Control how the sheet prints and exports to PDF: print area, orientation, "
    "fitting to a page, margins, headers and footers, and repeating the header row "
    "on every page.",
    properties={
        "document": DOCUMENT,
        "sheet": SHEET,
        "print_area": string(
            "Range to print, e.g. 'A1:F40'. Pass 'clear' to print everything."),
        "orientation": enum("Page orientation.", ["portrait", "landscape"]),
        "fit_to_pages_wide": number("Squeeze the sheet into this many pages across. 0 = no limit."),
        "fit_to_pages_tall": number("Squeeze the sheet into this many pages down. 0 = no limit."),
        "scale_percent": number("Fixed zoom for printing, e.g. 80. Ignored if fitting to pages."),
        "repeat_rows": string("Rows to repeat at the top of every page, e.g. '1' or '1:2'."),
        "repeat_columns": string("Columns to repeat at the left of every page, e.g. 'A'."),
        "margin_mm": number("Set all four margins, in millimetres."),
        "header_text": string("Centre header text. Pass '' to clear."),
        "footer_text": string("Centre footer text. Pass '' to clear."),
        "print_gridlines": boolean("Print the cell grid."),
        "center_horizontally": boolean("Centre the content across the page."),
        "center_vertically": boolean("Centre the content down the page."),
    },
    title="Page setup",
)
def page_setup(args):
    conn, doc, sheet = doc_and_sheet(args)
    styles = doc.StyleFamilies.getByName("PageStyles")
    style = styles.getByName(sheet.PageStyle)
    applied = []

    with undo_step(doc, "Claude: page setup %s" % sheet.Name):
        area = args.get("print_area")
        if area:
            if str(area).strip().lower() == "clear":
                sheet.setPrintAreas(())
                applied.append("print area cleared")
            else:
                spec = convert.parse_range(
                    convert.split_sheet(str(area))[1], used_range(sheet))
                sheet.setPrintAreas((make_struct(
                    "com.sun.star.table.CellRangeAddress",
                    Sheet=sheet.RangeAddress.Sheet,
                    StartColumn=spec.start_col, StartRow=spec.start_row,
                    EndColumn=spec.end_col, EndRow=spec.end_row),))
                applied.append("print area %s" % spec.name())

        if args.get("orientation"):
            style.IsLandscape = args["orientation"].lower() == "landscape"
            applied.append(args["orientation"].lower())

        if args.get("fit_to_pages_wide") is not None or args.get("fit_to_pages_tall") is not None:
            style.ScaleToPagesX = int(args.get("fit_to_pages_wide") or 0)
            style.ScaleToPagesY = int(args.get("fit_to_pages_tall") or 0)
            applied.append("fit to %s x %s page(s)" % (
                style.ScaleToPagesX or "any", style.ScaleToPagesY or "any"))
        elif args.get("scale_percent"):
            style.PageScale = int(args["scale_percent"])
            applied.append("scale %d%%" % style.PageScale)

        if args.get("repeat_rows"):
            text = str(args["repeat_rows"]).strip()
            first, last = (text.split(":", 1) + [text])[:2] if ":" in text else (text, text)
            sheet.setTitleRows(make_struct(
                "com.sun.star.table.CellRangeAddress",
                Sheet=sheet.RangeAddress.Sheet, StartColumn=0, EndColumn=0,
                StartRow=int(first) - 1, EndRow=int(last) - 1))
            applied.append("repeat row(s) %s" % text)

        if args.get("repeat_columns"):
            text = str(args["repeat_columns"]).strip()
            first, last = text.split(":", 1) if ":" in text else (text, text)
            sheet.setTitleColumns(make_struct(
                "com.sun.star.table.CellRangeAddress",
                Sheet=sheet.RangeAddress.Sheet, StartRow=0, EndRow=0,
                StartColumn=convert.col_to_index(first),
                EndColumn=convert.col_to_index(last)))
            applied.append("repeat column(s) %s" % text)

        if args.get("margin_mm") is not None:
            edge = int(float(args["margin_mm"]) * MM100)
            for side in ("LeftMargin", "RightMargin", "TopMargin", "BottomMargin"):
                setattr(style, side, edge)
            applied.append("margins %smm" % args["margin_mm"])

        for key, flag, content_property in (
            ("header_text", "HeaderIsOn", "RightPageHeaderContent"),
            ("footer_text", "FooterIsOn", "RightPageFooterContent"),
        ):
            if args.get(key) is None:
                continue
            text = str(args[key])
            setattr(style, flag, bool(text))
            if text:
                content = getattr(style, content_property)
                content.CenterText.setString(text)
                content.LeftText.setString("")
                content.RightText.setString("")
                setattr(style, content_property, content)
            applied.append("%s %r" % (key.split("_")[0], text))

        if "print_gridlines" in args:
            style.PrintGrid = bool_arg(args, "print_gridlines")
            applied.append("gridlines=%s" % style.PrintGrid)
        if "center_horizontally" in args:
            style.CenterHorizontally = bool_arg(args, "center_horizontally")
            applied.append("centred horizontally=%s" % style.CenterHorizontally)
        if "center_vertically" in args:
            style.CenterVertically = bool_arg(args, "center_vertically")
            applied.append("centred vertically=%s" % style.CenterVertically)

    if not applied:
        return (
            "No page settings were given. Sheet '%s' currently prints %s, "
            "%s, scale %d%%." % (
                sheet.Name, "landscape" if style.IsLandscape else "portrait",
                "with gridlines" if style.PrintGrid else "without gridlines",
                style.PageScale)
        )
    return "Page setup for '%s': %s. This also governs PDF export." % (
        sheet.Name, ", ".join(applied))


@tool(
    "manage_names",
    "List, create or delete named ranges, so formulas can say =SUM(Prices) instead "
    "of =SUM(B2:B40).",
    properties={
        "document": DOCUMENT,
        "sheet": SHEET,
        "operation": enum("Default list.", ["list", "add", "delete"]),
        "name": string("The name to create or delete."),
        "range": string("Range the name refers to, e.g. 'B2:B40'."),
    },
    title="Named ranges",
)
def manage_names(args):
    operation = (args.get("operation") or "list").lower()

    if operation == "list":
        conn, doc = doc_only(args)
        names = doc.NamedRanges
        if not names.Count:
            return "This document has no named ranges."
        lines = []
        for name in names.ElementNames:
            lines.append("%s\t%s" % (name, names.getByName(name).getContent()))
        return "Named ranges:\n" + "\n".join(lines)

    if operation == "delete":
        conn, doc = doc_only(args)
        name = args.get("name")
        if not name:
            raise CalcError("'name' is required to delete a named range.")
        names = doc.NamedRanges
        if not names.hasByName(name):
            raise CalcError(
                "No named range %r. Present: %s"
                % (name, ", ".join(names.ElementNames) or "none"))
        with undo_step(doc, "Claude: delete name %s" % name):
            names.removeByName(name)
        return "Deleted named range '%s'." % name

    conn, doc, sheet, spec = target(args, require_range=True)
    name = args.get("name")
    if not name:
        raise CalcError("'name' is required to create a named range.")
    names = doc.NamedRanges
    if names.hasByName(name):
        raise CalcError("A named range called %r already exists." % name)

    with undo_step(doc, "Claude: add name %s" % name):
        names.addNewByName(
            name, _absolute_ref(sheet, spec),
            _cell_address(sheet, spec.start_col, spec.start_row), 0)

    return "Named range '%s' now refers to %s.%s; use it in formulas as %s." % (
        name, sheet.Name, spec.name(), name)


@tool(
    "manage_comments",
    "Add, read or delete cell comments (the yellow sticky notes).",
    properties={
        "document": DOCUMENT,
        "sheet": SHEET,
        "operation": enum("Default list.", ["list", "add", "delete"]),
        "cell": string("Cell to attach to or remove from, e.g. 'B4'."),
        "text": string("Comment body, for add."),
    },
    title="Cell comments",
)
def manage_comments(args):
    conn, doc, sheet = doc_and_sheet(args)
    notes = sheet.Annotations
    operation = (args.get("operation") or "list").lower()

    if operation == "list":
        if not notes.Count:
            return "No comments on sheet '%s'." % sheet.Name
        lines = []
        for index in range(notes.Count):
            note = notes.getByIndex(index)
            position = note.Position
            lines.append("%s\t%s" % (
                convert.cell_name(position.Column, position.Row),
                note.getString().replace("\n", " / ")))
        return "Comments on '%s':\n" % sheet.Name + "\n".join(lines)

    if not args.get("cell"):
        raise CalcError("'cell' is required to %s a comment." % operation)
    spec = convert.parse_range(
        convert.split_sheet(str(args["cell"]))[1], used_range(sheet))

    if operation == "add":
        if args.get("text") is None:
            raise CalcError("'text' is required to add a comment.")
        with undo_step(doc, "Claude: comment %s" % spec.name()):
            notes.insertNew(
                _cell_address(sheet, spec.start_col, spec.start_row), str(args["text"]))
        return "Added a comment to %s.%s." % (sheet.Name, spec.name())

    for index in range(notes.Count):
        position = notes.getByIndex(index).Position
        if position.Column == spec.start_col and position.Row == spec.start_row:
            with undo_step(doc, "Claude: delete comment %s" % spec.name()):
                notes.removeByIndex(index)
            return "Deleted the comment on %s.%s." % (sheet.Name, spec.name())
    return "There is no comment on %s.%s to delete." % (sheet.Name, spec.name())


@tool(
    "protect_sheet",
    "Protect a sheet so its cells cannot be edited, or unprotect it. Cells are "
    "locked by default, so the usual pattern is to unlock the cells people should "
    "fill in, then protect the sheet.",
    properties={
        "document": DOCUMENT,
        "sheet": SHEET,
        "operation": enum(
            "What to do.",
            ["protect", "unprotect", "unlock_cells", "lock_cells", "status"]),
        "range": string("Range to lock or unlock, e.g. 'B2:B20'."),
        "password": string(
            "Optional password. Without one the sheet can be unprotected from the "
            "menu, which is usually what you want for a worksheet."),
    },
    required=["operation"],
    title="Protect sheet",
)
def protect_sheet(args):
    conn, doc, sheet = doc_and_sheet(args)
    operation = args["operation"]
    password = args.get("password") or ""

    if operation == "status":
        return "Sheet '%s' is %s." % (
            sheet.Name, "protected" if sheet.isProtected() else "not protected")

    if operation == "protect":
        if sheet.isProtected():
            return "Sheet '%s' is already protected." % sheet.Name
        with undo_step(doc, "Claude: protect %s" % sheet.Name):
            sheet.protect(password)
        return "Protected sheet '%s'%s. Locked cells can no longer be edited." % (
            sheet.Name, " with a password" if password else "")

    if operation == "unprotect":
        if not sheet.isProtected():
            return "Sheet '%s' is not protected." % sheet.Name
        with undo_step(doc, "Claude: unprotect %s" % sheet.Name):
            sheet.unprotect(password)
        if sheet.isProtected():
            raise CalcError(
                "Could not unprotect sheet '%s' -- the password did not match."
                % sheet.Name)
        return "Unprotected sheet '%s'." % sheet.Name

    if not args.get("range"):
        raise CalcError("'range' is required to lock or unlock cells.")
    conn, doc, sheet, spec = target(args, require_range=True)
    rng = cell_range(sheet, spec)
    locked = operation == "lock_cells"
    with undo_step(doc, "Claude: %s %s" % (operation, spec.name())):
        protection = rng.CellProtection
        protection.IsLocked = locked
        rng.CellProtection = protection
    return "%s %s.%s. %s" % (
        "Locked" if locked else "Unlocked", sheet.Name, spec.name(),
        "This takes effect once the sheet is protected."
        if locked else "These cells stay editable when the sheet is protected.",
    )

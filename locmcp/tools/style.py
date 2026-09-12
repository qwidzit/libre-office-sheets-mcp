"""Formatting, column/row sizing, freezing, charts, and a raw UNO escape hatch."""

import os

from .. import convert
from ..bridge import (
    CalcError, cell_range, make_struct, undo_step, uno_module, used_range,
)
from ..registry import DOCUMENT, SHEET, boolean, enum, number, string, tool
from .base import bool_arg, doc_and_sheet, target

MM100 = 100.0  # UNO measures in 1/100 mm


def _enum(type_name, value):
    return uno_module().Enum(type_name, value)


def _border_line(color, width_mm100):
    return make_struct(
        "com.sun.star.table.BorderLine2",
        Color=color,
        LineWidth=width_mm100,
        OuterLineWidth=width_mm100,
        InnerLineWidth=0,
        LineDistance=0,
        LineStyle=0,  # com.sun.star.table.BorderLineStyle.SOLID
    )


@tool(
    "format_range",
    "Apply visual formatting to a range: font, colours, alignment, wrapping, number "
    "format, borders and merging. Only the options you pass are changed.",
    properties={
        "document": DOCUMENT,
        "sheet": SHEET,
        "range": string("Range to format, e.g. 'A1:D1'."),
        "style": string(
            "Named cell style to apply first, e.g. 'Heading 1', 'Good', 'Bad', "
            "'Neutral', 'Accent 1', 'Result', 'Default'. Anything else you pass is "
            "applied on top of it."
        ),
        "bold": boolean("Bold on or off."),
        "italic": boolean("Italic on or off."),
        "underline": boolean("Underline on or off."),
        "font_size": number("Point size, e.g. 12."),
        "font_name": string("Font family, e.g. 'Calibri'."),
        "text_color": string("Font colour as '#RRGGBB' or a name like 'red'."),
        "background_color": string(
            "Cell fill as '#RRGGBB', a name, or 'none' to clear it."
        ),
        "align": enum("Horizontal alignment.", ["left", "center", "right", "default"]),
        "vertical_align": enum("Vertical alignment.", ["top", "middle", "bottom", "default"]),
        "wrap": boolean("Wrap text within the cell."),
        "number_format": string(
            "Calc format code, e.g. '0.00', '#,##0', '0.0%', 'YYYY-MM-DD', "
            "'\"$\"#,##0.00'."
        ),
        "borders": enum(
            "Border placement. 'all' also draws the interior grid.",
            ["none", "outer", "all"],
        ),
        "border_color": string("Border colour as '#RRGGBB' or a name. Default black."),
        "merge": boolean("Merge the range into one cell, or unmerge it when false."),
    },
    required=["range"],
    title="Format range",
)
def format_range(args):
    conn, doc, sheet, spec = target(args, require_range=True)
    rng = cell_range(sheet, spec)
    applied = []

    with undo_step(doc, "Claude: format %s.%s" % (sheet.Name, spec.name())):
        if args.get("style"):
            available = doc.StyleFamilies.getByName("CellStyles")
            if not available.hasByName(args["style"]):
                raise CalcError(
                    "No cell style named %r. Available: %s"
                    % (args["style"], ", ".join(sorted(available.ElementNames)))
                )
            # A style resets the cell's direct formatting, so it goes on first and
            # anything else in this call layers over it.
            rng.CellStyle = args["style"]
            applied.append("style=%s" % args["style"])
        if "bold" in args:
            rng.CharWeight = 150.0 if bool_arg(args, "bold") else 100.0
            applied.append("bold=%s" % bool_arg(args, "bold"))
        if "italic" in args:
            rng.CharPosture = _enum(
                "com.sun.star.awt.FontSlant", "ITALIC" if bool_arg(args, "italic") else "NONE"
            )
            applied.append("italic=%s" % bool_arg(args, "italic"))
        if "underline" in args:
            rng.CharUnderline = 1 if bool_arg(args, "underline") else 0
            applied.append("underline=%s" % bool_arg(args, "underline"))
        if args.get("font_size"):
            rng.CharHeight = float(args["font_size"])
            applied.append("size=%s" % args["font_size"])
        if args.get("font_name"):
            rng.CharFontName = str(args["font_name"])
            applied.append("font=%s" % args["font_name"])
        if args.get("text_color"):
            rng.CharColor = convert.parse_color(args["text_color"])
            applied.append("text=%s" % args["text_color"])
        if args.get("background_color"):
            colour = convert.parse_color(args["background_color"])
            rng.CellBackColor = colour
            rng.IsCellBackgroundTransparent = colour == -1
            applied.append("fill=%s" % args["background_color"])
        if args.get("align"):
            mapping = {
                "left": "LEFT", "center": "CENTER", "right": "RIGHT", "default": "STANDARD",
            }
            rng.HoriJustify = _enum(
                "com.sun.star.table.CellHoriJustify", mapping[args["align"]]
            )
            applied.append("align=%s" % args["align"])
        if args.get("vertical_align"):
            mapping = {
                "top": "TOP", "middle": "CENTER", "bottom": "BOTTOM", "default": "STANDARD",
            }
            rng.VertJustify = _enum(
                "com.sun.star.table.CellVertJustify", mapping[args["vertical_align"]]
            )
            applied.append("valign=%s" % args["vertical_align"])
        if "wrap" in args:
            rng.IsTextWrapped = bool_arg(args, "wrap")
            applied.append("wrap=%s" % bool_arg(args, "wrap"))

        if args.get("number_format"):
            code = str(args["number_format"])
            formats = doc.getNumberFormats()
            locale = make_struct("com.sun.star.lang.Locale")
            key = formats.queryKey(code, locale, False)
            if key == -1:
                try:
                    key = formats.addNew(code, locale)
                except Exception as exc:
                    raise CalcError("LibreOffice rejected the number format %r (%s)." % (code, exc))
            rng.NumberFormat = key
            applied.append("number_format=%s" % code)

        if args.get("borders"):
            style = args["borders"]
            colour = convert.parse_color(args.get("border_color") or "black")
            if style == "none":
                blank = make_struct("com.sun.star.table.BorderLine2", LineWidth=0, LineStyle=0)
                line, inner = blank, blank
            else:
                line = _border_line(colour, 26)  # ~0.26mm, Calc's thin line
                inner = line if style == "all" else make_struct(
                    "com.sun.star.table.BorderLine2", LineWidth=0, LineStyle=0
                )
            border = make_struct(
                "com.sun.star.table.TableBorder2",
                TopLine=line, IsTopLineValid=True,
                BottomLine=line, IsBottomLineValid=True,
                LeftLine=line, IsLeftLineValid=True,
                RightLine=line, IsRightLineValid=True,
                HorizontalLine=inner, IsHorizontalLineValid=True,
                VerticalLine=inner, IsVerticalLineValid=True,
            )
            rng.TableBorder2 = border
            applied.append("borders=%s" % style)

        if "merge" in args:
            rng.merge(bool_arg(args, "merge"))
            applied.append("merge=%s" % bool_arg(args, "merge"))

    if not applied:
        return "No formatting options were given, so %s.%s is unchanged." % (
            sheet.Name, spec.name()
        )
    return "Formatted %s.%s (%d cells): %s" % (
        sheet.Name, spec.name(), spec.cells, ", ".join(applied)
    )


@tool(
    "size_cells",
    "Set column widths and row heights, fit them to their contents, or hide and show "
    "them.",
    properties={
        "document": DOCUMENT,
        "sheet": SHEET,
        "columns": string("Column range, e.g. 'B' or 'A:F'."),
        "rows": string("Row range, e.g. '1' or '1:10'."),
        "width_mm": number("Column width in millimetres."),
        "height_mm": number("Row height in millimetres."),
        "optimal": boolean("Fit to contents instead of using an explicit size."),
        "visible": boolean("Show (true) or hide (false)."),
    },
    title="Size rows and columns",
)
def size_cells(args):
    conn, doc, sheet = doc_and_sheet(args)
    changes = []

    def slice_of(container, first, last):
        for index in range(first, last + 1):
            yield container.getByIndex(index)

    with undo_step(doc, "Claude: resize %s" % sheet.Name):
        if args.get("columns"):
            text = str(args["columns"]).strip()
            if ":" in text:
                left, right = text.split(":", 1)
            else:
                left = right = text
            first, last = convert.col_to_index(left), convert.col_to_index(right)
            first, last = min(first, last), max(first, last)
            for entry in slice_of(sheet.Columns, first, last):
                if bool_arg(args, "optimal"):
                    entry.OptimalWidth = True
                elif args.get("width_mm"):
                    entry.Width = int(float(args["width_mm"]) * MM100)
                if "visible" in args:
                    entry.IsVisible = bool_arg(args, "visible")
            changes.append(
                "columns %s:%s" % (convert.index_to_col(first), convert.index_to_col(last))
            )

        if args.get("rows"):
            text = str(args["rows"]).strip()
            if ":" in text:
                left, right = text.split(":", 1)
            else:
                left = right = text
            first, last = int(left) - 1, int(right) - 1
            first, last = min(first, last), max(first, last)
            for entry in slice_of(sheet.Rows, first, last):
                if bool_arg(args, "optimal"):
                    entry.OptimalHeight = True
                elif args.get("height_mm"):
                    entry.Height = int(float(args["height_mm"]) * MM100)
                if "visible" in args:
                    entry.IsVisible = bool_arg(args, "visible")
            changes.append("rows %d:%d" % (first + 1, last + 1))

    if not changes:
        raise CalcError("Pass 'columns' and/or 'rows' to say what should be resized.")
    what = []
    if bool_arg(args, "optimal"):
        what.append("fitted to contents")
    if args.get("width_mm"):
        what.append("width %smm" % args["width_mm"])
    if args.get("height_mm"):
        what.append("height %smm" % args["height_mm"])
    if "visible" in args:
        what.append("visible=%s" % bool_arg(args, "visible"))
    return "Adjusted %s on sheet '%s': %s." % (
        " and ".join(changes), sheet.Name, ", ".join(what) or "no change",
    )


@tool(
    "freeze_panes",
    "Freeze the top rows and/or left columns of the sheet's window so headers stay "
    "visible while scrolling. Requires a visible LibreOffice window.",
    properties={
        "document": DOCUMENT,
        "sheet": SHEET,
        "at": string(
            "The first unfrozen cell. 'B2' freezes row 1 and column A; 'A2' freezes "
            "row 1 only; 'A1' unfreezes everything."
        ),
    },
    required=["at"],
    title="Freeze panes",
)
def freeze_panes(args):
    conn, doc, sheet = doc_and_sheet(args)
    spec = convert.parse_range(str(args["at"]), used_range(sheet))
    controller = doc.CurrentController
    controller.setActiveSheet(sheet)
    controller.freezeAtPosition(spec.start_col, spec.start_row)
    if spec.start_col == 0 and spec.start_row == 0:
        return "Unfroze all panes on sheet '%s'." % sheet.Name
    return "Froze %d column(s) and %d row(s) on sheet '%s'." % (
        spec.start_col, spec.start_row, sheet.Name
    )


CHART_TYPES = {
    "column": ("com.sun.star.chart.BarDiagram", False),
    "bar": ("com.sun.star.chart.BarDiagram", True),
    "line": ("com.sun.star.chart.LineDiagram", None),
    "area": ("com.sun.star.chart.AreaDiagram", None),
    "pie": ("com.sun.star.chart.PieDiagram", None),
    "donut": ("com.sun.star.chart.DonutDiagram", None),
    "scatter": ("com.sun.star.chart.XYDiagram", None),
    "net": ("com.sun.star.chart.NetDiagram", None),
}


@tool(
    "create_chart",
    "Create a chart from a data range and place it on the sheet.",
    properties={
        "document": DOCUMENT,
        "sheet": SHEET,
        "range": string("Data range including headers, e.g. 'A1:C10'."),
        "chart_type": enum("Chart style. Default column.", sorted(CHART_TYPES)),
        "title": string("Chart title."),
        "name": string("Internal chart name. Defaults to 'Chart N'."),
        "anchor": string("Top-left cell to place the chart at. Default 'F2'."),
        "width_mm": number("Chart width in millimetres. Default 140."),
        "height_mm": number("Chart height in millimetres. Default 85."),
        "first_row_as_labels": boolean("Use the first row as series names. Default true."),
        "first_column_as_labels": boolean("Use the first column as categories. Default true."),
        "x_axis_title": string("Label for the horizontal axis."),
        "y_axis_title": string("Label for the vertical axis."),
        "legend": enum(
            "Where to put the legend, or 'none' to hide it. Default right.",
            ["none", "left", "right", "top", "bottom"]),
        "data_labels": boolean("Print each point's value on the chart. Default false."),
        "y_gridlines": boolean("Horizontal gridlines behind the plot. Default true."),
    },
    required=["range"],
    title="Create chart",
)
def create_chart(args):
    conn, doc, sheet, spec = target(args, require_range=True)
    charts = sheet.Charts
    name = args.get("name") or "Chart %d" % (charts.Count + 1)
    if charts.hasByName(name):
        raise CalcError("A chart named %r already exists on this sheet." % name)

    anchor_spec = convert.parse_range(str(args.get("anchor") or "F2"), used_range(sheet))
    origin = sheet.getCellByPosition(anchor_spec.start_col, anchor_spec.start_row).Position
    rect = make_struct(
        "com.sun.star.awt.Rectangle",
        X=origin.X,
        Y=origin.Y,
        Width=int(float(args.get("width_mm") or 140) * MM100),
        Height=int(float(args.get("height_mm") or 85) * MM100),
    )
    address = make_struct(
        "com.sun.star.table.CellRangeAddress",
        Sheet=sheet.RangeAddress.Sheet,
        StartColumn=spec.start_col,
        StartRow=spec.start_row,
        EndColumn=spec.end_col,
        EndRow=spec.end_row,
    )

    kind = (args.get("chart_type") or "column").lower()
    if kind not in CHART_TYPES:
        raise CalcError("Unknown chart_type %r. Choose from: %s" % (kind, ", ".join(sorted(CHART_TYPES))))
    service, horizontal = CHART_TYPES[kind]

    with undo_step(doc, "Claude: create chart %s" % name):
        charts.addNewByName(
            name,
            rect,
            (address,),
            bool_arg(args, "first_row_as_labels", True),
            bool_arg(args, "first_column_as_labels", True),
        )
        chart_doc = charts.getByName(name).EmbeddedObject
        diagram = chart_doc.createInstance(service)
        chart_doc.setDiagram(diagram)
        if horizontal is not None:
            chart_doc.Diagram.Vertical = horizontal
        if args.get("title"):
            chart_doc.HasMainTitle = True
            chart_doc.Title.String = str(args["title"])

        diagram = chart_doc.Diagram
        # Pie and donut charts have no axes, so these are best-effort.
        for key, has_flag, title_property in (
            ("x_axis_title", "HasXAxisTitle", "XAxisTitle"),
            ("y_axis_title", "HasYAxisTitle", "YAxisTitle"),
        ):
            if not args.get(key):
                continue
            try:
                setattr(diagram, has_flag, True)
                getattr(diagram, title_property).String = str(args[key])
            except Exception:
                pass

        placement = (args.get("legend") or "right").lower()
        try:
            chart_doc.HasLegend = placement != "none"
            if placement != "none":
                chart_doc.Legend.Alignment = _enum(
                    "com.sun.star.chart.ChartLegendPosition", placement.upper())
        except Exception:
            pass

        if bool_arg(args, "data_labels"):
            try:
                # com.sun.star.chart.ChartDataCaption.VALUE
                diagram.DataCaption = 1
            except Exception:
                pass

        if "y_gridlines" in args:
            try:
                diagram.HasYAxisGrid = bool_arg(args, "y_gridlines")
            except Exception:
                pass

    return "Created a %s chart named '%s' from %s.%s, anchored at %s." % (
        kind, name, sheet.Name, spec.name(), anchor_spec.name()
    )


EXEC_ENABLED = os.environ.get("LOCALC_MCP_ENABLE_EXEC", "0") in ("1", "true", "yes", "on")


@tool(
    "run_uno_script",
    "Escape hatch: run a short Python snippet against the live document using the UNO "
    "API, for anything the other tools do not cover. Disabled unless the environment "
    "variable LOCALC_MCP_ENABLE_EXEC=1 is set. In scope: doc, sheet, sheets, desktop, "
    "ctx, smgr, uno, and a helper struct(name, **fields). Assign to `result` or return "
    "the last expression's value.",
    properties={
        "document": DOCUMENT,
        "sheet": SHEET,
        "code": string("Python source to execute."),
    },
    required=["code"],
    title="Run UNO script",
)
def run_uno_script(args):
    if not EXEC_ENABLED:
        raise CalcError(
            "run_uno_script is disabled. Set LOCALC_MCP_ENABLE_EXEC=1 in the server's "
            "environment to enable it; it executes arbitrary Python against your "
            "documents, so leave it off unless you need it."
        )
    conn, doc, sheet = doc_and_sheet(args)
    scope = {
        "doc": doc,
        "sheet": sheet,
        "sheets": doc.Sheets,
        "desktop": conn.desktop,
        "ctx": conn.ctx,
        "smgr": conn.smgr,
        "uno": uno_module(),
        "struct": make_struct,
        "result": None,
    }
    with undo_step(doc, "Claude: run_uno_script"):
        exec(compile(str(args["code"]), "<run_uno_script>", "exec"), scope)
    result = scope.get("result")
    return "Script completed. result = %r" % (result,) if result is not None else "Script completed."

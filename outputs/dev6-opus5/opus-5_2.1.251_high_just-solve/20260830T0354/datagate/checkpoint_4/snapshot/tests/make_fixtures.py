"""Regenerate the binary spreadsheet fixtures.

    ./venv/bin/python tests/make_fixtures.py

The generated files are committed, so this only needs re-running when the
fixture data itself changes.
"""
import datetime
import os
import zipfile

import openpyxl
import xlwt

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")

# the same table as fixtures/basic.csv, so both formats must ingest alike
BASIC = [
    ["name", "age", "score", "start"],
    ["Alice", 30, 91.5, "08:30"],
    ["Bob", 25, 78.25, "9:15"],
    ["Carol", 41, 88, "12:00"],
]


# typed cells: dates, times, booleans and whole floats must land on the same
# values whichever container they arrive in
TYPED = [
    ["when", "at", "flag", "n"],
    [datetime.date(2024, 3, 5), datetime.time(8, 30), True, 42.0],
    [datetime.datetime(2024, 3, 5, 14, 2, 3), datetime.time(9, 15, 7), False, 1.25],
]


def write_xlsx(path, sheets, trailing_blanks=False):
    book = openpyxl.Workbook()
    first = True
    for title, grid in sheets:
        sheet = book.active if first else book.create_sheet()
        sheet.title = title
        first = False
        for row in grid:
            sheet.append(row)
        if trailing_blanks:
            # a stray formatted cell well past the data, as real files have
            sheet.cell(row=len(grid) + 3, column=len(grid[0]) + 2).value = None
    book.save(path)


def write_xls(path, sheets):
    book = xlwt.Workbook()
    for title, grid in sheets:
        sheet = book.add_sheet(title)
        for r, row in enumerate(grid):
            for c, value in enumerate(row):
                sheet.write(r, c, value)
    book.save(path)


def write_typed_xls(path):
    """xlwt needs an explicit number format for a cell to read back as a date."""
    book = xlwt.Workbook()
    sheet = book.add_sheet("Data")
    styles = {
        0: xlwt.easyxf(num_format_str="YYYY-MM-DD HH:MM:SS"),
        1: xlwt.easyxf(num_format_str="HH:MM:SS"),
    }
    for r, row in enumerate(TYPED):
        for c, value in enumerate(row):
            if r and c in styles:
                sheet.write(r, c, value, styles[c])
            else:
                sheet.write(r, c, value)
    book.save(path)


def main():
    write_xlsx(os.path.join(FIXTURES, "basic.xlsx"), [("Data", BASIC), ("Ignored", [["z"], [1]])])
    write_xls(os.path.join(FIXTURES, "basic.xls"), [("Data", BASIC), ("Ignored", [["z"], [1]])])

    write_xlsx(os.path.join(FIXTURES, "typed.xlsx"), [("Data", TYPED)])
    write_typed_xls(os.path.join(FIXTURES, "typed.xls"))

    # header row but no data row -> non-tabular
    write_xlsx(os.path.join(FIXTURES, "headeronly.xlsx"), [("Data", [["a", "b", "c"]])])
    write_xls(os.path.join(FIXTURES, "headeronly.xls"), [("Data", [["a", "b", "c"]])])

    # completely empty first sheet -> non-tabular
    book = openpyxl.Workbook()
    book.active.title = "Blank"
    book.create_sheet("HasData").append(["a", "b"])
    book.save(os.path.join(FIXTURES, "emptysheet.xlsx"))

    # a zip that is not a spreadsheet -> unrecognized format
    with zipfile.ZipFile(os.path.join(FIXTURES, "notsheet.zip"), "w") as archive:
        archive.writestr("readme.txt", "not a spreadsheet\n")

    print("wrote spreadsheet fixtures to %s" % FIXTURES)


if __name__ == "__main__":
    main()

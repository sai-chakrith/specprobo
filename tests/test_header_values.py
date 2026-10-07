from openpyxl import Workbook

from specprobe.ingest.parsers import parse_excel


def test_spreadsheet_oem_title_and_literal_name_are_not_headers(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Vendor values"
    sheet.append(["OEM"])
    sheet.append(["DID", "Byte length", "Name", "Encoding"])
    sheet.append(["0x2231", 2, "Name", "bytes"])
    sheet.append(["0x2232", 2, "Value", "bytes"])
    path = tmp_path / "headers.xlsx"
    workbook.save(path)
    _, rows = parse_excel(path, "doc")
    assert len(rows) == 2
    assert rows[0].values["DID"] == "0x2231" and rows[0].row == 3
    assert rows[0].values["Name"] == "Name"

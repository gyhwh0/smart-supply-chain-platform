from datetime import date
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


DIMENSION_LABELS = {
    "category": "商品分类",
    "product": "商品",
    "customer": "客户",
    "supplier": "供应商",
    "creator": "订单员/制单人",
    "sorter": "分拣员",
    "delivery": "配送员",
}


def _apply_title(sheet, title: str, subtitle: str, column_count: int):
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=column_count)
    title_cell = sheet.cell(1, 1, title)
    title_cell.font = Font(size=18, bold=True, color="FFFFFF")
    title_cell.fill = PatternFill("solid", fgColor="2F6FB2")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    sheet.row_dimensions[1].height = 34
    sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=column_count)
    subtitle_cell = sheet.cell(2, 1, subtitle)
    subtitle_cell.font = Font(color="526173")
    subtitle_cell.alignment = Alignment(horizontal="left", vertical="center")
    sheet.row_dimensions[2].height = 24


def _build_supplier_grouped_sheet(sheet, summary: dict, report_type: str):
    """Render each supplier as a paper-like purchase block with product rows."""
    sheet.title = "供应商采购汇总"
    cjk_font = "Arial Unicode MS"
    headers = ["菜名", "总数量", "订单总数"]
    thin = Side(style="thin", color="000000")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    report_date = summary.get("date_to") or summary.get("date_from") or date.today()
    if hasattr(report_date, "isoformat"):
        report_date = report_date.isoformat()
    suppliers = summary.get("rows", [])
    row_index = 1

    for supplier_index, supplier in enumerate(suppliers, 1):
        sheet.merge_cells(start_row=row_index, start_column=1, end_row=row_index, end_column=3)
        title = sheet.cell(
            row_index,
            1,
            f"（{supplier['name']}）采购单  日期：{report_date}  共{len(suppliers)}页  第{supplier_index}页",
        )
        title.font = Font(name=cjk_font, size=12, bold=True, color="000000")
        title.alignment = Alignment(horizontal="center", vertical="center")
        sheet.row_dimensions[row_index].height = 25
        row_index += 1

        for column, value in enumerate(headers, 1):
            cell = sheet.cell(row_index, column, value)
            cell.font = Font(name=cjk_font, size=10, color="000000")
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = border
        sheet.row_dimensions[row_index].height = 21
        row_index += 1

        for product in supplier.get("product_details", []):
            product_values = [
                product.get("name", ""),
                product.get("quantity_display", ""),
                product.get("order_breakdown", "") or "暂无客户订购明细",
            ]
            for column, value in enumerate(product_values, 1):
                cell = sheet.cell(row_index, column, value)
                cell.font = Font(name=cjk_font, size=10, color="000000")
                cell.border = border
                cell.alignment = Alignment(
                    horizontal="left" if column in {1, 3} else "center",
                    vertical="center",
                    wrap_text=True,
                )
            breakdown_length = len(product_values[2])
            sheet.row_dimensions[row_index].height = max(21, 18 * ((breakdown_length // 45) + 1))
            row_index += 1

        if not supplier.get("product_details"):
            sheet.merge_cells(start_row=row_index, start_column=1, end_row=row_index, end_column=3)
            empty_cell = sheet.cell(row_index, 1, "暂无对应商品明细")
            empty_cell.font = Font(name=cjk_font, size=10, color="666666")
            empty_cell.alignment = Alignment(horizontal="center", vertical="center")
            empty_cell.border = border
            row_index += 1
        row_index += 1

    widths = [30, 15, 72]
    for index, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.sheet_view.showGridLines = False
    sheet.page_setup.orientation = "portrait"
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.print_options.horizontalCentered = True
    if row_index > 1:
        sheet.print_area = f"A1:C{row_index - 1}"


def build_summary_excel(summary: dict) -> BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    dimension = summary.get("dimension", "product")
    dimension_label = DIMENSION_LABELS.get(dimension, "汇总对象")
    report_type = summary.get("report_type", "normal")
    rows = summary.get("rows", [])
    if dimension == "supplier":
        _build_supplier_grouped_sheet(sheet, summary, report_type)
        stream = BytesIO()
        workbook.save(stream)
        stream.seek(0)
        return stream
    if report_type == "horizontal":
        sheet.title = "横排销售汇总"
        last_column = max(len(rows) + 1, 2)
        sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_column)
        sheet.cell(1, 1, f"横排销售汇总（按{dimension_label}）")
        sheet.cell(1, 1).font = Font(size=18, bold=True, color="FFFFFF")
        sheet.cell(1, 1).fill = PatternFill("solid", fgColor="2F6FB2")
        sheet.cell(1, 1).alignment = Alignment(horizontal="center")
        sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=last_column)
        sheet.cell(2, 1, f"统计区间：{summary.get('date_from') or '不限'} 至 {summary.get('date_to') or '不限'}")
        labels = ["汇总项目", "销售金额", "销售单数", "销售数量"]
        for row_index, label in enumerate(labels, 4):
            cell = sheet.cell(row_index, 1, label)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="4D88C7")
        for column, row in enumerate(rows, 2):
            sheet.cell(4, column, row["name"]).font = Font(bold=True)
            sheet.cell(5, column, row["sales_amount"]).number_format = '¥0.00'
            sheet.cell(6, column, row["order_count"])
            sheet.cell(7, column, row["quantity_display"])
            sheet.column_dimensions[get_column_letter(column)].width = 20
        sheet.column_dimensions["A"].width = 16
        stream = BytesIO()
        workbook.save(stream)
        stream.seek(0)
        return stream
    if report_type == "quantity":
        sheet.title = "数量汇总"
        column_count = 4
        sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=column_count)
        sheet["A1"] = f"销售数量汇总（按{dimension_label}）"
        sheet["A1"].font = Font(size=18, bold=True, color="FFFFFF")
        sheet["A1"].fill = PatternFill("solid", fgColor="2F6FB2")
        sheet["A1"].alignment = Alignment(horizontal="center")
        sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=column_count)
        sheet["A2"] = f"统计区间：{summary.get('date_from') or '不限'} 至 {summary.get('date_to') or '不限'}"
        headers = [dimension_label, "销售数量", "销售单数", "销售金额"]
        for column, value in enumerate(headers, 1):
            cell = sheet.cell(4, column, value)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="4D88C7")
        for row_index, row in enumerate(rows, 5):
            values = [row["name"], row["quantity_display"], row["order_count"], row["sales_amount"]]
            for column, value in enumerate(values, 1):
                sheet.cell(row_index, column, value)
            sheet.cell(row_index, column_count).number_format = '¥0.00'
        widths = [28, 26, 14, 18]
        for index, width in enumerate(widths, 1):
            sheet.column_dimensions[get_column_letter(index)].width = width
        stream = BytesIO()
        workbook.save(stream)
        stream.seek(0)
        return stream
    sheet.title = "销售汇总"
    column_count = 5
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=column_count)
    sheet["A1"] = f"销售汇总报表（按{dimension_label}）"
    sheet["A1"].font = Font(size=18, bold=True, color="FFFFFF")
    sheet["A1"].fill = PatternFill("solid", fgColor="2F6FB2")
    sheet["A1"].alignment = Alignment(horizontal="center", vertical="center")
    sheet.row_dimensions[1].height = 34
    sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=column_count)
    sheet["A2"] = f"统计区间：{summary.get('date_from') or '不限'} 至 {summary.get('date_to') or '不限'}"
    headers = [dimension_label, "销售单数", "明细行数", "销售数量", "销售金额"]
    for column, value in enumerate(headers, 1):
        cell = sheet.cell(4, column, value)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="4D88C7")
        cell.alignment = Alignment(horizontal="center")
    thin = Side(style="thin", color="D9E0E8")
    for row_index, row in enumerate(summary.get("rows", []), 5):
        values = [row["name"], row["order_count"], row["item_count"], row["quantity_display"], row["sales_amount"]]
        for column, value in enumerate(values, 1):
            cell = sheet.cell(row_index, column, value)
            cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)
            cell.alignment = Alignment(horizontal="center", vertical="center")
        sheet.cell(row_index, column_count).number_format = '¥0.00'
    total_row = 5 + len(summary.get("rows", []))
    sheet.merge_cells(start_row=total_row, start_column=1, end_row=total_row, end_column=column_count - 1)
    sheet.cell(total_row, 1, "销售总额").font = Font(bold=True)
    sheet.cell(total_row, column_count, summary.get("total_amount", 0)).number_format = '¥0.00'
    sheet.cell(total_row, column_count).font = Font(bold=True, color="D65A31")
    widths = [28, 14, 14, 24, 18]
    for index, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream

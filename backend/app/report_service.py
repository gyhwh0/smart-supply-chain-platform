from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from PIL import Image, ImageDraw, ImageFont


def _rows(order):
    result = []
    for index, item in enumerate(order.items, 1):
        total = float(item.quantity * item.unit_price)
        result.append(
            [
                index,
                item.product.name,
                item.product.category,
                item.unit.name,
                float(item.quantity),
                float(item.unit_price),
                total,
                "是" if item.is_best_price else "否",
                item.remark or "",
            ]
        )
    return result


def build_excel(order) -> BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "采购订单"
    headers = ["序号", "商品", "品类", "单位", "数量", "单价", "金额", "供应商最优价", "备注"]
    sheet.merge_cells("A1:I1")
    sheet["A1"] = order.title
    sheet["A1"].font = Font(size=18, bold=True, color="FFFFFF")
    sheet["A1"].fill = PatternFill("solid", fgColor="2F6FB2")
    sheet["A1"].alignment = Alignment(horizontal="center", vertical="center")
    sheet.row_dimensions[1].height = 34
    sheet.merge_cells("A2:C2"); sheet["A2"] = f"订单编号：{order.order_no}"
    sheet.merge_cells("D2:F2"); sheet["D2"] = f"供应商：{order.supplier.name}"
    sheet.merge_cells("G2:I2"); sheet["G2"] = f"期望到货：{order.expected_date or '未指定'}"
    for column, value in enumerate(headers, 1):
        cell = sheet.cell(4, column, value)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="4D88C7")
        cell.alignment = Alignment(horizontal="center")
    thin = Side(style="thin", color="D9E0E8")
    data_rows = _rows(order)
    for row_index, values in enumerate(data_rows, 5):
        for column, value in enumerate(values, 1):
            cell = sheet.cell(row_index, column, value)
            cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)
            cell.alignment = Alignment(horizontal="center", vertical="center")
            if column in {6, 7}:
                cell.number_format = '¥0.00##'
        if values[7] == "是":
            sheet.cell(row_index, 8).fill = PatternFill("solid", fgColor="DDF3E8")
    total_row = 5 + len(data_rows)
    sheet.merge_cells(start_row=total_row, start_column=1, end_row=total_row, end_column=6)
    sheet.cell(total_row, 1, "订单总金额").font = Font(bold=True)
    sheet.cell(total_row, 7, sum(row[6] for row in data_rows)).number_format = '¥0.00'
    sheet.cell(total_row, 7).font = Font(bold=True, color="D65A31")
    sheet.merge_cells(start_row=total_row + 2, start_column=1, end_row=total_row + 2, end_column=9)
    sheet.cell(total_row + 2, 1, f"备注：{order.notes or '无'}")
    sheet.merge_cells(start_row=total_row + 3, start_column=1, end_row=total_row + 3, end_column=9)
    sheet.cell(total_row + 3, 1, order.report_footer or "请供应商按订单明细备货，并及时反馈交付情况。")
    widths = [8, 22, 14, 10, 12, 14, 15, 16, 24]
    for index, width in enumerate(widths, 1):
        sheet.column_dimensions[chr(64 + index)].width = width
    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream


def _font(size: int, bold: bool = False):
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc" if bold else "/System/Library/Fonts/STHeiti Light.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def build_image(order) -> BytesIO:
    rows = _rows(order)
    width = 1500
    row_height = 54
    height = 310 + (len(rows) + 2) * row_height + 150
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    blue, pale, line = "#2F6FB2", "#F2F7FC", "#D9E2EC"
    draw.rectangle((0, 0, width, 110), fill=blue)
    draw.text((width / 2, 34), order.title, font=_font(34, True), fill="white", anchor="ma")
    draw.text((60, 138), f"订单编号：{order.order_no}", font=_font(20), fill="#34445A")
    draw.text((530, 138), f"供应商：{order.supplier.name}", font=_font(20), fill="#34445A")
    draw.text((1080, 138), f"期望到货：{order.expected_date or '未指定'}", font=_font(20), fill="#34445A")
    columns = [60, 135, 400, 575, 690, 810, 955, 1110, 1260, 1440]
    headers = ["序号", "商品", "品类", "单位", "数量", "单价", "金额", "最优价", "备注"]
    top = 205
    draw.rectangle((columns[0], top, columns[-1], top + row_height), fill="#4D88C7")
    for index, header in enumerate(headers):
        draw.text(((columns[index] + columns[index + 1]) / 2, top + row_height / 2), header, font=_font(18, True), fill="white", anchor="mm")
    for row_index, values in enumerate(rows):
        y = top + (row_index + 1) * row_height
        draw.rectangle((columns[0], y, columns[-1], y + row_height), fill=pale if row_index % 2 else "white")
        display = [values[0], values[1], values[2], values[3], f"{values[4]:g}", f"¥{values[5]:.2f}", f"¥{values[6]:.2f}", values[7], values[8]]
        for index, value in enumerate(display):
            color = "#23845E" if index == 7 and value == "是" else "#34445A"
            draw.text(((columns[index] + columns[index + 1]) / 2, y + row_height / 2), str(value)[:18], font=_font(17), fill=color, anchor="mm")
    bottom = top + (len(rows) + 1) * row_height
    for x in columns:
        draw.line((x, top, x, bottom), fill=line, width=1)
    for index in range(len(rows) + 2):
        y = top + index * row_height
        draw.line((columns[0], y, columns[-1], y), fill=line, width=1)
    total = sum(row[6] for row in rows)
    draw.text((columns[-1], bottom + 42), f"订单总金额：¥ {total:.2f}", font=_font(25, True), fill="#D65A31", anchor="ra")
    draw.text((60, bottom + 92), f"备注：{order.notes or '无'}", font=_font(18), fill="#526174")
    draw.text((60, bottom + 130), order.report_footer or "请供应商按订单明细备货，并及时反馈交付情况。", font=_font(17), fill="#7A8798")
    stream = BytesIO()
    image.save(stream, format="PNG")
    stream.seek(0)
    return stream

"""CSV and formatted Excel exports. Excel files also open in Google Sheets."""
from __future__ import annotations

import csv
import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from backend.engine import domain as d
from backend.engine.calendar import Context

STATUS_LABEL = {
    d.WEEKLY_OFF: "Weekly off", d.HOLIDAY: "Holiday", d.LEAVE: "Leave", d.COMP_OFF: "Comp-off",
    d.UNAVAILABLE: "Unavailable", d.IDLE: "Spare", d.WORK: "Working",
}
STATUS_SHORT = {
    d.WEEKLY_OFF: "WO", d.HOLIDAY: "H", d.LEAVE: "L", d.COMP_OFF: "CO", d.UNAVAILABLE: "UA", d.IDLE: "S",
}
FILL = {
    d.WORK: "D5EFE9", d.WEEKLY_OFF: "E4E8EC", d.HOLIDAY: "FBEBC8", d.LEAVE: "E6DBF5",
    d.COMP_OFF: "E6DBF5", d.UNAVAILABLE: "F4D6DC", d.IDLE: "FFFFFF",
}
RED = "F4B8BF"
THIN = Side(style="thin", color="C9D1D9")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HEAD = PatternFill("solid", fgColor="16324F")


def safe(value):
    """Stop spreadsheet apps treating text as a formula."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def _employees(ctx: Context) -> list[d.Employee]:
    return sorted(ctx.employees.values(), key=lambda e: (e.pod_id or "", e.name))


def _pod_names(conn_pods: list[dict]) -> dict:
    return {p["id"]: p["name"] for p in conn_pods}


def csv_export(inp: d.RosterInput, roster: d.Roster, pods: list[dict]) -> str:
    ctx = Context(inp)
    pod_name = _pod_names(pods)
    by_day = roster.by_employee_day()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Date", "Weekday", "Pod", "Employee", "Status", "Brand", "Process", "Shift", "Cover", "Workload %"])
    for e in _employees(ctx):
        for day in ctx.days:
            r = roster.days.get((e.id, day))
            if r is None:
                continue
            base = [day.isoformat(), day.strftime("%a"), pod_name.get(e.pod_id, ""), safe(e.name)]
            items = by_day.get((e.id, day), [])
            if not items:
                w.writerow([*base, STATUS_LABEL.get(r.status, r.status), "", "", "", "", ""])
            for a in items:
                bp = ctx.bps.get(a.brand_process_id)
                brand = ctx.brands[bp.brand_id].name if bp else ""
                process = ctx.processes[bp.process_id].code if bp else ""
                shift = ctx.shifts[a.shift_id].name if a.shift_id in ctx.shifts else ""
                w.writerow([*base, "Working", safe(brand), safe(process), shift, "Yes" if a.is_cover else "No", a.share])
    return out.getvalue()


def _title_row(ws, row, values, fill=HEAD):
    for col, value in enumerate(values, 1):
        cell = ws.cell(row=row, column=col, value=value)
        cell.fill = fill
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BOX


def excel_export(inp: d.RosterInput, roster: d.Roster, issues: list[dict], pods: list[dict], meta: dict) -> bytes:
    ctx = Context(inp)
    pod_name = _pod_names(pods)
    by_day = roster.by_employee_day()
    by_bp_day = roster.by_process_day()
    wb = Workbook()

    # Sheet 1: who is doing what
    ws = wb.active
    ws.title = "Roster"
    ws.append([f"{meta['month']} roster, version {meta['version']} ({meta['status']})"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append(["Key: process codes = working; WO weekly off; H holiday; L leave; CO comp-off; UA unavailable; S spare; * = cover"])
    header = ["Pod", "Employee", *[f"{x.strftime('%a')[:2]} {x.day}" for x in ctx.days]]
    _title_row(ws, 3, header)
    row_index = 4
    for e in _employees(ctx):
        ws.cell(row=row_index, column=1, value=safe(pod_name.get(e.pod_id, ""))).border = BOX
        ws.cell(row=row_index, column=2, value=safe(e.name)).border = BOX
        for col, day in enumerate(ctx.days, 3):
            r = roster.days.get((e.id, day))
            status = r.status if r else None
            if status == d.WORK:
                text = "\n".join(
                    f"{ctx.brands[ctx.bps[a.brand_process_id].brand_id].name[:10]} {ctx.processes[ctx.bps[a.brand_process_id].process_id].code}{'*' if a.is_cover else ''}"
                    for a in by_day.get((e.id, day), []) if a.brand_process_id in ctx.bps
                )
            else:
                text = STATUS_SHORT.get(status, "")
            cell = ws.cell(row=row_index, column=col, value=safe(text))
            cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
            cell.font = Font(size=8)
            cell.border = BOX
            if status in FILL:
                cell.fill = PatternFill("solid", fgColor=FILL[status])
        row_index += 1
    ws.column_dimensions["A"].width = 10
    ws.column_dimensions["B"].width = 20
    for col in range(3, len(ctx.days) + 3):
        ws.column_dimensions[get_column_letter(col)].width = 12
    ws.freeze_panes = "C4"

    # Sheet 2: coverage by process and day
    cov = wb.create_sheet("Coverage")
    _title_row(cov, 1, ["Brand", "Process", "Shift", *[f"{x.day}" for x in ctx.days]])
    row_index = 2
    for bp in sorted(ctx.bps.values(), key=lambda b: (ctx.brands[b.brand_id].name, ctx.processes[b.process_id].code)):
        cov.cell(row=row_index, column=1, value=safe(ctx.brands[bp.brand_id].name)).border = BOX
        cov.cell(row=row_index, column=2, value=safe(ctx.processes[bp.process_id].code)).border = BOX
        cov.cell(row=row_index, column=3, value=ctx.shifts[bp.shift_id].name).border = BOX
        for col, day in enumerate(ctx.days, 4):
            required = ctx.required(bp.id, day)
            staffed = len({a.employee_id for a in by_bp_day.get((bp.id, day), [])})
            cell = cov.cell(row=row_index, column=col, value=f"{staffed}/{required}" if required else "")
            cell.alignment = Alignment(horizontal="center")
            cell.border = BOX
            if required and staffed < required:
                cell.fill = PatternFill("solid", fgColor=RED)
            elif required:
                cell.fill = PatternFill("solid", fgColor=FILL[d.WORK])
        row_index += 1
    cov.column_dimensions["A"].width = 20
    cov.freeze_panes = "D2"

    # Sheet 3: issues
    sheet = wb.create_sheet("Issues")
    _title_row(sheet, 1, ["Severity", "Date", "Issue", "What to do", "Override reason"])
    for i in issues:
        if i["severity"] == "info":
            continue
        sheet.append([i["severity"].title(), str(i["date"] or ""), safe(i["message"]), safe(i.get("suggestion") or ""), safe(i.get("override_reason") or "")])
    for col, width in zip("ABCDE", (10, 12, 90, 60, 40)):
        sheet.column_dimensions[col].width = width
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    sheet.freeze_panes = "A2"

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()

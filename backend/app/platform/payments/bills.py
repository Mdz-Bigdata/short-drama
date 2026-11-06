"""Reading the statements the channels publish each day. Anything unexpected is an error, never an empty bill."""

from __future__ import annotations

import csv
import io
import zipfile
from decimal import Decimal, InvalidOperation

from app.platform.payments.base import BillRow, BillUnreadable

_MAX_BILL_BYTES = 50 * 1024 * 1024


def _fen(text: str) -> int:
    try:
        value = Decimal(text.strip().lstrip("`").replace(",", "")) * 100
    except InvalidOperation as exc:
        raise BillUnreadable(f"账单金额无法解析: {text[:20]!r}") from exc
    if not value.is_finite() or value != value.to_integral_value():
        raise BillUnreadable(f"账单金额不是整数分: {text[:20]!r}")
    return abs(int(value))


def parse_wechat_trade_bill(raw: bytes) -> tuple[BillRow, ...]:
    """The ALL bill: a header, detail rows with a backtick before each field, then a totals header and one totals row.

    Row kinds and fields follow https://pay.weixin.qq.com/doc/v3/merchant/4013071246. Totals are checked, so a truncated
    download cannot pass as a shorter day.
    """
    try:
        lines = [line for line in raw.decode("utf-8-sig").splitlines() if line.strip()]
    except UnicodeDecodeError as exc:
        raise BillUnreadable("微信账单编码无法识别") from exc
    if not lines:
        raise BillUnreadable("微信账单是空文件")
    header = [name.strip().lstrip("`") for name in next(csv.reader([lines[0]]))]
    needed = ("微信订单号", "商户订单号", "交易状态", "订单金额", "商户退款单号", "申请退款金额")
    if any(name not in header for name in needed):
        raise BillUnreadable("微信账单缺少必要的列")
    position = {name: header.index(name) for name in needed}
    totals_at = next((index for index, line in enumerate(lines) if line.lstrip("`").startswith("总交易单数")), None)
    if totals_at is None or totals_at + 1 >= len(lines):
        raise BillUnreadable("微信账单缺少汇总行，可能不完整")
    rows = []
    for line in lines[1:totals_at]:
        cells = [cell.strip().lstrip("`") for cell in next(csv.reader([line]))]
        if len(cells) != len(header):
            raise BillUnreadable("微信账单的列数与表头不符")
        state = cells[position["交易状态"]]
        if state == "SUCCESS":
            rows.append(BillRow("payment", cells[position["商户订单号"]], _fen(cells[position["订单金额"]]), cells[position["微信订单号"]]))
        elif state in ("REFUND", "REVOKED"):
            rows.append(BillRow(
                "refund", cells[position["商户订单号"]], _fen(cells[position["申请退款金额"]]), cells[position["微信订单号"]],
                cells[position["商户退款单号"]],
            ))
        else:
            raise BillUnreadable(f"微信账单有未知的交易状态: {state[:20]!r}")
    labels = [name.strip().lstrip("`") for name in next(csv.reader([lines[totals_at]]))]
    values = [cell.strip().lstrip("`") for cell in next(csv.reader([lines[totals_at + 1]]))]
    totals = dict(zip(labels, values))
    try:
        stated = int(totals["总交易单数"])
        stated_paid, stated_refund = _fen(totals["订单总金额"]), _fen(totals["申请退款总金额"])
    except (KeyError, ValueError) as exc:
        raise BillUnreadable("微信账单汇总行无法解析") from exc
    paid = sum(row.amount_minor for row in rows if row.kind == "payment")
    refunded = sum(row.amount_minor for row in rows if row.kind == "refund")
    if (stated, stated_paid, stated_refund) != (len(rows), paid, refunded):
        raise BillUnreadable("微信账单明细与汇总对不上，可能不完整")
    return tuple(rows)


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise BillUnreadable("支付宝账单编码无法识别")


def parse_alipay_trade_bill(raw: bytes) -> tuple[BillRow, ...]:
    """A zip holding a detail file and a summary file. The columns can be configured per merchant, so they are found by name.

    Column names and the meaning of 退款批次号 follow https://ideservice.alipay.com/cms/site/0izcsq. The layout around the
    table (the # lines) comes from no document, only from what such files are known to look like, so it is matched loosely.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise BillUnreadable("支付宝账单不是有效的压缩包") from exc
    with archive:
        if sum(info.file_size for info in archive.infolist()) > _MAX_BILL_BYTES:
            raise BillUnreadable("支付宝账单解压后过大")
        texts = [_decode(archive.read(info)) for info in archive.infolist() if not info.is_dir()]
    needed = ("支付宝交易号", "商户订单号", "业务类型", "订单金额（元）", "商家实收（元）")
    for text in texts:
        records = [row for row in csv.reader(io.StringIO(text)) if row and not row[0].lstrip().startswith("#")]
        records = [[cell.strip() for cell in row] for row in records]
        header_at = next((index for index, row in enumerate(records) if "商户订单号" in row and "支付宝交易号" in row), None)
        if header_at is None:
            continue
        header = records[header_at]
        if any(name not in header for name in needed):
            raise BillUnreadable("支付宝账单缺少必要的列，请在商家平台的账单下载设置里保留它们")
        position = {name: header.index(name) for name in (*needed, "退款批次号") if name in header}
        rows = []
        for record in records[header_at + 1:]:
            if len(record) != len(header):
                if record[0].startswith("业务明细列表结束") or len(record) == 1:
                    continue
                raise BillUnreadable("支付宝账单的列数与表头不符")
            kind = record[position["业务类型"]]
            if kind == "交易":
                rows.append(BillRow("payment", record[position["商户订单号"]], _fen(record[position["订单金额（元）"]]), record[position["支付宝交易号"]]))
            elif kind == "退款":
                if "退款批次号" not in position:
                    raise BillUnreadable("支付宝账单缺少退款批次号列")
                rows.append(BillRow(
                    "refund", record[position["商户订单号"]], _fen(record[position["商家实收（元）"]]), record[position["支付宝交易号"]],
                    record[position["退款批次号"]],
                ))
            else:
                raise BillUnreadable(f"支付宝账单有未知的业务类型: {kind[:20]!r}")
        return tuple(rows)
    raise BillUnreadable("支付宝账单里没有找到明细表")

"""Reading the statements the channels publish each day. Anything unexpected is an error, never an empty bill."""

from __future__ import annotations

import csv
import io
import zipfile
from decimal import Decimal, InvalidOperation

from app.platform.payments.base import BillRow, BillUnreadable
from app.core import prompt_data


_WORDING_FILE = "payments_bills"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/payments_bills.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

_MAX_BILL_BYTES = 50 * 1024 * 1024


def _fen(text: str) -> int:
    try:
        value = Decimal(text.strip().lstrip("`").replace(",", "")) * 100
    except InvalidOperation as exc:
        raise BillUnreadable(_text_of("_fen.text").format(text[:20])) from exc
    if not value.is_finite() or value != value.to_integral_value():
        raise BillUnreadable(_text_of("_fen.text.2").format(text[:20]))
    return abs(int(value))


def parse_wechat_trade_bill(raw: bytes) -> tuple[BillRow, ...]:
    """The ALL bill: a header, detail rows with a backtick before each field, then a totals header and one totals row.

    Row kinds and fields follow https://pay.weixin.qq.com/doc/v3/merchant/4013071246. Totals are checked, so a truncated
    download cannot pass as a shorter day.
    """
    try:
        lines = [line for line in raw.decode("utf-8-sig").splitlines() if line.strip()]
    except UnicodeDecodeError as exc:
        raise BillUnreadable(_text_of("parse_wechat_trade_bill.text")) from exc
    if not lines:
        raise BillUnreadable(_text_of("parse_wechat_trade_bill.text.2"))
    header = [name.strip().lstrip("`") for name in next(csv.reader([lines[0]]))]
    needed = _words_of("parse_wechat_trade_bill.needed")
    if any(name not in header for name in needed):
        raise BillUnreadable(_text_of("parse_wechat_trade_bill.text.3"))
    position = {name: header.index(name) for name in needed}
    totals_at = next((index for index, line in enumerate(lines) if line.lstrip("`").startswith(_text_of("parse_wechat_trade_bill.totals_at"))), None)
    if totals_at is None or totals_at + 1 >= len(lines):
        raise BillUnreadable(_text_of("parse_wechat_trade_bill.text.4"))
    rows = []
    for line in lines[1:totals_at]:
        cells = [cell.strip().lstrip("`") for cell in next(csv.reader([line]))]
        if len(cells) != len(header):
            raise BillUnreadable(_text_of("parse_wechat_trade_bill.text.5"))
        state = cells[position[_text_of("parse_wechat_trade_bill.state")]]
        if state == "SUCCESS":
            rows.append(BillRow("payment", cells[position[_text_of("parse_wechat_trade_bill.text.6")]], _fen(cells[position[_text_of("parse_wechat_trade_bill.text.7")]]), cells[position[_text_of("parse_wechat_trade_bill.text.8")]]))
        elif state in ("REFUND", "REVOKED"):
            rows.append(BillRow(
                "refund", cells[position[_text_of("parse_wechat_trade_bill.text.9")]], _fen(cells[position[_text_of("parse_wechat_trade_bill.text.10")]]), cells[position[_text_of("parse_wechat_trade_bill.text.11")]],
                cells[position[_text_of("parse_wechat_trade_bill.text.12")]],
            ))
        else:
            raise BillUnreadable(_text_of("parse_wechat_trade_bill.text.13").format(state[:20]))
    labels = [name.strip().lstrip("`") for name in next(csv.reader([lines[totals_at]]))]
    values = [cell.strip().lstrip("`") for cell in next(csv.reader([lines[totals_at + 1]]))]
    totals = dict(zip(labels, values))
    try:
        stated = int(totals[_text_of("parse_wechat_trade_bill.stated")])
        stated_paid, stated_refund = _fen(totals[_text_of("parse_wechat_trade_bill.text.14")]), _fen(totals[_text_of("parse_wechat_trade_bill.text.15")])
    except (KeyError, ValueError) as exc:
        raise BillUnreadable(_text_of("parse_wechat_trade_bill.text.16")) from exc
    paid = sum(row.amount_minor for row in rows if row.kind == "payment")
    refunded = sum(row.amount_minor for row in rows if row.kind == "refund")
    if (stated, stated_paid, stated_refund) != (len(rows), paid, refunded):
        raise BillUnreadable(_text_of("parse_wechat_trade_bill.text.17"))
    return tuple(rows)


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise BillUnreadable(_text_of("_decode.text"))


def parse_alipay_trade_bill(raw: bytes) -> tuple[BillRow, ...]:
    """A zip holding a detail file and a summary file. The columns can be configured per merchant, so they are found by name.

    Column names and the meaning of 退款批次号 follow https://ideservice.alipay.com/cms/site/0izcsq. The layout around the
    table (the # lines) comes from no document, only from what such files are known to look like, so it is matched loosely.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise BillUnreadable(_text_of("parse_alipay_trade_bill.text")) from exc
    with archive:
        if sum(info.file_size for info in archive.infolist()) > _MAX_BILL_BYTES:
            raise BillUnreadable(_text_of("parse_alipay_trade_bill.text.2"))
        texts = [_decode(archive.read(info)) for info in archive.infolist() if not info.is_dir()]
    needed = _words_of("parse_alipay_trade_bill.needed")
    for text in texts:
        records = [row for row in csv.reader(io.StringIO(text)) if row and not row[0].lstrip().startswith("#")]
        records = [[cell.strip() for cell in row] for row in records]
        header_at = next((index for index, row in enumerate(records) if _text_of("parse_alipay_trade_bill.header_at") in row and _text_of("parse_alipay_trade_bill.header_at.2") in row), None)
        if header_at is None:
            continue
        header = records[header_at]
        if any(name not in header for name in needed):
            raise BillUnreadable(_text_of("parse_alipay_trade_bill.text.3"))
        position = {name: header.index(name) for name in (*needed, _text_of("parse_alipay_trade_bill.position")) if name in header}
        rows = []
        for record in records[header_at + 1:]:
            if len(record) != len(header):
                if record[0].startswith(_text_of("parse_alipay_trade_bill.text.4")) or len(record) == 1:
                    continue
                raise BillUnreadable(_text_of("parse_alipay_trade_bill.text.5"))
            kind = record[position[_text_of("parse_alipay_trade_bill.kind")]]
            if kind == _text_of("parse_alipay_trade_bill.text.6"):
                rows.append(BillRow("payment", record[position[_text_of("parse_alipay_trade_bill.text.7")]], _fen(record[position[_text_of("parse_alipay_trade_bill.text.8")]]), record[position[_text_of("parse_alipay_trade_bill.text.9")]]))
            elif kind == _text_of("parse_alipay_trade_bill.text.10"):
                if _text_of("parse_alipay_trade_bill.text.11") not in position:
                    raise BillUnreadable(_text_of("parse_alipay_trade_bill.text.12"))
                rows.append(BillRow(
                    "refund", record[position[_text_of("parse_alipay_trade_bill.text.13")]], _fen(record[position[_text_of("parse_alipay_trade_bill.text.14")]]), record[position[_text_of("parse_alipay_trade_bill.text.15")]],
                    record[position[_text_of("parse_alipay_trade_bill.text.16")]],
                ))
            else:
                raise BillUnreadable(_text_of("parse_alipay_trade_bill.text.17").format(kind[:20]))
        return tuple(rows)
    raise BillUnreadable(_text_of("parse_alipay_trade_bill.text.18"))

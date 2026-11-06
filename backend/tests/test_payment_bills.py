# -*- coding: utf-8 -*-
"""Reading channel bills: what the documents describe reads correctly, and anything off is an error rather than a short day."""

import hashlib
import io
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path

from app.platform.payments.base import BillNotReady, BillRow, BillUnreadable, ChannelError
from app.platform.payments.bills import parse_alipay_trade_bill, parse_wechat_trade_bill
from tests.payment_fakes import FakeAlipay, FakeWeChat, alipay_bill, wechat_bill

DAY = date(2026, 11, 4)


class WeChatBillTests(unittest.TestCase):
    def test_payments_and_refunds_read_in_fen(self):
        rows = parse_wechat_trade_bill(wechat_bill([("P1", "42001", 2990)], [("P1", "42001", 1000, "R1")]))
        self.assertEqual(rows, (BillRow("payment", "P1", 2990, "42001"), BillRow("refund", "P1", 1000, "42001", "R1")))

    def test_a_day_with_nothing_is_empty_not_an_error(self):
        self.assertEqual(parse_wechat_trade_bill(wechat_bill()), ())

    def test_anything_incomplete_or_strange_is_refused(self):
        good = wechat_bill([("P1", "42001", 2990), ("P2", "42002", 100)]).decode()
        lines = good.splitlines()
        cases = {
            "no totals": "\n".join(lines[:-2]),
            "a row lost": "\n".join(lines[:1] + lines[2:]),
            "amount changed": good.replace("`0.60%,`29.90", "`0.60%,`19.90", 1),
            "unknown state": good.replace("`SUCCESS", "`SOMETHING", 1),
            "missing column": good.replace("商户订单号", "别的列"),
            "fewer cells": good.replace("`NATIVE,", "", 1),
            "empty": "",
            "not whole fen": good.replace("`0.60%,`29.90", "`0.60%,`29.905", 1),
        }
        for name, text in cases.items():
            with self.subTest(name), self.assertRaises(BillUnreadable):
                parse_wechat_trade_bill(text.encode())
        with self.assertRaises(BillUnreadable):
            parse_wechat_trade_bill(b"\xff\xfe\x00")


class AlipayBillTests(unittest.TestCase):
    def test_payments_and_refunds_read_in_fen(self):
        rows = parse_alipay_trade_bill(alipay_bill([("P1", "2026001", 2990)], [("P1", "2026001", 1000, "R1")]))
        self.assertEqual(rows, (BillRow("payment", "P1", 2990, "2026001"), BillRow("refund", "P1", 1000, "2026001", "R1")))

    def test_a_day_with_nothing_is_empty(self):
        self.assertEqual(parse_alipay_trade_bill(alipay_bill()), ())

    def test_what_cannot_be_read_is_refused(self):
        for name, raw in {
            "not a zip": b"PK not really", "missing amount column": alipay_bill([("P1", "1", 100)], drop_column="订单金额（元）"),
            "no detail table": alipay_bill(drop_column="支付宝交易号"),
        }.items():
            with self.subTest(name), self.assertRaises(BillUnreadable):
                parse_alipay_trade_bill(raw)

    def test_a_refund_without_its_batch_number_column_is_refused(self):
        with self.assertRaises(BillUnreadable):
            parse_alipay_trade_bill(alipay_bill(refunds=[("P1", "1", 100, "R1")], drop_column="退款批次号"))

    def test_an_unknown_business_type_is_refused(self):
        with self.assertRaises(BillUnreadable):
            parse_alipay_trade_bill(_with_type("结算"))


def _with_type(kind: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("a.csv", f"支付宝交易号,商户订单号,业务类型,订单金额（元）,商家实收（元）\n1,P1,{kind},1.00,1.00\n".encode("gbk"))
    return buffer.getvalue()


class DownloadTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.wechat, self.alipay = FakeWeChat(Path(temp.name)), FakeAlipay(Path(temp.name))

    def test_wechat_downloads_and_checks_the_hash(self):
        self.wechat.bills[DAY.isoformat()] = wechat_bill([("P1", "42001", 2990)])
        bill = self.wechat.channel().download_bill(DAY)
        self.assertEqual(bill.rows, (BillRow("payment", "P1", 2990, "42001"),))
        self.assertEqual(hashlib.sha1(bill.raw).hexdigest(), hashlib.sha1(self.wechat.bills[DAY.isoformat()]).hexdigest())

    def test_wechat_a_changed_file_is_refused(self):
        self.wechat.bills[DAY.isoformat()] = wechat_bill([("P1", "42001", 2990)])
        self.wechat.bill_hash = "0" * 40
        with self.assertRaisesRegex(BillUnreadable, "哈希"):
            self.wechat.channel().download_bill(DAY)

    def test_wechat_not_generated_yet_is_not_a_failure(self):
        for code in ("NO_STATEMENT_EXIST", "STATEMENT_CREATING"):
            self.wechat.bill_code = code
            with self.subTest(code), self.assertRaises(BillNotReady):
                self.wechat.channel().download_bill(DAY)
        self.wechat.bill_code = "INVALID_REQUEST"
        with self.assertRaises(ChannelError) as caught:
            self.wechat.channel().download_bill(DAY)
        self.assertNotIsInstance(caught.exception, BillNotReady)

    def test_wechat_never_signs_a_request_to_somewhere_else(self):
        self.wechat.bills[DAY.isoformat()] = wechat_bill()
        for url in ("https://evil.example/v3/billdownload/file?token=a", "http://api.mch.weixin.qq.com/v3/billdownload/file?token=a"):
            self.wechat.bill_url = url
            with self.subTest(url), self.assertRaisesRegex(ChannelError, "不可信"):
                self.wechat.channel().download_bill(DAY)

    def test_alipay_downloads(self):
        self.alipay.bills[DAY.isoformat()] = alipay_bill([("P1", "2026001", 2990)])
        self.assertEqual(self.alipay.channel().download_bill(DAY).rows, (BillRow("payment", "P1", 2990, "2026001"),))

    def test_alipay_refusal_counts_as_not_ready(self):
        with self.assertRaises(BillNotReady):
            self.alipay.channel().download_bill(DAY)

    def test_alipay_only_fetches_from_alipay(self):
        self.alipay.bills[DAY.isoformat()] = alipay_bill()
        channel = self.alipay.channel()
        self.alipay.bill_host = "alipay.com.evil.example"
        with self.assertRaisesRegex(ChannelError, "不可信"):
            channel.download_bill(DAY)


if __name__ == "__main__":
    unittest.main()

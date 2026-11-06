# -*- coding: utf-8 -*-
"""Each channel's real adapter against a fake that speaks its protocol: signing, verifying, and turning answers into our terms."""

import base64
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app.platform import payments
from app.platform.payments import get_payment_channels
from app.platform.payments.alipay import _to_minor, signed_part_of_response
from app.platform.payments.base import CLOSED, PAID, UNPAID, ChannelError, NotificationRejected, new_merchant_no
from app.platform.payments.wechat import WeChatPay
from tests.payment_fakes import STRANGER_KEY, FakeAlipay, FakeWeChat


class Base(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.expires = datetime.now(timezone.utc) + timedelta(minutes=15)


class MerchantNumberTests(unittest.TestCase):
    def test_fits_what_both_channels_allow(self):
        number = new_merchant_no("P")
        self.assertLessEqual(len(number), 32)
        self.assertRegex(number, r"^[0-9A-Za-z]+$")
        self.assertNotEqual(number, new_merchant_no("P"))


class WeChatTests(Base):
    def setUp(self):
        super().setUp()
        self.fake = FakeWeChat(self.folder)
        self.channel = self.fake.channel()

    def _trade(self, out="P20261105000000abcdef"):
        self.channel.create_qr(out_trade_no=out, amount_minor=2990, description="月度 会员", expires_at=self.expires)
        return out

    def test_a_signed_order_gets_a_code_and_the_amount_is_in_fen(self):
        code = self.channel.create_qr(out_trade_no="P2026110500000001", amount_minor=2990, description="会员", expires_at=self.expires)
        self.assertTrue(code.startswith("weixin://"))
        self.assertEqual(self.fake.trades["P2026110500000001"]["amount"], {"total": 2990, "currency": "CNY"})

    def test_query_and_close_sign_their_paths_too(self):
        out = self._trade()
        self.assertEqual(self.channel.query(out).state, UNPAID)
        self.fake.pay(out)
        trade = self.channel.query(out)
        self.assertEqual((trade.state, trade.amount_minor, trade.merchant_id), (PAID, 2990, self.channel.merchant_id))
        self.assertTrue(trade.channel_trade_no)
        self.channel.close(out)
        self.assertEqual(self.channel.query(out).state, CLOSED)

    def test_a_trade_the_channel_has_not_heard_of_is_unpaid(self):
        self.assertEqual(self.channel.query("Pnever").state, UNPAID)

    def test_an_answer_not_signed_by_wechat_is_thrown_away(self):
        out = self._trade()
        self.fake.pay(out)
        self.fake.unsigned = True
        with self.assertRaisesRegex(ChannelError, "验签"):
            self.channel.query(out)

    def test_a_valid_notification_is_read(self):
        out = self._trade()
        self.fake.pay(out)
        event = self.channel.parse_notification(*self.fake.notification(out, event_id="evt-1"))
        self.assertEqual(event.event_id, "evt-1")
        self.assertEqual((event.trade.state, event.trade.amount_minor, event.trade.out_trade_no), (PAID, 2990, out))
        self.assertEqual(event.trade.paid_at, datetime.fromisoformat("2026-11-05T10:00:00+08:00"))

    def test_notifications_that_fail_verification(self):
        out = self._trade()
        self.fake.pay(out)
        headers, body = self.fake.notification(out)
        probe = "WECHATPAY/SIGNTEST/" + base64.b64encode(b"probe").decode()
        cases = {
            "wrong key": self.fake.notification(out, key=STRANGER_KEY),
            "probe signature": self.fake.notification(out, signature=probe),
            "unknown key id": self.fake.notification(out, serial="PUB_KEY_ID_OTHER"),
            "too old": self.fake.notification(out, age=3600),
            "changed in transit": (headers, body.replace(b"TRANSACTION.SUCCESS", b"TRANSACTION.SUCCESS ")),
            "no headers": ({}, body),
        }
        for name, (case_headers, case_body) in cases.items():
            with self.subTest(name), self.assertRaises(NotificationRejected):
                self.channel.parse_notification(case_headers, case_body)

    def test_signed_but_undecryptable_is_rejected(self):
        out = self._trade()
        self.fake.pay(out)
        _, body = self.fake.notification(out)
        envelope = json.loads(body)
        envelope["resource"]["ciphertext"] = base64.b64encode(b"x" * 64).decode()
        with self.assertRaises(NotificationRejected):
            self.channel.parse_notification(*self.fake.signed(json.dumps(envelope).encode()))

    def test_another_kind_of_event_is_verified_and_ignored(self):
        event = self.channel.parse_notification(*self.fake.signed(json.dumps({"id": "e", "event_type": "REFUND.SUCCESS"}).encode()))
        self.assertIsNone(event.trade)

    def test_refunds(self):
        out = self._trade()
        self.fake.pay(out)
        self.assertEqual(self.channel.query_refund(out_trade_no=out, out_refund_no="R1").state, "pending")
        self.assertEqual(self.channel.refund(out_trade_no=out, out_refund_no="R1", refund_minor=2990, total_minor=2990, reason="x").state, "processing")
        self.assertEqual(self.fake.refunds["R1"]["body"]["amount"], {"refund": 2990, "total": 2990, "currency": "CNY"})
        self.assertEqual(self.channel.query_refund(out_trade_no=out, out_refund_no="R1").state, "succeeded")
        self.fake.refund_status = "ABNORMAL"
        self.assertEqual(self.channel.query_refund(out_trade_no=out, out_refund_no="R1").state, "failed")

    def test_an_apiv3_key_of_the_wrong_length_is_refused_at_the_start(self):
        config = self.fake.config()
        with self.assertRaises(ChannelError):
            WeChatPay(type(config)(**{**config.__dict__, "api_v3_key": "short"}))


class AlipayTests(Base):
    def setUp(self):
        super().setUp()
        self.fake = FakeAlipay(self.folder)
        self.channel = self.fake.channel()

    def _trade(self, out="P20261105000000abcdef", amount=2990):
        self.channel.create_qr(out_trade_no=out, amount_minor=amount, description="月度 会员", expires_at=self.expires)
        return out

    def test_yuan_only_appears_at_the_edge(self):
        for fen, yuan in ((2990, "29.90"), (1, "0.01"), (100000, "1000.00")):
            with self.subTest(fen):
                out = self._trade(f"P{fen}", fen)
                self.assertEqual(self.fake.trades[out]["total_amount"], yuan)
                self.fake.pay(out)
                self.assertEqual(self.channel.query(out).amount_minor, fen)

    def test_an_amount_that_is_not_whole_fen_is_not_rounded_into_a_match(self):
        for bad in ("29.901", "abc", "NaN", "Infinity", "", None):
            with self.subTest(bad):
                self.assertIsNone(_to_minor(bad))
        self.assertEqual(_to_minor("29.90"), 2990)

    def test_characters_the_subject_may_not_contain_are_taken_out(self):
        self.channel.create_qr(out_trade_no="Psubject", amount_minor=100, description="创作/入门=A&B 会员", expires_at=self.expires)
        self.assertIn("Psubject", self.fake.trades)

    def test_a_code_nobody_scanned_is_unpaid_and_closes_quietly(self):
        out = self._trade()
        self.assertEqual(self.channel.query(out).state, UNPAID)
        self.channel.close(out)
        self.assertEqual(self.fake.closed, [out])

    def test_a_paid_trade_is_read(self):
        out = self._trade()
        self.fake.pay(out)
        trade = self.channel.query(out)
        self.assertEqual((trade.state, trade.amount_minor), (PAID, 2990))
        self.assertEqual(trade.merchant_id, self.channel.merchant_id)

    def test_only_success_states_count(self):
        out = self._trade()
        self.fake.pay(out)
        for status, state in (("TRADE_SUCCESS", PAID), ("TRADE_FINISHED", PAID), ("WAIT_BUYER_PAY", UNPAID), ("TRADE_CLOSED", CLOSED), ("SOMETHING_NEW", UNPAID)):
            with self.subTest(status):
                event = self.channel.parse_notification(*self.fake.notification(out, trade_status=status))
                self.assertEqual(event.trade.state, state)

    def test_answers_are_verified_over_the_bytes_sent(self):
        out = self._trade()
        self.fake.pay(out)
        self.fake.tamper = True
        with self.assertRaisesRegex(ChannelError, "验签"):
            self.channel.query(out)
        self.fake.tamper, self.fake.unsigned = False, True
        with self.assertRaisesRegex(ChannelError, "验签"):
            self.channel.query(out)

    def test_the_signed_part_survives_braces_and_chinese(self):
        raw = '{"a_response":{"code":"10000","msg":"成功 {x}","n":{"y":1}},"sign":"abc"}'
        self.assertEqual(signed_part_of_response(raw, "a_response"), '{"code":"10000","msg":"成功 {x}","n":{"y":1}}')
        self.assertIsNone(signed_part_of_response('{"sign":"abc","a_response":{}}', "a_response"))
        self.assertIsNone(signed_part_of_response('{"a_response":{}}', "a_response"))

    def test_a_valid_notification_is_read_with_encoded_values(self):
        out = self._trade()
        self.fake.pay(out)
        event = self.channel.parse_notification(*self.fake.notification(out, event_id="n-1"))
        self.assertEqual(event.event_id, "n-1")
        self.assertEqual((event.trade.state, event.trade.amount_minor), (PAID, 2990))
        self.assertEqual(event.trade.merchant_id, self.channel.merchant_id)
        self.assertEqual(event.trade.paid_at, datetime.fromisoformat("2026-11-05T10:00:00+08:00"))

    def test_a_notification_without_seller_id_is_still_checked_on_app_id(self):
        out = self._trade()
        self.fake.pay(out)
        self.assertEqual(self.channel.parse_notification(*self.fake.notification(out, drop=("seller_id",))).trade.merchant_id, self.channel.merchant_id)
        other = self.channel.parse_notification(*self.fake.notification(out, app_id="someone-else"))
        self.assertNotEqual(other.trade.merchant_id, self.channel.merchant_id)

    def test_notifications_that_fail_verification(self):
        out = self._trade()
        self.fake.pay(out)
        headers, body = self.fake.notification(out)
        cases = {
            "wrong key": self.fake.notification(out, key=STRANGER_KEY),
            "changed amount": (headers, body.replace(b"total_amount=29.90", b"total_amount=0.01")),
            "no signature": (headers, b"out_trade_no=" + out.encode() + b"&trade_status=TRADE_SUCCESS"),
            "not a form": (headers, b"\xff\xfe"),
            "empty": (headers, b""),
        }
        for name, (case_headers, case_body) in cases.items():
            with self.subTest(name), self.assertRaises(NotificationRejected):
                self.channel.parse_notification(case_headers, case_body)

    def test_a_refund_counts_only_when_the_query_says_so(self):
        out = self._trade()
        self.fake.pay(out)
        self.assertEqual(self.channel.query_refund(out_trade_no=out, out_refund_no="R1").state, "pending")
        self.assertEqual(self.channel.refund(out_trade_no=out, out_refund_no="R1", refund_minor=2990, total_minor=2990, reason="x").state, "succeeded")
        self.assertEqual(self.fake.refunds["R1"]["body"]["refund_amount"], "29.90")
        self.assertEqual(self.channel.refund(out_trade_no=out, out_refund_no="R1", refund_minor=2990, total_minor=2990, reason="x").state, "processing")
        self.assertEqual(self.channel.query_refund(out_trade_no=out, out_refund_no="R1").state, "succeeded")


class ConfigurationTests(Base):
    def _env(self, **overrides):
        wechat, alipay = FakeWeChat(self.folder), FakeAlipay(self.folder)
        env = {
            "PAYMENT_NOTIFY_BASE_URL": "https://shop.example/", "WECHATPAY_MCH_ID": wechat.mch_id, "WECHATPAY_APP_ID": wechat.app_id,
            "WECHATPAY_CERT_SERIAL": wechat.serial, "WECHATPAY_PRIVATE_KEY_PATH": wechat.private_key_path,
            "WECHATPAY_API_V3_KEY": wechat.api_v3_key, "WECHATPAY_PUBLIC_KEY_ID": wechat.public_key_id,
            "WECHATPAY_PUBLIC_KEY_PATH": wechat.public_key_path, "ALIPAY_APP_ID": alipay.app_id, "ALIPAY_SELLER_ID": alipay.seller_id,
            "ALIPAY_PRIVATE_KEY_PATH": alipay.private_key_path, "ALIPAY_PUBLIC_KEY_PATH": alipay.public_key_path,
        }
        return {**env, **overrides}

    def _channels(self, env):
        names = ("WECHATPAY_", "ALIPAY_", "PAYMENT_NOTIFY")
        kept = {key: value for key, value in os.environ.items() if not key.startswith(names)}
        get_payment_channels.cache_clear()
        self.addCleanup(get_payment_channels.cache_clear)
        with patch.dict(os.environ, {**kept, **env}, clear=True):
            return get_payment_channels()

    def test_nothing_configured_nothing_offered(self):
        self.assertEqual(self._channels({}), {})

    def test_fully_configured_both_offered_with_their_notify_urls(self):
        channels = self._channels(self._env())
        self.assertEqual(sorted(channels), ["alipay", "wechat"])
        self.assertEqual(channels["wechat"]._config.notify_url, "https://shop.example/api/billing/webhooks/wechat")

    def test_one_missing_setting_takes_out_that_channel_only(self):
        self.assertEqual(sorted(self._channels(self._env(WECHATPAY_API_V3_KEY=""))), ["alipay"])
        self.assertEqual(sorted(self._channels(self._env(ALIPAY_SELLER_ID=" "))), ["wechat"])

    def test_no_notify_url_no_channels(self):
        self.assertEqual(self._channels(self._env(PAYMENT_NOTIFY_BASE_URL="")), {})

    def test_a_notify_url_that_is_not_https_turns_channels_off(self):
        with self.assertLogs("app.platform.payments", "ERROR"):
            self.assertEqual(self._channels(self._env(PAYMENT_NOTIFY_BASE_URL="http://shop.example")), {})

    def test_a_bad_key_file_is_reported_without_its_contents(self):
        bad = self.folder / "bad.pem"
        bad.write_text("not-a-key-SECRETVALUE")
        with self.assertLogs("app.platform.payments", "ERROR") as logs:
            channels = self._channels(self._env(ALIPAY_PRIVATE_KEY_PATH=str(bad)))
        self.assertEqual(sorted(channels), ["wechat"])
        self.assertNotIn("SECRETVALUE", "".join(logs.output))
        self.assertIn("alipay", "".join(logs.output))

    def test_a_bare_alipay_style_key_loads(self):
        fake = FakeAlipay(self.folder)
        lines = Path(fake.public_key_path).read_text().strip().splitlines()[1:-1]
        Path(fake.public_key_path).write_text("".join(lines))
        out = fake.channel()
        self.assertEqual(out.name, "alipay")
        self.assertIs(payments.Alipay, type(out))


if __name__ == "__main__":
    unittest.main()

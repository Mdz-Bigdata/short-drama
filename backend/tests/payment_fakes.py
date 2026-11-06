# -*- coding: utf-8 -*-
"""Stand-ins for the two payment channels, speaking their real protocols, so the real adapters run end to end.

They check what they are sent as strictly as the real thing would and sign what they answer. The signature code here is
written separately from the adapters', against the documentation, so a mistake in one is not repeated in the other.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import secrets
import time
import zipfile
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.platform.payments.alipay import Alipay, AlipayConfig
from app.platform.payments.wechat import WeChatPay, WeChatPayConfig


def _new_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _sign(private_key, message: bytes) -> str:
    return base64.b64encode(private_key.sign(message, padding.PKCS1v15(), hashes.SHA256())).decode()


def _verify(public_key, message: bytes, signature: str) -> None:
    public_key.verify(base64.b64decode(signature), message, padding.PKCS1v15(), hashes.SHA256())


def _write_private(key, path: Path) -> str:
    path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
    ))
    return str(path)


def _write_public(key, path: Path) -> str:
    path.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    return str(path)


# One key each, generated once: RSA generation is slow and nothing here depends on the keys being fresh.
_MERCHANT_KEY = _new_key()
_WECHAT_KEY = _new_key()
_ALIPAY_KEY = _new_key()
_STRANGER_KEY = _new_key()


class FakeWeChat:
    mch_id, app_id, serial, public_key_id = "1900000001", "wxappid0000000001", "MERCHANTSERIAL", "PUB_KEY_ID_0001"
    api_v3_key = "0123456789abcdef0123456789abcdef"

    def __init__(self, folder: Path) -> None:
        self.private_key_path = _write_private(_MERCHANT_KEY, folder / "wx-merchant.pem")
        self.public_key_path = _write_public(_WECHAT_KEY, folder / "wx-public.pem")
        self.trades: dict[str, dict] = {}
        self.refunds: dict[str, dict] = {}
        self.closed: list[str] = []
        self.calls: list[tuple[str, str]] = []
        self.fail_paths: tuple[str, ...] = ()
        self.unsigned = False
        self.refund_status = "SUCCESS"
        self.refund_sends = 0
        self.bills: dict[str, bytes] = {}
        self.bill_code = "NO_STATEMENT_EXIST"
        self.bill_url = "https://api.mch.weixin.qq.com/v3/billdownload/file?token=abc"
        self.bill_hash = None

    def config(self) -> WeChatPayConfig:
        return WeChatPayConfig(
            mch_id=self.mch_id, app_id=self.app_id, cert_serial=self.serial, private_key_path=self.private_key_path,
            api_v3_key=self.api_v3_key, public_key_id=self.public_key_id, public_key_path=self.public_key_path,
            notify_url="https://shop.example/api/billing/webhooks/wechat",
        )

    def channel(self) -> WeChatPay:
        return WeChatPay(self.config(), transport=httpx.MockTransport(self._handle))

    def _reply(self, status: int, data: dict | None = None) -> httpx.Response:
        content = json.dumps(data, ensure_ascii=False).encode() if data is not None else b""
        timestamp, nonce = str(int(time.time())), secrets.token_hex(8)
        key = _STRANGER_KEY if self.unsigned else _WECHAT_KEY
        return httpx.Response(status, content=content, headers={
            "Wechatpay-Timestamp": timestamp, "Wechatpay-Nonce": nonce, "Wechatpay-Serial": self.public_key_id,
            "Wechatpay-Signature": _sign(key, f"{timestamp}\n{nonce}\n".encode() + content + b"\n"),
        })

    def _check_signed(self, request: httpx.Request) -> None:
        scheme, _, rest = request.headers["authorization"].partition(" ")
        assert scheme == "WECHATPAY2-SHA256-RSA2048"
        fields = dict(part.split("=", 1) for part in rest.split(","))
        fields = {key: value.strip('"') for key, value in fields.items()}
        assert fields["mchid"] == self.mch_id and fields["serial_no"] == self.serial
        assert abs(time.time() - int(fields["timestamp"])) < 300
        path = request.url.raw_path.decode()
        message = f"{request.method}\n{path}\n{fields['timestamp']}\n{fields['nonce_str']}\n".encode() + request.content + b"\n"
        _verify(_MERCHANT_KEY.public_key(), message, fields["signature"])

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self._check_signed(request)
        path = request.url.path
        self.calls.append((request.method, path))
        if any(part in path for part in self.fail_paths):
            raise httpx.ConnectError("down", request=request)
        if path == "/v3/bill/tradebill":
            day = request.url.params["bill_date"]
            assert request.url.params["bill_type"] == "ALL"
            if day not in self.bills:
                return self._reply(400, {"code": self.bill_code, "message": "none"})
            self._bill_day = day
            digest = self.bill_hash or hashlib.sha1(self.bills[day]).hexdigest()
            return self._reply(200, {"hash_type": "SHA1", "hash_value": digest, "download_url": self.bill_url})
        if path == "/v3/billdownload/file":
            return httpx.Response(200, content=self.bills[self._bill_day])  # unsigned, as the documentation says
        if request.method == "POST" and path == "/v3/pay/transactions/native":
            body = json.loads(request.content)
            assert isinstance(body["amount"]["total"], int) and body["mchid"] == self.mch_id and body["appid"] == self.app_id
            assert 6 <= len(body["out_trade_no"]) <= 32 and body["notify_url"].startswith("https://")
            self.trades[body["out_trade_no"]] = {"trade_state": "NOTPAY", "amount": body["amount"]}
            return self._reply(200, {"code_url": f"weixin://wxpay/bizpayurl?pr={body['out_trade_no']}"})
        if path.endswith("/close"):
            out = path.split("/")[-2]
            self.closed.append(out)
            self.trades.setdefault(out, {})["trade_state"] = "CLOSED"
            return self._reply(204)
        if request.method == "GET" and path.startswith("/v3/pay/transactions/out-trade-no/"):
            out = path.split("/")[-1]
            if out not in self.trades:
                return self._reply(404, {"code": "ORDER_NOT_EXIST", "message": "not found"})
            return self._reply(200, self._transaction(out))
        if request.method == "POST" and path == "/v3/refund/domestic/refunds":
            body = json.loads(request.content)
            self.refund_sends += 1
            self.refunds.setdefault(body["out_refund_no"], {"body": body, "times": 0})["times"] += 1
            return self._reply(200, {"refund_id": "wxrefund" + body["out_refund_no"][-8:], "status": "PROCESSING"})
        if request.method == "GET" and path.startswith("/v3/refund/domestic/refunds/"):
            number = path.split("/")[-1]
            if number not in self.refunds:
                return self._reply(404, {"code": "RESOURCE_NOT_EXISTS", "message": "none"})
            return self._reply(200, {"refund_id": "wxrefund" + number[-8:], "status": self.refund_status})
        raise AssertionError(f"unexpected call {request.method} {path}")

    def _transaction(self, out: str, **overrides) -> dict:
        trade = self.trades[out]
        data = {
            "mchid": self.mch_id, "appid": self.app_id, "out_trade_no": out, "trade_state": trade["trade_state"],
            "amount": dict(trade.get("amount") or {}), **({"transaction_id": trade["transaction_id"]} if trade.get("transaction_id") else {}),
        }
        return {**data, **overrides}

    def pay(self, out: str) -> None:
        self.trades[out].update(trade_state="SUCCESS", transaction_id="wx" + out[-20:])

    def notification(self, out: str, *, key=None, serial=None, age: int = 0, signature=None, event_id="", **overrides) -> tuple[dict, bytes]:
        plain = json.dumps({**self._transaction(out), "success_time": "2026-11-05T10:00:00+08:00", **overrides}).encode()
        nonce, aad = "abcdefghijkl", "transaction"
        envelope = {
            "id": event_id or secrets.token_hex(8), "event_type": "TRANSACTION.SUCCESS", "resource_type": "encrypt-resource",
            "resource": {
                "algorithm": "AEAD_AES_256_GCM", "nonce": nonce, "associated_data": aad, "original_type": "transaction",
                "ciphertext": base64.b64encode(AESGCM(self.api_v3_key.encode()).encrypt(nonce.encode(), plain, aad.encode())).decode(),
            },
        }
        return self.signed(json.dumps(envelope).encode(), key=key, serial=serial, age=age, signature=signature)

    def signed(self, body: bytes, *, key=None, serial=None, age: int = 0, signature=None) -> tuple[dict, bytes]:
        timestamp, nonce = str(int(time.time()) - age), secrets.token_hex(8)
        return {
            "Wechatpay-Timestamp": timestamp, "Wechatpay-Nonce": nonce, "Wechatpay-Serial": serial or self.public_key_id,
            "Wechatpay-Signature": signature or _sign(key or _WECHAT_KEY, f"{timestamp}\n{nonce}\n".encode() + body + b"\n"),
        }, body


class FakeAlipay:
    app_id, seller_id = "2021000000000001", "2088000000000001"

    def __init__(self, folder: Path) -> None:
        self.private_key_path = _write_private(_MERCHANT_KEY, folder / "ali-merchant.pem")
        self.public_key_path = _write_public(_ALIPAY_KEY, folder / "ali-public.pem")
        self.trades: dict[str, dict] = {}
        self.refunds: dict[str, dict] = {}
        self.closed: list[str] = []
        self.calls: list[tuple[str, str]] = []
        self.unsigned = False
        self.tamper = False
        self.down = False
        self.refund_sends = 0
        self.bills: dict[str, bytes] = {}
        self.bill_host = "dwbillcenter.alipay.com"
        self.refund_refused = False

    def config(self) -> AlipayConfig:
        return AlipayConfig(
            app_id=self.app_id, seller_id=self.seller_id, private_key_path=self.private_key_path,
            public_key_path=self.public_key_path, notify_url="https://shop.example/api/billing/webhooks/alipay",
        )

    def channel(self) -> Alipay:
        return Alipay(self.config(), transport=httpx.MockTransport(self._handle))

    def _reply(self, method: str, answer: dict) -> httpx.Response:
        key = method.replace(".", "_") + "_response"
        part = json.dumps(answer, ensure_ascii=False)
        signature = _sign(_STRANGER_KEY if self.unsigned else _ALIPAY_KEY, part.encode())
        if self.tamper:
            part = part.replace("10000", "10000 ")
        return httpx.Response(200, content=f'{{"{key}":{part},"sign":"{signature}"}}'.encode(), headers={"Content-Type": "text/html;charset=utf-8"})

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("down", request=request)
        if request.url.host == self.bill_host:
            return httpx.Response(200, content=self.bills[request.url.params["day"]])
        params = dict(request.url.params)
        params.update(parse_qsl(request.content.decode()))
        signature = params.pop("sign")
        assert params["sign_type"] == "RSA2" and params["app_id"] == self.app_id and params["charset"] == "utf-8"
        _verify(_MERCHANT_KEY.public_key(), "&".join(f"{k}={params[k]}" for k in sorted(params)).encode(), signature)
        method, biz = params["method"], json.loads(params["biz_content"])
        self.calls.append((method, biz.get("out_trade_no", "")))
        if method == "alipay.data.dataservice.bill.downloadurl.query":
            assert biz["bill_type"] == "trade"
            if biz["bill_date"] not in self.bills:
                return self._reply(method, {"code": "40004", "sub_code": "isp.bill_not_exist"})
            return self._reply(method, {"code": "10000", "bill_download_url": f"http://{self.bill_host}/f?day={biz['bill_date']}"})
        out = biz.get("out_trade_no")
        if method == "alipay.trade.precreate":
            assert params["notify_url"].startswith("https://") and len(biz["total_amount"].split(".")[1]) == 2
            # As the documentation for this interface states them.
            assert biz["product_code"] == "QR_CODE_OFFLINE" and not set(biz["subject"]) & set("/=&")
            assert not {"timeout_express", "time_expire", "qr_code_timeout_express"} & set(biz)
            self.trades[out] = {"status": None, "total_amount": biz["total_amount"]}
            return self._reply(method, {"code": "10000", "msg": "Success", "out_trade_no": out, "qr_code": f"https://qr.alipay.com/{out}"})
        trade = self.trades.get(out)
        if method == "alipay.trade.query":
            if not trade or not trade["status"]:
                return self._reply(method, {"code": "40004", "msg": "Business Failed", "sub_code": "ACQ.TRADE_NOT_EXIST"})
            return self._reply(method, {
                "code": "10000", "out_trade_no": out, "trade_no": trade.get("trade_no", ""), "trade_status": trade["status"],
                "total_amount": trade["total_amount"], "send_pay_date": "2026-11-05 10:00:00",
            })
        if method == "alipay.trade.close":
            self.closed.append(out)
            if trade and trade["status"]:
                trade["status"] = "TRADE_CLOSED"
                return self._reply(method, {"code": "10000", "out_trade_no": out})
            return self._reply(method, {"code": "40004", "sub_code": "ACQ.TRADE_NOT_EXIST"})
        if method == "alipay.trade.refund":
            self.refund_sends += 1
            record = self.refunds.setdefault(biz["out_request_no"], {"body": biz, "times": 0})
            record["times"] += 1
            return self._reply(method, {"code": "10000", "trade_no": trade["trade_no"], "fund_change": "Y" if record["times"] == 1 else "N"})
        if method == "alipay.trade.fastpay.refund.query":
            done = biz["out_request_no"] in self.refunds
            return self._reply(method, {"code": "10000", "trade_no": trade["trade_no"], **({"refund_status": "REFUND_SUCCESS"} if done else {})})
        raise AssertionError(f"unexpected call {method}")

    def pay(self, out: str) -> None:
        self.trades[out].update(status="TRADE_SUCCESS", trade_no="ali" + out[-20:])

    def notification(self, out: str, *, key=None, event_id="", drop=(), **overrides) -> tuple[dict, bytes]:
        trade = self.trades[out]
        params = {
            "notify_id": event_id or secrets.token_hex(8), "notify_type": "trade_status_sync", "notify_time": "2026-11-05 10:00:01",
            "app_id": self.app_id, "seller_id": self.seller_id, "out_trade_no": out, "trade_no": trade.get("trade_no", ""),
            "total_amount": trade["total_amount"], "trade_status": trade["status"] or "WAIT_BUYER_PAY", "gmt_payment": "2026-11-05 10:00:00",
            "subject": "创作 会员 & 积分", **overrides,
        }
        for name in drop:
            params.pop(name, None)
        signed = dict(params)
        params.update(sign=_sign(key or _ALIPAY_KEY, "&".join(f"{k}={signed[k]}" for k in sorted(signed)).encode()), sign_type="RSA2")
        return {"Content-Type": "application/x-www-form-urlencoded"}, urlencode(params).encode()


STRANGER_KEY = _STRANGER_KEY


def yuan(fen: int) -> str:
    return f"{fen // 100}.{fen % 100:02d}"


def wechat_bill(payments=(), refunds=()) -> bytes:
    """An ALL bill as https://pay.weixin.qq.com/doc/v3/merchant/4013071246 describes it. Rows are (out, wechat no, fen[, refund no])."""
    header = "交易时间,公众账号ID,商户号,特约商户号,设备号,微信订单号,商户订单号,用户标识,交易类型,交易状态,付款银行,货币种类,应结订单金额,代金券金额,微信退款单号,商户退款单号,退款金额,充值券退款金额,退款类型,退款状态,商品名称,商户数据包,手续费,费率,订单金额,申请退款金额,费率备注"
    lines = [header]

    def row(out, number, state, paid, refund_no, refund):
        cells = ["2026-11-04 10:00:00", "wxappid", "1900000001", "0", "", number, out, "openid", "NATIVE", state, "OTHERS", "CNY", yuan(paid), "0.00",
                 "wxr" if refund_no else "0", refund_no or "0", yuan(refund), "0.00", "ORIGINAL" if refund_no else "", "SUCCESS" if refund_no else "",
                 "会员", "", "0.10", "0.60%", yuan(paid), yuan(refund), ""]
        return ",".join(f"`{cell}" for cell in cells)

    lines += [row(out, number, "SUCCESS", fen, None, 0) for out, number, fen in payments]
    lines += [row(out, number, "REFUND", 0, refund_no, fen) for out, number, fen, refund_no in refunds]
    paid, refunded = sum(item[2] for item in payments), sum(item[2] for item in refunds)
    lines.append("总交易单数,应结订单总金额,退款总金额,充值券退款总金额,手续费总金额,订单总金额,申请退款总金额")
    lines.append(f"`{len(payments) + len(refunds)},`{yuan(paid)},`{yuan(refunded)},`0.00,`0.00,`{yuan(paid)},`{yuan(refunded)}")
    return ("\n".join(lines) + "\n").encode()


def alipay_bill(payments=(), refunds=(), *, drop_column=None) -> bytes:
    """A zip with a detail and a summary file in GBK. Rows are (out, alipay no, fen[, refund batch no])."""
    columns = ["支付宝交易号", "商户订单号", "业务类型", "商品名称", "订单金额（元）", "商家实收（元）", "退款批次号", "服务费（元）"]
    lines = ["#支付宝业务明细查询", "#账号：[20880000000000010156]", "#起始日期：[2026年11月04日]", ",".join(columns)]
    for out, number, fen in payments:
        lines.append(f"{number}\t,{out}\t,交易,会员,{yuan(fen)},{yuan(fen)},,-0.10")
    for out, number, fen, batch in refunds:
        lines.append(f"{number}\t,{out}\t,退款,会员,{yuan(fen)},-{yuan(fen)},{batch}\t,0.10")
    lines += ["#-----------------------------------------业务明细列表结束------------------------------------", "#导出时间：[2026-11-05 09:00:00]"]
    text = "\n".join(lines)
    if drop_column:
        text = text.replace(drop_column, "别的列")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("20880000-20261104_业务明细.csv", text.encode("gbk"))
        archive.writestr("20880000-20261104_业务明细(汇总).csv", "#支付宝业务汇总查询\n门店编号,交易订单总笔数\n合计,1\n".encode("gbk"))
    return buffer.getvalue()

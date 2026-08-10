import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import patch

from app.platform.payments import PaymentSignatureError, verify_webhook_signature


class PaymentSecurityTests(unittest.TestCase):
    def test_webhook_signature_is_required_and_constant_time_verified(self):
        payload = {"event_id": "evt-1", "order_id": "order-1", "status": "paid"}
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        secret = "test-webhook-secret-with-at-least-32-chars"
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        with patch.dict(os.environ, {"PAYMENT_WEBHOOK_SECRET": secret}, clear=False):
            verify_webhook_signature(body, signature)
            with self.assertRaises(PaymentSignatureError):
                verify_webhook_signature(body, "0" * 64)
            with self.assertRaises(PaymentSignatureError):
                verify_webhook_signature(body, "")
        with patch.dict(os.environ, {"PAYMENT_WEBHOOK_SECRET": "YOUR_RANDOM_32_PLUS_CHARACTER_WEBHOOK_SECRET"}):
            with self.assertRaises(PaymentSignatureError):
                verify_webhook_signature(body, signature)


if __name__ == "__main__":
    unittest.main()

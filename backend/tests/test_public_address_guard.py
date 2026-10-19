"""The public-host guard: global addresses and a local proxy's fake-IP pool pass, private networks never do."""

import unittest
from unittest.mock import patch

from app import settings
from app.core.model_configuration import _assert_public_addresses


def _resolves_to(address):
    return lambda *args, **kwargs: [(2, 1, 6, "", (address, 443))]


class PublicAddressTests(unittest.TestCase):
    def test_global_and_fake_ip_addresses_pass_and_private_ones_do_not(self):
        with patch.dict("os.environ", {"ALLOW_PROXY_FAKE_IP": "1"}):
            self.assertTrue(settings.is_public_address("8.8.8.8"))
            self.assertTrue(settings.is_public_address("198.18.0.142"))
            self.assertTrue(settings.is_public_address("198.19.255.1"))
            for private in ("127.0.0.1", "10.0.0.5", "172.16.3.4", "192.168.1.2", "169.254.169.254", "::1", "not-an-ip"):
                self.assertFalse(settings.is_public_address(private), private)

    def test_the_fake_ip_pool_is_opt_in_for_production_and_configurable(self):
        with patch.dict("os.environ", {"ALLOW_PROXY_FAKE_IP": "0"}):
            self.assertFalse(settings.is_public_address("198.18.0.142"))
        with patch.object(settings, "is_production", return_value=True), patch.dict("os.environ", {"ALLOW_PROXY_FAKE_IP": ""}):
            self.assertFalse(settings.is_public_address("198.18.0.142"))
        with patch.dict("os.environ", {"ALLOW_PROXY_FAKE_IP": "1", "PROXY_FAKE_IP_CIDR": "28.0.0.0/8"}):
            self.assertTrue(settings.is_public_address("28.0.0.9"))
            self.assertFalse(settings.is_public_address("198.18.0.142"))

    def test_a_provider_host_behind_a_fake_ip_proxy_is_accepted_and_a_lan_one_is_explained(self):
        with patch.dict("os.environ", {"ALLOW_PROXY_FAKE_IP": "1"}), patch("socket.getaddrinfo", _resolves_to("198.18.0.142")):
            _assert_public_addresses("api.deepseek.com")
        with patch("socket.getaddrinfo", _resolves_to("192.168.1.20")):
            with self.assertRaisesRegex(ValueError, "192.168.1.20.*fake-ip"):
                _assert_public_addresses("api.deepseek.com")


if __name__ == "__main__":
    unittest.main()

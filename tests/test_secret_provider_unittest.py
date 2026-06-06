from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from tools import keychain_secret as ks


class SecretProviderTest(unittest.TestCase):
    def test_env_provider_reads_default_names(self) -> None:
        env = {
            "OUROBOROS_SECRET_PROVIDER": "ENV",
            "OUROBOROS_BITFLYER_API_KEY": "k_default",
            "OUROBOROS_BITFLYER_API_SECRET": "s_default",
        }
        with patch.dict(os.environ, env, clear=False):
            k, s, src = ks.read_pair_with_source(
                service="ouroboros.bitflyer",
                account_key="api_key",
                account_secret="api_secret",
            )
        self.assertEqual(k, "k_default")
        self.assertEqual(s, "s_default")
        self.assertEqual(src, "ENV")

    def test_env_provider_reads_custom_account_env_names(self) -> None:
        env = {
            "OUROBOROS_SECRET_PROVIDER": "ENV",
            "MY_API_KEY": "k_custom",
            "MY_API_SECRET": "s_custom",
        }
        with patch.dict(os.environ, env, clear=False):
            k, s, src = ks.read_pair_with_source(
                service="ouroboros.bitflyer",
                account_key="MY_API_KEY",
                account_secret="MY_API_SECRET",
            )
        self.assertEqual(k, "k_custom")
        self.assertEqual(s, "s_custom")
        self.assertEqual(src, "ENV")

    def test_keychain_provider_forces_keychain(self) -> None:
        env = {"OUROBOROS_SECRET_PROVIDER": "KEYCHAIN"}
        with patch.dict(os.environ, env, clear=False):
            with patch.object(ks, "read_generic_password", side_effect=["k_kc", "s_kc"]) as m:
                k, s, src = ks.read_pair_with_source(
                    service="ouroboros.bitflyer",
                    account_key="api_key",
                    account_secret="api_secret",
                )
        self.assertEqual(k, "k_kc")
        self.assertEqual(s, "s_kc")
        self.assertEqual(src, "KEYCHAIN")
        self.assertEqual(m.call_count, 2)

    def test_auto_on_darwin_fallbacks_to_env_when_keychain_fails(self) -> None:
        env = {
            "OUROBOROS_SECRET_PROVIDER": "AUTO",
            "OUROBOROS_BITFLYER_API_KEY": "k_env",
            "OUROBOROS_BITFLYER_API_SECRET": "s_env",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch.object(ks.sys, "platform", "darwin"):
                with patch.object(ks, "read_generic_password", side_effect=ks.KeychainError("kc fail")):
                    k, s, src = ks.read_pair_with_source(
                        service="ouroboros.bitflyer",
                        account_key="api_key",
                        account_secret="api_secret",
                    )
        self.assertEqual(k, "k_env")
        self.assertEqual(s, "s_env")
        self.assertEqual(src, "ENV")

    def test_env_provider_missing_secret_raises(self) -> None:
        env = {"OUROBOROS_SECRET_PROVIDER": "ENV"}
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaises(ks.KeychainError):
                ks.read_pair_with_source(
                    service="ouroboros.bitflyer",
                    account_key="NO_SUCH_KEY",
                    account_secret="NO_SUCH_SECRET",
                )


if __name__ == "__main__":
    unittest.main()

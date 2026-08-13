#!/usr/bin/env python3
"""Redaction tests — stdlib only. Run: python3 test_redact.py

Covers: each high-precision pattern fires; non-mangling of hashes/uuids/prose;
SPECLOOP_REDACT=0 disables; default-on when env unset.

Every secret-like string below is a plain, explicitly-fake mock (FAKE_* plus
filler X's) chosen to match the redaction regexes. None are real secrets.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import redact  # noqa: E402


class RedactTests(unittest.TestCase):
    def setUp(self):
        # most tests want redaction explicitly ON regardless of outer env
        self._prev = os.environ.pop("SPECLOOP_REDACT", None)

    def tearDown(self):
        if self._prev is not None:
            os.environ["SPECLOOP_REDACT"] = self._prev
        else:
            os.environ.pop("SPECLOOP_REDACT", None)

    def test_aws_access_key(self):
        out = redact.redact("config AWS_ACCESS_KEY_ID=AKIAFAKEAWSKEYXXXXXX done")
        self.assertIn("[REDACTED:aws-access-key]", out)
        self.assertNotIn("AKIAFAKEAWSKEYXXXXXX", out)

    def test_github_token(self):
        out = redact.redact("GH_TOKEN=ghp_FAKEGITHUBTOKENXXXXXXXXXXXXXXXXXXXXX")
        self.assertIn("[REDACTED:github-token]", out)
        self.assertNotIn("ghp_FAKEGITHUBTOKENXXXXXXXXXXXXXXXXXXXXX", out)

    def test_stripe_key(self):
        out = redact.redact("key=sk_live_FAKESTRIPEKEYXXXXXXX")
        self.assertIn("[REDACTED:stripe-key]", out)
        self.assertNotIn("sk_live_", out)

    def test_openai_key(self):
        out = redact.redact("client with sk-proj-FAKE_OPENAI_KEY_XXXX here")
        self.assertIn("[REDACTED:openai-key]", out)
        self.assertNotIn("sk-proj-FAKE_OPENAI_KEY_XXXX", out)

    def test_jwt(self):
        tok = "eyJFAKE_JWT_000000.eyJFAKE_JWT_000000.FAKE_JWT_000000"
        out = redact.redact(f"Authorization had {tok} embedded")
        self.assertIn("[REDACTED:jwt]", out)
        self.assertNotIn(tok, out)

    def test_bearer(self):
        out = redact.redact("req.Header.Set('Authorization', 'Bearer FAKE_BEARER_TOKEN_XXXX')")
        self.assertIn("[REDACTED:bearer]", out)
        self.assertNotIn("FAKE_BEARER_TOKEN_XXXX", out)

    def test_url_credentials_redacts_password_only(self):
        out = redact.redact("DATABASE_URL=postgres://appuser:FAKE_DB_PASSWORD@db.host:5432/db")
        self.assertIn("[REDACTED:url-creds]", out)
        self.assertIn("appuser@", out.replace("appuser:[REDACTED:url-creds]@", "appuser@"))
        self.assertNotIn("FAKE_DB_PASSWORD", out)
        # host + port survive
        self.assertIn("db.host:5432", out)

    def test_url_without_credentials_untouched(self):
        s = "see https://example.com/path and http://host:8080/x"
        self.assertEqual(redact.redact(s), s)

    def test_key_assign(self):
        out = redact.redact('options: { api_key: "FAKE_API_KEY_XXXXX" }')
        self.assertIn("[REDACTED:key-assign]", out)
        self.assertNotIn("FAKE_API_KEY_XXXXX", out)

    def test_private_key_block(self):
        pem = ("-----BEGIN FAKE PRIVATE KEY-----\n"
               "FAKE_KEY_CONTENT_DO_NOT_USE_00000000\n"
               "-----END FAKE PRIVATE KEY-----")
        out = redact.redact(f"signing key:\n{pem}\nstored")
        self.assertIn("[REDACTED:private-key]", out)
        self.assertNotIn("BEGIN FAKE PRIVATE KEY", out)
        self.assertNotIn("FAKE_KEY_CONTENT", out)

    # --- non-mangling (false-positive control) ---
    def test_hashes_and_uuids_untouched(self):
        for s in [
            "commit sha 2c26b46b68ffc68ff99b453c1d30413413422d70",
            "sha256 " + "a" * 64,
            "uuid 550e8400-e29b-41d4-a716-446655440000",
            "run id 0d7bfa3e-911d-4e50-a948-3fb2c688df53",
            "score 0.85 and id 05c9f652-ba6c-45a8-b2d4-e052d5cb41ec",
        ]:
            self.assertEqual(redact.redact(s), s, f"mangled: {s}")

    def test_normal_prose_untouched(self):
        s = ("the postgres connection pool timed out after retrying the jwt token "
             "refresh race condition in the auth middleware")
        self.assertEqual(redact.redact(s), s)

    def test_short_values_not_redacted(self):
        # key-assign requires >=16 char value; short values must survive
        self.assertEqual(redact.redact("api_key=abc"), "api_key=abc")
        self.assertEqual(redact.redact('token: "short"'), 'token: "short"')

    # --- config gating ---
    def test_disabled_when_redact_off(self):
        os.environ["SPECLOOP_REDACT"] = "0"
        raw = "key sk-proj-FAKE_OPENAI_KEY_XXXX"
        self.assertEqual(redact.redact(raw), raw)
        os.environ["SPECLOOP_REDACT"] = "off"
        self.assertEqual(redact.redact(raw), raw)

    def test_default_on_when_env_unset(self):
        os.environ.pop("SPECLOOP_REDACT", None)
        out = redact.redact("key sk-proj-FAKE_OPENAI_KEY_XXXX")
        self.assertIn("[REDACTED:openai-key]", out)

    def test_empty_and_none_safe(self):
        self.assertEqual(redact.redact(""), "")
        self.assertIsNone(redact.redact(None))


if __name__ == "__main__":
    unittest.main()

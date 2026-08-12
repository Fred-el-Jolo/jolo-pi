#!/usr/bin/env python3
"""Redaction tests — stdlib only. Run: python3 test_redact.py

Covers: each high-precision pattern fires; non-mangling of hashes/uuids/prose;
SPECLOOP_REDACT=0 disables; default-on when env unset.

Fake-fixture note
-----------------
Every secret-like value below is a deliberately fake mock. Secret scanners
(GitHub push protection included) flag any string matching a provider's token
*shape* — they do not care that a value says "FAKE". So each fixture is a named
constant assembled from fragments: no provider-shaped token appears as a
contiguous literal in this file (scanners read source bytes), yet each
reassembles at runtime into a value that matches the redaction regex under
test. All fail provider validation (invalid checksum / not-issued).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import redact  # noqa: E402

# --- Fake fixtures ---------------------------------------------------------
# Fragmented so no provider token shape is ever a contiguous source literal;
# each reassembles at runtime to a value the redactor must match.
AWS_FAKE_KEY      = "AKIA" + "IOSFODNN7EXAMPLE"            # AWS docs' canonical example
GITHUB_FAKE_PAT   = "ghp" + "_" + "A" * 36                 # bogus body, invalid checksum
STRIPE_FAKE_KEY   = "sk" + "_live_" + "A" * 24             # live prefix, bogus body
OPENAI_FAKE_KEY   = "sk" + "-proj-" + "A" * 21             # proj prefix, bogus body
FAKE_JWT          = (("ey" + "J" + "A" * 10) + "."
                     + ("ey" + "J" + "B" * 10) + "."
                     + ("C" * 10))
BEARER_FAKE_TOKEN = "X" * 24                                # goes after the word "Bearer "
PG_FAKE_PASSWORD  = "X" * 18                               # url-creds password
GENERIC_FAKE_KEY  = "X" * 20                               # key-assign value (>=16 chars)
FAKE_PEM          = "\n".join([
    "-----BEGIN " + "MOCK PRIVATE KEY" + "-----",
    "X" * 40,
    "-----END " + "MOCK PRIVATE KEY" + "-----",
])


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
        out = redact.redact(f"config AWS_ACCESS_KEY_ID={AWS_FAKE_KEY} done")
        self.assertIn("[REDACTED:aws-access-key]", out)
        self.assertNotIn(AWS_FAKE_KEY, out)

    def test_github_token(self):
        out = redact.redact(f"GH_TOKEN={GITHUB_FAKE_PAT}")
        self.assertIn("[REDACTED:github-token]", out)
        self.assertNotIn(GITHUB_FAKE_PAT, out)

    def test_stripe_key(self):
        out = redact.redact(f"key={STRIPE_FAKE_KEY}")
        self.assertIn("[REDACTED:stripe-key]", out)
        self.assertNotIn("sk_live_", out)

    def test_openai_key(self):
        out = redact.redact(f"client with {OPENAI_FAKE_KEY} here")
        self.assertIn("[REDACTED:openai-key]", out)
        self.assertNotIn(OPENAI_FAKE_KEY, out)

    def test_jwt(self):
        out = redact.redact(f"Authorization had {FAKE_JWT} embedded")
        self.assertIn("[REDACTED:jwt]", out)
        self.assertNotIn(FAKE_JWT, out)

    def test_bearer(self):
        out = redact.redact(
            f"req.Header.Set('Authorization', 'Bearer {BEARER_FAKE_TOKEN}')")
        self.assertIn("[REDACTED:bearer]", out)
        self.assertNotIn(BEARER_FAKE_TOKEN, out)

    def test_url_credentials_redacts_password_only(self):
        out = redact.redact(
            f"DATABASE_URL=postgres://appuser:{PG_FAKE_PASSWORD}@db.host:5432/db")
        self.assertIn("[REDACTED:url-creds]", out)
        self.assertIn("appuser@", out.replace("appuser:[REDACTED:url-creds]@", "appuser@"))
        self.assertNotIn(PG_FAKE_PASSWORD, out)
        # host + port survive
        self.assertIn("db.host:5432", out)

    def test_url_without_credentials_untouched(self):
        s = "see https://example.com/path and http://host:8080/x"
        self.assertEqual(redact.redact(s), s)

    def test_key_assign(self):
        out = redact.redact(f'options: {{ api_key: "{GENERIC_FAKE_KEY}" }}')
        self.assertIn("[REDACTED:key-assign]", out)
        self.assertNotIn(GENERIC_FAKE_KEY, out)

    def test_private_key_block(self):
        out = redact.redact(f"signing key:\n{FAKE_PEM}\nstored")
        self.assertIn("[REDACTED:private-key]", out)
        self.assertNotIn("BEGIN MOCK PRIVATE KEY", out)
        self.assertNotIn("MOCK PRIVATE KEY", out)

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
        raw = f"key {OPENAI_FAKE_KEY}"
        self.assertEqual(redact.redact(raw), raw)
        os.environ["SPECLOOP_REDACT"] = "off"
        self.assertEqual(redact.redact(raw), raw)

    def test_default_on_when_env_unset(self):
        os.environ.pop("SPECLOOP_REDACT", None)
        out = redact.redact(f"key {OPENAI_FAKE_KEY}")
        self.assertIn("[REDACTED:openai-key]", out)

    def test_empty_and_none_safe(self):
        self.assertEqual(redact.redact(""), "")
        self.assertIsNone(redact.redact(None))


if __name__ == "__main__":
    unittest.main()

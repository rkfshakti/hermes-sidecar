from __future__ import annotations

import os

from sidecar import pairing as token


def test_create_read_rotate(tmp_path):
    first = token.load_or_create_token(tmp_path)
    assert len(first) >= 32
    assert token.read_token(tmp_path) == first
    second = token.rotate_token(tmp_path)
    assert second != first
    assert token.read_token(tmp_path) == second


def test_token_file_is_private(tmp_path):
    token.load_or_create_token(tmp_path)
    mode = os.stat(token.token_path(tmp_path)).st_mode & 0o777
    assert mode == 0o600


def test_tokens_equal_is_constant_time_and_length_safe():
    assert token.tokens_equal("abc", "abc")
    assert not token.tokens_equal("abc", "abd")
    assert not token.tokens_equal("", "abc")
    assert not token.tokens_equal("abc", "")


def test_mask_token():
    assert token.mask_token("") == "(not set)"
    assert token.mask_token("abcdefghijklmnop").startswith("abcd")
    assert token.mask_token("abcdefghijklmnop").endswith("mnop")

"""Ядро серийных номеров: эталонные векторы из JS-прототипа и свойства кода."""

import json
import os
import random

from app import serials
from app.serials import (
    ALPHABET, Fields, check_symbol, decode_serial, encode_serial,
    key_fingerprint, key_to_rounds, normalize,
)

VECTORS = json.load(open(os.path.join(os.path.dirname(__file__), "vectors.json")))


def test_round_keys_match_js():
    for key, rounds in VECTORS["meta"]["rounds"].items():
        assert key_to_rounds(key) == rounds


def test_encode_matches_js_vectors():
    for v in VECTORS["vectors"]:
        assert encode_serial(Fields(**v["fields"]), v["key"]) == v["code"]


def test_decode_matches_js_vectors():
    for v in VECTORS["vectors"]:
        dec = decode_serial(v["code"], v["key"])
        assert dec.ok and dec.fields == Fields(**v["fields"])


def test_roundtrip_random():
    rnd = random.Random(42)
    key = "deadbeefcafebabe0123456789abcdef"
    for _ in range(500):
        f = Fields(type=rnd.randrange(32), color=rnd.randrange(64), month=rnd.randrange(256),
                   place=rnd.randrange(16), seq=rnd.randrange(4096))
        code = encode_serial(f, key)
        assert len(code) == 8 and all(ch in ALPHABET for ch in code)
        dec = decode_serial(code, key)
        assert dec.ok and dec.fields == f


def test_check_symbol_catches_single_error():
    key = "0123456789abcdef0123456789abcdef"
    code = encode_serial(Fields(type=1, color=2, month=7, place=1, seq=42), key)
    for pos in range(8):
        for ch in ALPHABET:
            if ch == code[pos]:
                continue
            mutated = code[:pos] + ch + code[pos + 1:]
            assert not decode_serial(mutated, key).ok, f"missed single error at {pos}: {mutated}"


def test_check_symbol_catches_adjacent_transposition():
    key = "0123456789abcdef0123456789abcdef"
    rnd = random.Random(7)
    for _ in range(100):
        f = Fields(type=rnd.randrange(32), color=rnd.randrange(64), month=rnd.randrange(256),
                   place=rnd.randrange(16), seq=rnd.randrange(4096))
        code = encode_serial(f, key)
        for i in range(7):
            if code[i] == code[i + 1]:
                continue
            swapped = code[:i] + code[i + 1] + code[i] + code[i + 2:]
            assert not decode_serial(swapped, key).ok, f"missed transposition at {i}: {code}->{swapped}"


def test_normalize_confusable_characters():
    assert normalize("il1 o0-u v") == "11100VV"
    assert normalize("abcd-efgh") == "ABCDEFGH"
    assert normalize("  x9 Z2\t") == "X9Z2"


def test_decode_reasons():
    key = "0123456789abcdef0123456789abcdef"
    assert decode_serial("ABC", key).reason == "length"
    good = encode_serial(Fields(type=0, color=0, month=0, place=0, seq=1), key)
    bad_check = good[:7] + ALPHABET[(ALPHABET.index(good[7]) + 1) % 32]
    assert decode_serial(bad_check, key).reason == "check"


def test_different_keys_give_different_codes():
    f = Fields(type=1, color=1, month=1, place=1, seq=1)
    codes = {encode_serial(f, k) for k in VECTORS["meta"]["rounds"]}
    assert len(codes) == len(VECTORS["meta"]["rounds"])


def test_neighbour_serials_look_unrelated():
    key = "0123456789abcdef0123456789abcdef"
    a = encode_serial(Fields(type=1, color=2, month=7, place=1, seq=100), key)
    b = encode_serial(Fields(type=1, color=2, month=7, place=1, seq=101), key)
    assert sum(x == y for x, y in zip(a, b)) < 6  # почти все знаки различны


def test_key_fingerprint_format():
    fp = key_fingerprint("0123456789abcdef0123456789abcdef")
    assert len(fp) == 9 and fp[4] == "-"
    assert fp == key_fingerprint("0123456789abcdef0123456789abcdef")  # детерминирован


def test_month_label():
    assert serials.month_label(0) == "Jan 2026"
    assert serials.month_label(7) == "Aug 2026"
    assert serials.month_label(12) == "Jan 2027"

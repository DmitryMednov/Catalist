"""Ядро серийных номеров Catalist.

Точный порт логики из прототипа (hallmarksuite.tsx), бит-в-бит совместимый
с JavaScript-реализацией: номера, выданные прототипом на том же ключе,
декодируются здесь, и наоборот. Совместимость закреплена эталонными
векторами в tests/vectors.json, сгенерированными из исходного JS-кода.

Формат номера: 8 знаков Crockford Base32 (без I, L, O, U).
Семь знаков несут 35 бит полезной нагрузки, восьмой — контрольный
(GF(32), ловит одиночную ошибку и перестановку соседних знаков).

Поля payload:
    type  (5 бит, 32)   — тип изделия
    color (6 бит, 64)   — цвет
    month (8 бит, 256)  — месяцы с января 2026
    place (4 бита, 16)  — площадка
    seq   (12 бит, 4096)— порядковый номер издания

Payload перемешивается несбалансированной сетью Фейстеля (4 раунда,
18/17 бит) на 128-битном ключе — соседние номера выглядят несвязанными.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
BASE_YEAR = 2026
CAP = {"type": 32, "color": 64, "month": 256, "place": 16, "seq": 4096}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

_M32 = 0xFFFFFFFF


def _imul(a: int, b: int) -> int:
    """32-битное умножение как Math.imul(a, b) >>> 0 в JS."""
    return (a * b) & _M32


def key_to_rounds(key: str) -> list[int]:
    """FNV-1a по символам ключа → 4 раундовых подключа."""
    h = 0x811C9DC5
    for ch in key:
        h ^= ord(ch)
        h = _imul(h, 0x01000193)
    rk = []
    for _ in range(4):
        h = _imul(h ^ (h >> 13), 0x9E3779B1)
        rk.append(h)
    return rk


def _f(v: int, k: int) -> int:
    h = _imul((v ^ k) & _M32, 0x9E3779B1)
    h ^= h >> 15
    h = _imul(h, 0x85EBCA6B)
    h ^= h >> 13
    return h & _M32


def scramble(v: int, rk: list[int], forward: bool) -> int:
    """Несбалансированная сеть Фейстеля: 35 бит = A(18) | B(17), 4 раунда."""
    a, b = 18, 17
    A, B = v // 131072, v % 131072
    if forward:
        for r in range(4):
            A, B = B, (A ^ (_f(B, rk[r]) % (1 << a))) % (1 << a)
            a, b = b, a
    else:
        sizes = []
        aa, bb = 18, 17
        for _ in range(4):
            sizes.append((aa, bb))
            aa, bb = bb, aa
        for r in range(3, -1, -1):
            ra = sizes[r][0]
            A, B = (B ^ (_f(A, rk[r]) % (1 << ra))) % (1 << ra), A
    return A * 131072 + B


def _gf_mul(a: int, b: int) -> int:
    """Умножение в GF(32), многочлен x^5 + x^2 + 1."""
    p = 0
    for _ in range(5):
        if b & 1:
            p ^= a
        b >>= 1
        hi = a & 16
        a = (a << 1) & 31
        if hi:
            a ^= 5
    return p


def check_symbol(symbols: list[int]) -> int:
    """Контрольный знак: ловит одиночную ошибку и перестановку соседних."""
    w, c = 1, 0
    for s in symbols:
        w = _gf_mul(w, 2)
        c ^= _gf_mul(w, s)
    return c


@dataclass(frozen=True)
class Fields:
    type: int
    color: int
    month: int
    place: int
    seq: int

    def as_dict(self) -> dict:
        return asdict(self)


def pack(f: Fields) -> int:
    return ((((f.type * CAP["color"] + f.color) * CAP["month"] + f.month)
             * CAP["place"] + f.place) * CAP["seq"]) + f.seq


def unpack(v: int) -> Fields:
    seq = v % CAP["seq"]; v //= CAP["seq"]
    place = v % CAP["place"]; v //= CAP["place"]
    month = v % CAP["month"]; v //= CAP["month"]
    color = v % CAP["color"]; v //= CAP["color"]
    return Fields(type=v % CAP["type"], color=color, month=month, place=place, seq=seq)


def encode_serial(fields: Fields, key: str) -> str:
    v = scramble(pack(fields), key_to_rounds(key), True)
    syms = [0] * 7
    x = v
    for i in range(6, -1, -1):
        syms[i] = x % 32
        x //= 32
    return "".join(ALPHABET[s] for s in syms) + ALPHABET[check_symbol(syms)]


def normalize(raw: str) -> str:
    """Приведение ввода: верхний регистр, только [0-9A-Z], I/L→1, O→0, U→V."""
    s = "".join(ch for ch in str(raw).upper() if ch.isascii() and (ch.isdigit() or "A" <= ch <= "Z"))
    return s.replace("I", "1").replace("L", "1").replace("O", "0").replace("U", "V")


@dataclass(frozen=True)
class Decoded:
    ok: bool
    norm: str
    fields: Fields | None = None
    reason: str | None = None  # length | alphabet | check


def decode_serial(raw: str, key: str) -> Decoded:
    s = normalize(raw)
    if len(s) != 8:
        return Decoded(ok=False, norm=s, reason="length")
    idx = [ALPHABET.find(ch) for ch in s]
    if any(i < 0 for i in idx):
        return Decoded(ok=False, norm=s, reason="alphabet")
    data = idx[:7]
    if check_symbol(data) != idx[7]:
        return Decoded(ok=False, norm=s, reason="check")
    v = 0
    for i in range(7):
        v = v * 32 + data[i]
    return Decoded(ok=True, norm=s, fields=unpack(scramble(v, key_to_rounds(key), False)))


def month_label(m: int) -> str:
    return f"{MONTHS[m % 12]} {BASE_YEAR + m // 12}"


def slot_of(f: Fields) -> str:
    """Ключ занятости комбинации — тот же формат, что в прототипе."""
    return f"{f.type}-{f.color}-{f.month}-{f.place}-{f.seq}"


def random_key() -> str:
    """128-битный ключ шифрования, hex — как randomKey() прототипа."""
    import secrets
    return secrets.token_hex(16)


def key_fingerprint(key: str) -> str:
    """Отпечаток ключа XXXX-XXXX — как fingerprint() прототипа."""
    h = 0x811C9DC5
    for ch in "hallmark:fp:" + key:
        h ^= ord(ch)
        h = _imul(h, 0x01000193)
    for _ in range(5000):
        h = _imul(h ^ (h >> 13), 0x9E3779B1)
    hx = format(h, "x").upper().rjust(8, "0")
    return hx[:4] + "-" + hx[4:8]

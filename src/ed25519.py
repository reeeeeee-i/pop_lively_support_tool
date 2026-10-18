"""Ed25519 署名 (RFC 8032) の純 Python 実装

自動更新 (ツール本体・曲リストの JSON) の改ざん検出に使う。標準ライブラリだけで動くので、
配布物に暗号ライブラリを足さずに済む。RFC 8032 の参考実装に沿っており、RFC のテストベクターと、
別実装 (cryptography) との突き合わせで確認している (tests/test_signing.py)。

verify はアプリ (署名の検証) で、sign / secret_to_public は tools/sign_release.py (署名の作成) で使う。
署名の作成は開発者の手元でだけ行う。この実装は処理時間が一定ではないため、信頼できない相手と
やり取りする場面 (サーバーでの署名など) では使わないこと。
"""
from __future__ import annotations

import hashlib

_P = 2 ** 255 - 19
_Q = 2 ** 252 + 27742317777372353535851937790883648493   # 基点の位数 (L)


def _sha512(data: bytes) -> bytes:
    return hashlib.sha512(data).digest()


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


_D = -121665 * _inv(121666) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _sha512_modq(data: bytes) -> int:
    return int.from_bytes(_sha512(data), "little") % _Q


# 点は拡張座標 (X, Y, Z, T) で表す
def _add(p: tuple, q: tuple) -> tuple:
    a = (p[1] - p[0]) * (q[1] - q[0]) % _P
    b = (p[1] + p[0]) * (q[1] + q[0]) % _P
    c = 2 * p[3] * q[3] * _D % _P
    d = 2 * p[2] * q[2] % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(s: int, p: tuple) -> tuple:
    q = (0, 1, 1, 0)   # 単位元
    while s > 0:
        if s & 1:
            q = _add(q, p)
        p = _add(p, p)
        s >>= 1
    return q


def _equal(p: tuple, q: tuple) -> bool:
    if (p[0] * q[2] - q[0] * p[2]) % _P != 0:
        return False
    return (p[1] * q[2] - q[1] * p[2]) % _P == 0


def _recover_x(y: int, sign: int) -> int | None:
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_GY = 4 * _inv(5) % _P
_GX = _recover_x(_GY, 0)
_G = (_GX, _GY, 1, _GX * _GY % _P)


def _compress(p: tuple) -> bytes:
    zinv = _inv(p[2])
    x, y = p[0] * zinv % _P, p[1] * zinv % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(data: bytes) -> tuple | None:
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


def _expand(secret: bytes) -> tuple[int, bytes]:
    if len(secret) != 32:
        raise ValueError("秘密鍵は 32 バイトです")
    h = _sha512(secret)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def secret_to_public(secret: bytes) -> bytes:
    """秘密鍵 (32 バイトのシード) から公開鍵 (32 バイト) を求める。"""
    a, _ = _expand(secret)
    return _compress(_mul(a, _G))


def sign(secret: bytes, message: bytes) -> bytes:
    """message に署名する (64 バイト)。"""
    a, prefix = _expand(secret)
    public = _compress(_mul(a, _G))
    r = _sha512_modq(prefix + message)
    r_point = _compress(_mul(r, _G))
    h = _sha512_modq(r_point + public + message)
    s = (r + h * a) % _Q
    return r_point + int.to_bytes(s, 32, "little")


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    """署名が正しければ True。形式が不正な入力も False を返す (例外にしない)。"""
    if len(public) != 32 or len(signature) != 64:
        return False
    a_point = _decompress(public)
    r_point = _decompress(signature[:32])
    if a_point is None or r_point is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _Q:   # 署名の可鍛性 (別のバイト列で同じ署名になるもの) を許さない
        return False
    h = _sha512_modq(signature[:32] + public + message)
    return _equal(_mul(s, _G), _add(r_point, _mul(h, a_point)))

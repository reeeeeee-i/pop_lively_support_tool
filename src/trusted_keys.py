"""配布物の署名を検証する公開鍵 (信頼の起点)

{key_id: 公開鍵 (32 バイトの 16 進)}。key_id は src/signing.py の key_id() の値。
鍵を更新するときは、新しい鍵をここへ追加したバージョンを、旧い鍵で署名して配布してから、
新しい鍵での署名に切り替える (旧い鍵は、全員が更新し終えてから削除する)。
鍵の作り方・署名の手順は README の「署名」を参照。
"""

TRUSTED_PUBLIC_KEYS: dict[str, str] = {
    "1b082662baf04d60": "5edecb3dc56ffcf25e6a58efb0eb08f965127ebd6b161ca81c3ac00561d3c271",
}

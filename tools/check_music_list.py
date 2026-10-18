"""再生成した曲リストが、前の曲リストと比べて異常でないか確かめる (自動更新用)

    python tools/check_music_list.py 前の.json 新しい.json

Wiki の構成が変わってパースが壊れた曲リストを、そのまま配信しないための検査。異常があれば終了コード 1 で終わる。
"""
import json
import sys

MAX_DROPPED = 10      # 前にあって今回無い曲の上限
MIN_RATIO = 0.98      # 曲数が前の何割を下回ったら異常とするか
REQUIRED = ("music_id", "title", "artist", "ver")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    old, new = load(sys.argv[1]), load(sys.argv[2])
    problems = []
    if len(new) < len(old) * MIN_RATIO:
        problems.append(f"曲数が減りすぎています: {len(old)} -> {len(new)}")
    new_ids = [s.get("music_id") for s in new]
    if len(set(new_ids)) != len(new_ids):
        problems.append("music_id が重複しています")
    dropped = {s["music_id"] for s in old} - set(new_ids)
    if len(dropped) > MAX_DROPPED:
        problems.append(f"なくなった曲が多すぎます: {len(dropped)} 曲")
    bad = [s for s in new if not all(s.get(k) for k in REQUIRED)]
    if bad:
        problems.append(f"必須の項目が空の曲があります: {len(bad)} 曲 (例: {bad[0]})")
    nolevel = [s for s in new if not any(s.get(k) for k in ("easy", "normal", "hyper", "ex"))]
    if len(nolevel) > len(old) * 0.02:
        problems.append(f"レベルが 1 つも取れていない曲が多すぎます: {len(nolevel)} 曲")
    print(f"曲数 {len(old)} -> {len(new)} / なくなった曲 {len(dropped)} / レベル無し {len(nolevel)}")
    if problems:
        for p in problems:
            print("異常:", p)
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()

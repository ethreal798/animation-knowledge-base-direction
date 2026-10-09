"""补采缺失作品: 枚举当季全部 TV 动画 ID, 与本地文件对比, 只拉缺失项。
用法: python scripts/retry_missing.py <year> <season>
"""
import json
import os
import sys
import time

from collect_anilist import LIST_Q, DETAIL_Q, gql

API = "https://graphql.anilist.co"


def main():
    year, season = int(sys.argv[1]), sys.argv[2]
    out_dir = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "anilist")

    ids = []
    page = 1
    while True:
        data = gql(LIST_Q, {"year": year, "season": season, "page": page, "perPage": 50})
        media = data["Page"]["media"]
        ids += [m["id"] for m in media]
        if len(media) < 50:
            break
        page += 1
        time.sleep(1)
    print(f"enumerated {len(ids)} works")

    have = set()
    for fn in os.listdir(out_dir):
        if fn.startswith(f"{year}_{season}_"):
            have.add(int(fn.split("_")[2].split(".")[0]))
    missing = [i for i in ids if i not in have]
    print(f"local={len(have)} missing={len(missing)}")

    ok, fail = 0, 0
    for i, mid in enumerate(missing):
        try:
            d = gql(DETAIL_Q, {"id": mid})
            m = d["Media"]
            out = os.path.join(out_dir, f"{year}_{season}_{mid}.json")
            with open(out, "w", encoding="utf-8") as f:
                json.dump(m, f, ensure_ascii=False, indent=1)
            ok += 1
            print(f"[{i+1}/{len(missing)}] saved {m['title']['romaji']} "
                  f"| staff={len(m['staff']['edges'])} cast={len(m['characters']['edges'])}")
        except Exception as e:
            fail += 1
            print(f"[{i+1}/{len(missing)}] FAILED id={mid}: {e}")
        time.sleep(1)
    print(f"done ok={ok} fail={fail}")


if __name__ == "__main__":
    main()

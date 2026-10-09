"""AniList 采集脚本：按季度枚举 TV 动画，逐部拉取 title/studio/staff/cast 详情。
用法: python collect_anilist.py <year> <season> [max_pages]
试点: python collect_anilist.py 2025 WINTER 2
输出: data/raw/anilist/<year>_<season>_<id>.json
"""
import json
import os
import sys
import time

import requests

API = "https://graphql.anilist.co"
HEADERS = {"User-Agent": "linkto-rag-exam/0.1 (dev)", "Content-Type": "application/json",
           "Accept": "application/json"}

LIST_Q = """
query ($year: Int, $season: MediaSeason, $page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    media(type: ANIME, format: TV, seasonYear: $year, season: $season, sort: POPULARITY_DESC) {
      id
    }
  }
}"""

DETAIL_Q = """
query ($id: Int) {
  Media(id: $id, type: ANIME) {
    id
    title { romaji english native }
    startDate { year month day }
    endDate { year month day }
    season
    seasonYear
    format
    episodes
    duration
    studios(isMain: true) { nodes { name } }
    staff(sort: RELEVANCE) {
      edges { role node { name { full native } } }
    }
    characters(role: MAIN, perPage: 30) {
      edges {
        node { name { full native } }
        voiceActors(language: JAPANESE) { name { full native } }
      }
    }
  }
}"""


def gql(query, variables, retries=3):
    for i in range(retries):
        try:
            r = requests.post(API, json={"query": query, "variables": variables},
                              headers=HEADERS, timeout=30)
            if r.status_code == 200:
                data = r.json()
                if data.get("errors"):
                    raise RuntimeError(f"graphql errors: {data['errors']}")
                return data["data"]
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 60))
                print(f"rate limited, wait {wait}s")
                time.sleep(wait)
                continue
            raise RuntimeError(f"http {r.status_code}: {r.text[:200]}")
        except Exception as e:
            if i == retries - 1:
                raise
            print(f"retry {i+1}: {e}")
            time.sleep(2 ** i * 2)


def main():
    year, season = int(sys.argv[1]), sys.argv[2]
    max_pages = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    per_page = 30

    out_dir = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "anilist")
    os.makedirs(out_dir, exist_ok=True)

    ids = []
    page = 1
    while page <= max_pages:
        data = gql(LIST_Q, {"year": year, "season": season, "page": page, "perPage": per_page})
        media = data["Page"]["media"]
        ids += [m["id"] for m in media]
        if len(media) < per_page:
            break
        page += 1
        time.sleep(1)
    print(f"[{year} {season}] enumerated {len(ids)} works")

    ok, fail = 0, 0
    for i, mid in enumerate(ids):
        try:
            d = gql(DETAIL_Q, {"id": mid})
            m = d["Media"]
            out = os.path.join(out_dir, f"{year}_{season}_{mid}.json")
            with open(out, "w", encoding="utf-8") as f:
                json.dump(m, f, ensure_ascii=False, indent=1)
            ok += 1
            print(f"[{i+1}/{len(ids)}] saved {m['title']['romaji']} "
                  f"| staff={len(m['staff']['edges'])} cast={len(m['characters']['edges'])}")
        except Exception as e:
            fail += 1
            print(f"[{i+1}/{len(ids)}] FAILED id={mid}: {e}")
        time.sleep(1.2)

    print(f"done ok={ok} fail={fail}")


if __name__ == "__main__":
    main()

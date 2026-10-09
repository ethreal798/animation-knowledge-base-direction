"""评测集构建: 从 works.jsonl 自动生成可校验 QA 对 -> data/eval_set.jsonl
题型: 导演 / 制作公司 / 角色声优 / 季度番组
期望答案存"包含任一即算对"的关键词列表(日文名+罗马字), 用于规则匹配评估。
"""
import json
import os
import random
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(BASE, ".."))

CORE_QUESTIONS = {
    "Director": ("导演是谁", "导演"),
    "Chief Director": ("总导演是谁", "总导演"),
    "Series Composition": ("系列构成是谁", "系列构成"),
    "Character Design": ("角色设计是谁", "角色设计"),
}
QUOTA = {"director": 35, "studio": 25, "cast": 25, "season": 5}
random.seed(42)


def pick_works(works, season_year):
    return [w for w in works if w.get("seasonYear") == season_year]


def main():
    with open(os.path.join(ROOT, "data", "processed", "works.jsonl"), encoding="utf-8") as f:
        works = [json.loads(line) for line in f if line.strip()]
    random.shuffle(works)

    items = []
    used = set()
    count = Counter()

    def budget(t):
        return count[t] < QUOTA[t]

    # 1) 导演/主创题
    for w in works:
        if not budget("director"):
            break
        core = [s for s in w["staff"] if s["role_zh"] == "导演"]
        if not core:
            continue
        q_cn, q_dim = CORE_QUESTIONS["Director"]
        title = w["titles"]["native"]
        if (title, q_dim) in used:
            continue
        keys = [s["name_jp"] for s in core if s["name_jp"]] + [s["name_romaji"] for s in core if s["name_romaji"]]
        used.add((title, q_dim))
        count["director"] += 1
        items.append({
            "id": f"d{len(items):03d}", "type": "director",
            "question": f"《{title}》的{q_cn}？", "expected": keys,
            "work_id": w["id"], "title": title,
            "season": f"{w['seasonYear']}{w['season']}",
        })

    # 2) 制作公司题
    for w in works:
        if not budget("studio"):
            break
        if not w["studios"]:
            continue
        title = w["titles"]["native"]
        if (title, "studio") in used:
            continue
        used.add((title, "studio"))
        count["studio"] += 1
        items.append({
            "id": f"s{len(items):03d}", "type": "studio",
            "question": f"《{title}》是由哪个动画公司制作的？", "expected": w["studios"],
            "work_id": w["id"], "title": title,
            "season": f"{w['seasonYear']}{w['season']}",
        })

    # 3) 角色声优题
    for w in works:
        if not budget("cast"):
            break
        for c in w["characters"]:
            if not c.get("voice_actors"):
                continue
            cn = c["name_jp"] or c["name"]
            va = c["voice_actors"][0]
            vkeys = ([va["name_jp"]] if va["name_jp"] else []) + ([va["name_romaji"]] if va["name_romaji"] else [])
            if not vkeys:
                continue
            count["cast"] += 1
            items.append({
                "id": f"c{len(items):03d}", "type": "cast",
                "question": f"动画《{w['titles']['native']}》中角色「{cn}」的配音声优是谁？",
                "expected": vkeys,
                "work_id": w["id"], "title": w["titles"]["native"],
                "season": f"{w['seasonYear']}{w['season']}",
            })
            break

    # 4) 季度番组题: 各季度取一例
    for yy, ss in [(2025, "WINTER"), (2025, "SPRING"), (2025, "SUMMER"),
                   (2025, "FALL"), (2026, "WINTER")]:
        if not budget("season"):
            break
        pool = [w for w in works if w.get("seasonYear") == yy and w.get("season") == ss]
        if not pool:
            continue
        count["season"] += 1
        items.append({
            "id": f"q{len(items):03d}", "type": "season",
            "question": f"{yy}年{ {'WINTER':'冬季','SPRING':'春季','SUMMER':'夏季','FALL':'秋季'}[ss] }有哪些动画？请列举3部。",
            "expected": [w["titles"]["native"] for w in pool],
            "work_id": pool[0]["id"], "title": pool[0]["titles"]["native"],
            "season": f"{yy}{ss}",
        })

    random.shuffle(items)
    out = os.path.join(ROOT, "data", "eval_set.jsonl")
    with open(out, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    print("eval items:", len(items), Counter(i["type"] for i in items))


if __name__ == "__main__":
    main()

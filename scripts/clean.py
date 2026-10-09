"""清洗与实体归一: 原始 AniList JSON -> data/processed/works.jsonl
规则: 名字去空白、staff 去重、角色英文->中文映射、null 日文名保留罗马字。
"""
import glob
import json
import os
import re

ROLE_ZH = {
    "Director": "导演", "Chief Director": "总导演", "Assistant Director": "副导演",
    "Series Composition": "系列构成", "Character Design": "角色设计",
    "Sub Character Design": "次要角色设计", "Chief Animation Director": "总作画监督",
    "Animation Director": "作画监督", "Art Director": "美术监督", "Art Design": "美术设计",
    "Color Design": "色彩设计", "Director of Photography": "摄影监督", "Editing": "剪辑",
    "Sound Director": "音响监督", "Music": "音乐", "Original Story": "原作",
    "Original Character Design": "原作角色设计", "Prop Design": "道具设计",
    "Theme Song Performance (OP)": "片头曲演唱", "Theme Song Performance (ED)": "片尾曲演唱",
    "Theme Song Composition": "主题曲作曲", "Theme Song Lyrics": "主题曲作词",
    "Theme Song Arrangement": "主题曲编曲", "Sound Effects": "音效",
    "Mechanical Design": "机械设计", "Unit Director": "演出", "Planning": "企划",
    "Producer": "制片人", "Animation Production": "动画制作",
}


def norm_name(s):
    return re.sub(r"\s+", "", (s or "")).strip()


def main():
    base = os.path.join(os.path.dirname(__file__), "..")
    files = sorted(glob.glob(os.path.join(base, "data", "raw", "anilist", "*.json")))
    print("raw files:", len(files))

    out = []
    for fp in files:
        with open(fp, encoding="utf-8") as f:
            m = json.load(f)
        title = m.get("title") or {}

        staff = []
        for e in m.get("staff", {}).get("edges", []):
            nm = e.get("node", {}).get("name", {})
            jp = norm_name(nm.get("native"))
            rom = norm_name(nm.get("full"))
            if not jp and not rom:
                continue
            role = e.get("role", "")
            staff.append({"role_en": role, "role_zh": ROLE_ZH.get(role, role),
                          "name_jp": jp, "name_romaji": rom})
        seen = set()
        staff_dedup = []
        for s in staff:
            k = (s["role_en"], s["name_jp"] or s["name_romaji"])
            if k not in seen:
                seen.add(k)
                staff_dedup.append(s)

        chars = []
        for e in m.get("characters", {}).get("edges", []):
            cn = e.get("node", {}).get("name", {})
            vas = [{"name_jp": norm_name(va.get("name", {}).get("native")),
                    "name_romaji": norm_name(va.get("name", {}).get("full"))}
                   for va in e.get("voiceActors", [])]
            chars.append({"name": norm_name(cn.get("full")), "name_jp": norm_name(cn.get("native")),
                          "voice_actors": vas})

        rec = {
            "id": m["id"],
            "titles": {"native": norm_name(title.get("native")), "romaji": norm_name(title.get("romaji")),
                       "english": norm_name(title.get("english"))},
            "aliases": [],
            "season": m.get("season"), "seasonYear": m.get("seasonYear"),
            "episodes": m.get("episodes"),
            "studios": [n["name"] for n in m.get("studios", {}).get("nodes", [])],
            "staff": staff_dedup,
            "characters": chars,
            "source": "anilist",
        }
        out.append(rec)

    out_path = os.path.join(base, "data", "processed", "works.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        for rec in out:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # 统计
    n_staff = sum(len(r["staff"]) for r in out)
    n_char = sum(len(r["characters"]) for r in out)
    n_no_jp = sum(1 for r in out for s in r["staff"] if not s["name_jp"])
    print(f"works={len(out)} staff_total={n_staff} char_total={n_char} staff_without_jp={n_no_jp}")
    print("sample:", json.dumps(out[0], ensure_ascii=False)[:600])


if __name__ == "__main__":
    main()

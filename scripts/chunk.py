"""分块: works.jsonl -> data/processed/chunks.jsonl
按 作品×维度 分块: overview / studio / staff_核心 / staff_其余 / cast
每块文本以作品名(多语言)开头，便于检索时按作品名命中。
"""
import json
import os

CORE_ROLES = {"导演", "总导演", "系列构成", "角色设计", "总作画监督", "音乐", "音响监督"}


def title_str(r):
    t = r["titles"]
    parts = [t["native"], t["romaji"], t["english"], *[a for a in r["aliases"] if a]]
    return " | ".join([p for p in parts if p])


def staff_line(s):
    jp = s["name_jp"] or s["name_romaji"]
    if s["name_jp"] and s["name_romaji"] and s["name_romaji"] != s["name_jp"]:
        jp = f"{s['name_jp']}（{s['name_romaji']}）"
    return f"{s['role_zh']}: {jp}"


def build_chunks(r):
    t = r["titles"]
    season_label = f"{r['seasonYear']}年{r['season']}季" if r.get("season") else ""
    chunks = []

    # overview
    lines = [f"《{t['native']}》（{t['romaji']}）"]
    if t.get("english"):
        lines[0] += f" / {t['english']}"
    meta = [season_label]
    if r.get("episodes"):
        meta.append(f"全{r['episodes']}话")
    if r.get("studios"):
        meta.append("制作公司：" + "、".join(r["studios"]))
    lines.append("；".join([m for m in meta if m]))
    chunks.append(("overview", "。".join(lines)))

    # studio
    if r.get("studios"):
        chunks.append(("studio", f"《{t['native']}》的制作公司为：" + "、".join(r["studios"]) + "。"))

    # staff 核心/其余
    core = [s for s in r["staff"] if s["role_zh"] in CORE_ROLES]
    rest = [s for s in r["staff"] if s["role_zh"] not in CORE_ROLES]
    if core:
        chunks.append(("staff_核心", f"《{t['native']}》的核心主创：" + "；".join(staff_line(s) for s in core) + "。"))
    if rest:
        chunks.append(("staff_其余", f"《{t['native']}》的其他制作人员：" + "；".join(staff_line(s) for s in rest) + "。"))

    # cast
    if r["characters"]:
        cast_parts = []
        for c in r["characters"]:
            cn = c["name_jp"] or c["name"]
            vas = "、".join(f"{va['name_jp'] or va['name_romaji']}" for va in c["voice_actors"] if va["name_jp"] or va["name_romaji"])
            cast_parts.append(f"{cn}（CV: {vas}）" if vas else cn)
        chunks.append(("cast", f"《{t['native']}》的主要角色与配音：" + "、".join(cast_parts) + "。"))

    meta_common = {
        "work_id": r["id"],
        "title_native": t["native"], "title_romaji": t["romaji"], "title_english": t["english"],
        "aliases": r["aliases"], "season": r.get("season"), "year": r.get("seasonYear"),
        "source": "anilist",
    }
    return [{"dimension": dim, "text": text, **meta_common} for dim, text in chunks]


def main():
    base = os.path.join(os.path.dirname(__file__), "..")
    with open(os.path.join(base, "data", "processed", "works.jsonl"), encoding="utf-8") as f:
        works = [json.loads(line) for line in f if line.strip()]

    chunks = []
    for r in works:
        chunks.extend(build_chunks(r))

    out_path = os.path.join(base, "data", "processed", "chunks.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    dims = {}
    for c in chunks:
        dims[c["dimension"]] = dims.get(c["dimension"], 0) + 1
    print(f"works={len(works)} chunks={len(chunks)} by_dim={dims}")
    sample = chunks[0]
    print("sample chunk:", json.dumps(sample, ensure_ascii=False)[:400])


if __name__ == "__main__":
    main()

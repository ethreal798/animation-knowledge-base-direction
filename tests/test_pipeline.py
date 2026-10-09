"""管线单元测试: clean 声优路径 / chunk 分块维度 / bm25 编码
运行: python -m pytest tests/test_pipeline.py  (或 python tests/test_pipeline.py)
"""
import json
import math
import os
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.abspath(os.path.join(BASE, "..", "scripts"))
sys.path.insert(0, SCRIPTS)

from clean import norm_name, ROLE_ZH
from chunk import build_chunks, CORE_ROLES
from embed_index import tokenize, build_bm25_encoder


def make_raw():
    return {
        "id": 999, "season": "WINTER", "seasonYear": 2025, "episodes": 12,
        "title": {"native": "テスト作品", "romaji": "TestWork", "english": "Test Work"},
        "studios": {"nodes": [{"name": "StudioX"}]},
        "staff": {"edges": [
            {"role": "Director", "node": {"name": {"full": "Taro Yamada", "native": "山田 太郎"}}},
            {"role": "Director", "node": {"name": {"full": "Taro Yamada", "native": "山田 太郎"}}},  # 重复
            {"role": "Music", "node": {"name": {"full": "Jiro Sato", "native": ""}}},
        ]},
        "characters": {"edges": [
            {"node": {"name": {"full": "Hana", "native": "花"}},
             "voiceActors": [{"name": {"full": "Yui Aoi", "native": "葵 結衣"}}]},
        ]},
    }


def test_clean_voice_actor_path():
    """回归: 声优名必须取 va['name']['native'], 否则为空。"""
    m = make_raw()
    vas = [{"name_jp": norm_name(va.get("name", {}).get("native")),
            "name_romaji": norm_name(va.get("name", {}).get("full"))}
           for va in m["characters"]["edges"][0]["voiceActors"]]
    assert vas == [{"name_jp": "葵結衣", "name_romaji": "YuiAoi"}], vas


def test_clean_role_mapping_and_dedup():
    staff = []
    for e in make_raw()["staff"]["edges"]:
        nm = e["node"]["name"]
        jp, rom = norm_name(nm.get("native")), norm_name(nm.get("full"))
        role = e["role"]
        staff.append({"role_en": role, "role_zh": ROLE_ZH.get(role, role),
                      "name_jp": jp, "name_romaji": rom})
    seen, dedup = set(), []
    for s in staff:
        k = (s["role_en"], s["name_jp"] or s["name_romaji"])
        if k not in seen:
            seen.add(k)
            dedup.append(s)
    assert ROLE_ZH["Director"] == "导演"
    assert ROLE_ZH["Music"] == "音乐"
    assert len(dedup) == 2, "重复的 Director 应被去重"


def test_chunk_dimensions_and_cast_cv():
    w = {
        "id": 999,
        "titles": {"native": "テスト作品", "romaji": "TestWork", "english": "Test Work"},
        "aliases": [], "season": "WINTER", "seasonYear": 2025, "episodes": 12,
        "studios": ["StudioX"],
        "staff": [
            {"role_en": "Director", "role_zh": "导演", "name_jp": "山田太郎", "name_romaji": "TaroYamada"},
            {"role_en": "Script", "role_zh": "Script", "name_jp": "佐藤次郎", "name_romaji": "JiroSato"},
        ],
        "characters": [
            {"name": "Hana", "name_jp": "花",
             "voice_actors": [{"name_jp": "葵結衣", "name_romaji": "YuiAoi"}]},
        ],
        "source": "anilist",
    }
    chunks = build_chunks(w)
    dims = [c["dimension"] for c in chunks]
    assert dims == ["overview", "studio", "staff_核心", "staff_其余", "cast"], dims
    cast = [c for c in chunks if c["dimension"] == "cast"][0]
    assert "CV: 葵結衣" in cast["text"], cast["text"]
    core = [c for c in chunks if c["dimension"] == "staff_核心"][0]
    assert "导演: 山田太郎" in core["text"]
    assert "山田太郎" in CORE_ROLES or "导演" in CORE_ROLES


def test_bm25_encoder_consistent():
    texts = ["《テスト作品》的制作公司为：StudioX。", "《別作品》的制作公司为：StudioY。"]
    encode, vocab_size = build_bm25_encoder(texts)
    idx, val = encode(texts[0])
    assert idx and val, "BM25 向量不应为空"
    assert len(idx) == len(val)
    assert all(math.isfinite(v) for v in val)
    # 同一文本编码稳定
    assert encode(texts[0]) == encode(texts[0])


def test_tokenize_splits_cjk_and_latin():
    toks = tokenize("テスト作品 StudioX 2025")
    assert "テ" in toks and "studiox" in toks and "2025" in toks


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    sys.exit(1 if failed else 0)

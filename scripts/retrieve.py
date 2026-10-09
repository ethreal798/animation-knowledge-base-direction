"""混合检索验证: dense(余弦) + sparse(BM25) 双路, RRF 融合。
用法: python scripts/retrieve.py "药屋少女的呢喃 导演是谁" [top_k]
"""
import json
import math
import os
import re
import sys
from collections import Counter

import requests
from qdrant_client import QdrantClient, models

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(BASE, ".."))
EMB_MODEL = "qwen3.7-text-embedding-flash"
COLLECTION = "anime_chunks"
TOKEN_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]|[a-z0-9]+")


def load_env():
    env = {}
    with open(os.path.join(ROOT, ".env"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def load_bm25():
    """从入库时落盘的词表加载, 保证与索引侧完全一致(跨进程 hash 稳定性)。"""
    with open(os.path.join(ROOT, "data", "processed", "bm25_vocab.json"), encoding="utf-8") as f:
        saved = json.load(f)
    vocab, idf = saved["vocab"], saved["idf"]

    def encode(text):
        tf = Counter(TOKEN_RE.findall(text.lower()))
        idx, val = [], []
        for w, c in tf.items():
            i = vocab.get(w)
            if i is not None:
                idx.append(i)
                val.append(c * idf[w])
        return idx, val

    return encode


def main():
    query = sys.argv[1]
    top = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    env = load_env()
    key, base = env["DASHSCOPE_API_KEY"], env["DASHSCOPE_BASE_URL"]

    r = requests.post(
        base + "/embeddings",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": EMB_MODEL, "input": [query]},
        timeout=60,
    )
    if r.status_code != 200:
        raise RuntimeError(f"embed {r.status_code}: {r.text[:200]}")
    q_vec = r.json()["data"][0]["embedding"]

    encode = load_bm25()
    q_idx, q_val = encode(query)

    client = QdrantClient(path=os.path.join(ROOT, "data", "qdrant"))

    dense = models.NearestQuery(nearest=q_vec)
    sparse = models.NearestQuery(nearest=models.SparseVector(indices=q_idx, values=q_val))
    res = client.query_points(
        COLLECTION,
        prefetch=[
            models.Prefetch(query=dense, using="dense", limit=top * 3),
            models.Prefetch(query=sparse, using="sparse", limit=top * 3),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=top,
        with_payload=True,
    )

    print(f"query: {query}\n")
    for i, p in enumerate(res.points, 1):
        pl = p.payload
        print(f"[{i}] score={p.score:.4f} | {pl['dimension']} | {pl['title_native']} ({pl['title_romaji']})")
        print(f"    {pl['text'][:110]}")


if __name__ == "__main__":
    main()

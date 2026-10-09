"""向量入库: chunks.jsonl -> Qdrant local (data/qdrant)
稠密向量(网关 embedding) + BM25 稀疏向量双路入库, 检索时 RRF 融合。
local 模式不支持 payload 全文索引, 故稀疏路用自研 BM25 编码。
用法: python scripts/embed_index.py [--rebuild]
"""
import json
import math
import os
import re
import sys
import time
from collections import Counter

import requests
from qdrant_client import QdrantClient, models

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(BASE, ".."))
EMB_MODEL = "qwen3.7-text-embedding-flash"
COLLECTION = "anime_chunks"
BATCH = 25  # 网关批量上限
DIM = 1024

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


def tokenize(text):
    """中文按单字、拉丁/数字按小写词。"""
    return TOKEN_RE.findall(text.lower())


def build_bm25_encoder(texts, save_path=None):
    """基于语料统计 df, 返回 encode(doc)->(indices, values) 的闭包。
    词表按出现顺序固定(避免跨进程 hash 随机化导致索引错位), 可落盘共用。"""
    N = len(texts)
    df = Counter()
    for t in texts:
        df.update(set(tokenize(t)))
    idf = {w: math.log(1 + (N - df[w] + 0.5) / (df[w] + 0.5)) for w in df}
    vocab = {w: i for i, w in enumerate(df)}
    if save_path:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump({"vocab": vocab, "idf": idf}, f, ensure_ascii=False)

    def encode(text):
        tf = Counter(tokenize(text))
        idx, val = [], []
        for w, c in tf.items():
            i = vocab.get(w)
            if i is not None:
                idx.append(i)
                val.append(c * idf[w])
        return idx, val

    return encode, len(vocab)


def embed_batch(key, base, texts):
    for attempt in range(5):
        r = requests.post(
            base + "/embeddings",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": EMB_MODEL, "input": texts},
            timeout=60,
        )
        if r.status_code == 200:
            data = sorted(r.json()["data"], key=lambda x: x["index"])
            return [d["embedding"] for d in data]
        if r.status_code == 429:
            wait = 2 ** attempt
            print(f"  rate limited, retry in {wait}s")
            time.sleep(wait)
            continue
        raise RuntimeError(f"embed {r.status_code}: {r.text[:200]}")
    raise RuntimeError("embed retries exhausted")


def main():
    env = load_env()
    key, base = env["DASHSCOPE_API_KEY"], env["DASHSCOPE_BASE_URL"]

    with open(os.path.join(ROOT, "data", "processed", "chunks.jsonl"), encoding="utf-8") as f:
        chunks = [json.loads(line) for line in f if line.strip()]
    print("chunks:", len(chunks))

    encode_bm25, vocab_size = build_bm25_encoder(
        [c["text"] for c in chunks], save_path=os.path.join(ROOT, "data", "processed", "bm25_vocab.json"))
    print("bm25 vocab:", vocab_size)

    client = QdrantClient(path=os.path.join(ROOT, "data", "qdrant"))
    if "--rebuild" in sys.argv:
        client.delete_collection(COLLECTION)
    if not client.collection_exists(COLLECTION):
        client.create_collection(
            COLLECTION,
            vectors_config={"dense": models.VectorParams(size=DIM, distance=models.Distance.COSINE)},
            sparse_vectors_config={"sparse": models.SparseVectorParams()},
        )
        print("collection created (dense + sparse)")

    existing = client.count(COLLECTION).count
    if existing and "--rebuild" not in sys.argv:
        print(f"collection already has {existing} points, skip (use --rebuild to redo)")
        return

    points = []
    for i in range(0, len(chunks), BATCH):
        batch = chunks[i:i + BATCH]
        vecs = embed_batch(key, base, [c["text"] for c in batch])
        for j, (c, v) in enumerate(zip(batch, vecs)):
            idx, val = encode_bm25(c["text"])
            points.append(models.PointStruct(
                id=i + j,
                vector={
                    "dense": v,
                    "sparse": models.SparseVector(indices=idx, values=val),
                },
                payload={
                    "dimension": c["dimension"],
                    "text": c["text"],
                    "work_id": c["work_id"],
                    "title_native": c.get("title_native", ""),
                    "title_romaji": c.get("title_romaji", ""),
                    "title_english": c.get("title_english", ""),
                    "season": c.get("season", ""),
                    "year": c.get("year", ""),
                },
            ))
        print(f"  embedded {i + len(batch)}/{len(chunks)}")
        time.sleep(0.2)

    client.upsert(COLLECTION, points=points, wait=True)
    print("indexed:", client.count(COLLECTION).count)


if __name__ == "__main__":
    main()

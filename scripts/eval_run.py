"""对照实验: 同一评测集分别跑 baseline / rag, 规则匹配评估 -> data/eval_results.jsonl
用法: python scripts/eval_run.py [--rebuild]  直接请求本地服务 /api/chat
"""
import json
import os
import re
import sys
import time

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(BASE, ".."))
API = "http://127.0.0.1:8000/api/chat"
MODES = ["baseline", "rag"]


def norm(s):
    return re.sub(r"\s+", "", s)


def hit(answer, expected, qtype=None):
    if not expected:
        return False
    na = norm(answer)
    if qtype == "season":
        # 列举3部中至少2部属于该季度真实作品才算对
        return sum(1 for k in expected if k and norm(k) in na) >= 2
    return any(k and norm(k) in na for k in expected)


def main():
    with open(os.path.join(ROOT, "data", "eval_set.jsonl"), encoding="utf-8") as f:
        items = [json.loads(line) for line in f if line.strip()]
    print("eval items:", len(items))

    out_path = os.path.join(ROOT, "data", "eval_results.jsonl")
    mode = "w" if "--rebuild" in sys.argv else "a"
    limit = None
    keep_types = None
    for i, a in enumerate(sys.argv):
        if a == "--limit":
            limit = int(sys.argv[i + 1])
        if a == "--type":
            keep_types = sys.argv[i + 1]
            items = [it for it in items if it["type"] == keep_types]
            mode = "w"
    if limit:
        items = items[:limit]
        mode = "w"
    if mode == "w" and os.path.exists(out_path):
        if keep_types:
            kept = []
            with open(out_path, encoding="utf-8") as f:
                for line in f:
                    if json.loads(line)["type"] != keep_types:
                        kept.append(line)
            with open(out_path, "w", encoding="utf-8") as f:
                f.writelines(kept)
        else:
            os.remove(out_path)
    done = set()
    if mode == "a" and os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                done.add((r["id"], r["mode"]))

    results = []
    for it in items:
        for m in MODES:
            key = (it["id"], m)
            if key in done:
                continue
            try:
                r = requests.post(API, json={"question": it["question"], "mode": m}, timeout=120)
                ans = r.json().get("answer", "")
            except Exception as e:
                ans = f"<ERROR {e}>"
            rec = {"id": it["id"], "type": it["type"], "mode": m,
                   "question": it["question"], "expected": it["expected"],
                   "answer": ans, "hit": hit(ans, it["expected"], it["type"])}
            results.append(rec)
            with open(out_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"{it['id']} {m:8s} hit={rec['hit']} | {it['question'][:40]}", flush=True)
            time.sleep(0.3)

    # 汇总
    all_rows = [json.loads(line) for line in open(out_path, encoding="utf-8")]
    for m in MODES:
        rows = [r for r in all_rows if r["mode"] == m]
        if not rows:
            continue
        n = len(rows)
        ok = sum(r["hit"] for r in rows)
        print(f"\n== {m}: {ok}/{n} = {ok / n:.1%}")
        for t in ["director", "studio", "cast", "season"]:
            rt = [r for r in rows if r["type"] == t]
            if rt:
                ot = sum(r["hit"] for r in rt)
                print(f"   {t:9s} {ot}/{len(rt)} = {ot / len(rt):.1%}")


if __name__ == "__main__":
    main()

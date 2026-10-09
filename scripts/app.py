"""题A 问答服务: FastAPI, 双模式对照
- POST /api/chat  {question, mode: baseline|rag, history?}
  baseline: 纯 LLM; rag: 混合检索 top-k -> LLM
- GET  /api/health
- GET  /api/history  对话历史 (SQLite)
- GET  /            前端页面 (web/index.html)
用法: uvicorn scripts.app:app --host 0.0.0.0 --port 8000
"""
import json
import os
import sqlite3
import sys
import time

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from retrieve import load_env, load_bm25, COLLECTION, EMB_MODEL, TOKEN_RE

import math
import re
from collections import Counter

import requests
from qdrant_client import QdrantClient, models
from openai import OpenAI

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(BASE, ".."))

LLM_MODEL = "deepseek-v4-flash-0731"
RAG_PROMPT = """你是动画知识库问答助手。请只依据下方资料回答问题；资料不足时明确说明"资料中没有相关信息"，不要编造。

资料：
{context}

问题：{question}
回答："""


def _embed_query(key, base, text):
    r = requests.post(
        base + "/embeddings",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": EMB_MODEL, "input": [text]},
        timeout=60,
    )
    if r.status_code != 200:
        raise RuntimeError(f"embed {r.status_code}: {r.text[:200]}")
    return r.json()["data"][0]["embedding"]


class ChatRequest(BaseModel):
    question: str
    mode: str = "rag"  # baseline | rag
    history: list = []
    top_k: int = 5


def build_app():
    env = load_env()
    key, base = env["DASHSCOPE_API_KEY"], env["DASHSCOPE_BASE_URL"]
    encode = load_bm25()
    client = QdrantClient(path=os.path.join(ROOT, "data", "qdrant"))
    llm = OpenAI(api_key=key, base_url=base)

    # ---- SQLite 对话历史 ----
    db_path = os.path.join(ROOT, "data", "chat_history.db")
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("""CREATE TABLE IF NOT EXISTS chat_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        sources TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL)""")
    conn.commit()

    def save_chat(question, answer, sources):
        conn.execute(
            "INSERT INTO chat_history (question, answer, sources, created_at) VALUES (?, ?, ?, ?)",
            (question, answer, json.dumps(sources, ensure_ascii=False),
             time.strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()

    def load_history(limit=100):
        rows = conn.execute(
            "SELECT id, question, answer, sources, created_at FROM chat_history "
            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"id": r[0], "question": r[1], "answer": r[2],
                 "sources": json.loads(r[3]), "created_at": r[4]} for r in rows]

    def retrieve(question, top_k):
        q_vec = _embed_query(key, base, question)
        q_idx, q_val = encode(question)
        dense = models.NearestQuery(nearest=q_vec)
        sparse = models.NearestQuery(nearest=models.SparseVector(indices=q_idx, values=q_val))
        res = client.query_points(
            COLLECTION,
            prefetch=[
                models.Prefetch(query=dense, using="dense", limit=top_k * 3),
                models.Prefetch(query=sparse, using="sparse", limit=top_k * 3),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=top_k,
            with_payload=True,
        )
        return res.points

    app = FastAPI(title="AnimeQA 动画知识库")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "indexed": client.count(COLLECTION).count}

    @app.get("/api/history")
    def history(limit: int = 100):
        return {"items": load_history(limit)}

    @app.delete("/api/history/{hid}")
    def del_history(hid: int):
        conn.execute("DELETE FROM chat_history WHERE id = ?", (hid,))
        conn.commit()
        return {"ok": True, "deleted": hid}

    @app.delete("/api/history")
    def clear_history():
        conn.execute("DELETE FROM chat_history")
        conn.commit()
        return {"ok": True, "deleted_all": True}

    @app.get("/", response_class=HTMLResponse)
    def index():
        page = os.path.join(ROOT, "web", "index.html")
        if os.path.exists(page):
            with open(page, encoding="utf-8") as f:
                return f.read()
        return HTMLResponse("<h1>AnimeQA</h1><p>web/index.html 缺失</p>", status_code=200)

    @app.post("/api/chat")
    def chat(req: ChatRequest):
        messages = [{"role": m["role"], "content": m["content"]} for m in req.history]
        # 多轮记忆：用"历史问题 + 当前问题"做检索词，让"它/那部作品"能命中前文作品
        hist_q = " ".join(m["content"] for m in req.history if m["role"] == "user")
        question = f"{hist_q} {req.question}".strip() if hist_q else req.question
        if req.mode == "baseline":
            messages.append({"role": "user", "content": req.question})
            comp = llm.chat.completions.create(
                model=LLM_MODEL, messages=messages, max_tokens=1024,
                extra_body={"enable_thinking": False})
            result = {"answer": comp.choices[0].message.content, "sources": [],
                      "usage": comp.usage.model_dump() if comp.usage else {}}
            save_chat(req.question, result["answer"], result["sources"])
            return result

        points = retrieve(question, req.top_k)
        context = "\n".join(f"[{i + 1}] {p.payload['text']}" for i, p in enumerate(points))
        prompt = RAG_PROMPT.format(context=context, question=req.question)
        messages.append({"role": "user", "content": prompt})
        comp = llm.chat.completions.create(
            model=LLM_MODEL, messages=messages, max_tokens=1024,
            extra_body={"enable_thinking": False})
        sources = [
            {"id": p.id, "dimension": p.payload["dimension"], "text": p.payload["text"],
             "title": p.payload.get("title_native") or p.payload.get("title_romaji"),
             "season": p.payload.get("season"), "year": p.payload.get("year")}
            for p in points
        ]
        result = {"answer": comp.choices[0].message.content, "sources": sources,
                  "usage": comp.usage.model_dump() if comp.usage else {}}
        save_chat(req.question, result["answer"], result["sources"])
        return result

    return app


app = build_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

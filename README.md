# 番组资料室 · AnimeQA

**2025–2026 新番制作信息垂直知识库（RAG 问答）**——题A 笔试题交付项目。

- 数据源：AniList GraphQL（2025冬→2026秋，8 个季度，**406 部** TV 动画）
- 检索：稠密向量（qwen3.7-text-embedding-flash）+ 自研 BM25 稀疏向量双路，RRF 融合
- 生成：deepseek-v4-flash-0731（阿里云百炼网关），仅依据检索资料回答并带引用 `[n]`
- 评测：90 题双模式对照，**baseline 18.9% vs rag 100%**（详见 `题A_交付说明.md` §4）
- 公网：http://8.166.138.196:18001/
---

> **命令约定**：本文所有命令都**直接以虚拟环境内的解释器执行，无需先 activate**。
> - Windows：`.venv\Scripts\python.exe`
> - Linux / macOS：`.venv/bin/python`
>
> 下面所有命令都给出两种写法（用「# win / # mac」标注差异），复制即可运行。

## 目录结构

```
a/
├── README.md               # 本文件
├── 题A_交付说明.md          # 交付说明（实现方式/选型/评估/token/失败案例）
├── 题A_Spec.md             # 设计文档
├── requirements.txt
├── .env                    # 网关密钥（已随仓库提交，仓库请保持私有）
├── web/index.html          # 前端页面（由 FastAPI 直接托管）
├── scripts/                # 数据管线 + 服务
│   ├── app.py              # FastAPI 问答服务（入口）
│   ├── collect_anilist.py  # 采集
│   ├── retry_missing.py    # 差集补采
│   ├── clean.py            # 清洗/实体归一
│   ├── chunk.py            # 分块
│   ├── embed_index.py      # 向量入库
│   ├── retrieve.py         # 混合检索验证
│   ├── eval_build.py       # 评测集构建
│   └── eval_run.py         # 评测跑分
├── tests/test_pipeline.py  # 单元测试
└── data/                   # 原始JSON / 处理结果 / Qdrant / SQLite 历史 / 评测结果
```

## 环境要求

- Python 3.10+（本机 venv 为 3.12，服务器部署为 3.10）
- 依赖见 `requirements.txt`（fastapi / uvicorn / qdrant-client / openai / requests / pydantic）

## 快速开始（启动问答服务）

> **数据已全部就绪，开箱即用**：本仓库已提交完整数据产物——8 季度 406 部原始采集 JSON、清洗分块后的 2022 块、Qdrant 双路向量索引（均在 `data/` 目录），以及网关密钥 `.env`。你只需创建虚拟环境、装依赖、启动服务即可，**无需执行任何采集 / 分块 / 建索引命令**。
>
> 如需重跑数据管线（会**覆盖**现有数据产物），见「重建知识库（数据管线）」一节。

### 1. 创建虚拟环境

```bash
python -m venv .venv
```

### 2. 安装依赖

```bash
# Windows
.venv\Scripts\python.exe -m pip install -r requirements.txt

# Linux / macOS
.venv/bin/python -m pip install -r requirements.txt
```

### 3. 确认网关密钥

`.env` 已随仓库提供（含密钥，仓库为私有）。仅当克隆后 `.env` 缺失时，按以下模板手动创建：

```
DASHSCOPE_API_KEY=sk-xxxx
DASHSCOPE_BASE_URL=https://<你的网关>/compatible-mode/v1
```

### 4. 启动服务

```bash
# Windows
.venv\Scripts\python.exe -m uvicorn app:app --app-dir scripts --host 0.0.0.0 --port 8000

# Linux / macOS
.venv/bin/python -m uvicorn app:app --app-dir scripts --host 0.0.0.0 --port 8000
```

启动后访问 **http://localhost:8000/** （Web 页面），健康检查 `GET /api/health` 返回 `{"status":"ok","indexed":2022}`。

> 为什么 `--app-dir scripts`：`app.py` 顶部 `from retrieve import ...` 依赖同目录模块，把 scripts 加入模块搜索路径即可。等价写法：先 `cd scripts` 再执行上面的 uvicorn 命令（去掉 `--app-dir scripts`）。

## API 接口

| 接口 | 方法 | 说明 |
|---|---|---|
| `/api/chat` | POST | 问答。入参 `{"question": "...", "mode": "rag\|baseline", "history": [...], "top_k": 5}`；返回 `{answer, sources:[{title,dimension,text,season,year}], usage}` |
| `/api/health` | GET | 服务状态 + 索引块数 |
| `/api/history` | GET | 对话历史（SQLite，最近 100 条） |
| `/api/history/{id}` | DELETE | 删除单条历史 |
| `/api/history` | DELETE | 清空全部历史 |
| `/` | GET | 前端页面 |

## 重建知识库（数据管线）

> 以下命令仅供**重跑管线覆盖现有数据**时使用；开箱即用场景无需执行任何一条。

按顺序执行（每个脚本输出为下一个脚本的输入）：

```bash
# 1. 采集（按季度枚举，如 2025 WINTER；试点可加 max_pages）
# Windows
.venv\Scripts\python.exe scripts/collect_anilist.py 2025 WINTER
# Linux / macOS
.venv/bin/python scripts/collect_anilist.py 2025 WINTER

# 2. 差集补采（对"枚举全集 − 本地已有"的缺失作品重试）
# Windows
.venv\Scripts\python.exe scripts/retry_missing.py
# Linux / macOS
.venv/bin/python scripts/retry_missing.py

# 3. 清洗与实体归一 → data/processed/works.jsonl
# Windows
.venv\Scripts\python.exe scripts/clean.py
# Linux / macOS
.venv/bin/python scripts/clean.py

# 4. 作品×维度分块 → data/processed/chunks.jsonl
# Windows
.venv\Scripts\python.exe scripts/chunk.py
# Linux / macOS
.venv/bin/python scripts/chunk.py

# 5. 双路向量入库 → data/qdrant（--rebuild 清空重建）
# Windows
.venv\Scripts\python.exe scripts/embed_index.py [--rebuild]
# Linux / macOS
.venv/bin/python scripts/embed_index.py [--rebuild]

# 6. 检索验证
# Windows
.venv\Scripts\python.exe scripts/retrieve.py "药屋少女的呢喃 导演是谁" 5
# Linux / macOS
.venv/bin/python scripts/retrieve.py "药屋少女的呢喃 导演是谁" 5
```

## 评测

```bash
# 构建评测集（90 题：导演/制作公司/声优/季度）→ data/eval_set.jsonl
# Windows
.venv\Scripts\python.exe scripts/eval_build.py
# Linux / macOS
.venv/bin/python scripts/eval_build.py

# 跑分（需先在本机启动服务，遍历评测集请求 /api/chat，写入 data/eval_results.jsonl）
# Windows
.venv\Scripts\python.exe scripts/eval_run.py [--rebuild] [--limit N] [--type 导演]
# Linux / macOS
.venv/bin/python scripts/eval_run.py [--rebuild] [--limit N] [--type 导演]
```

## 单元测试

```bash
# Windows
.venv\Scripts\python.exe -m pytest tests/test_pipeline.py
# Linux / macOS
.venv/bin/python -m pytest tests/test_pipeline.py

# 或直接运行（不依赖 pytest）：
.venv\Scripts\python.exe tests/test_pipeline.py   # Windows
.venv/bin/python tests/test_pipeline.py           # Linux / macOS
```

## 常见问题

**Q1：提示 `No module named 'fastapi'`**

多半是没有用虚拟环境内的解释器执行——请确认每条命令都是 `.venv\Scripts\python.exe`（Windows）/ `.venv/bin/python`（Linux/macOS）开头，而不是裸 `python`。若 venv 已存在但缺依赖，重跑「安装依赖」步骤。

**Q2：启动报 `portalocker.exceptions.AlreadyLocked` / `PermissionError: [Errno 13]`**

Qdrant local 模式通过锁文件（`data/qdrant/.lock`）保证单进程独占，同一时间只能有一个服务实例。若之前有旧实例没退出（或残留了无响应的 uvicorn 进程），新实例启动就会抢锁失败。

排查与解决（Windows）：

```powershell
# 1. 找占着 8000 端口的旧实例
Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -eq 8000 }

# 2. 确认它是残留的问答服务后停掉（PID 替换为实际值）
Stop-Process -Id <PID> -Force

# 3. 重新启动
.venv\Scripts\python.exe -m uvicorn app:app --app-dir scripts --host 0.0.0.0 --port 8000
```

Linux/macOS：`lsof -i :8000` 找 PID 后 `kill <PID>`，再重新启动。

## 说明文档

- `题A_交付说明.md`：按题面 6 项交付要求组织——实现方式与时间规划 / 开源RAG选型 / 评估方案设计 / AI工具与token统计 / 个人时间占比 / 失败案例分析。
- `题A_Spec.md`：设计文档与 Phase 结论。

# RepoLens

> AI-powered GitHub repository explainer with Graph RAG chat

RepoLens analyzes any public GitHub repository and generates a structured technical tutorial. It then builds a knowledge graph from the codebase and lets you chat with it using a hybrid Graph RAG pipeline combining Neo4j, Qdrant, and the OpenAI Agents SDK.

---

## What It Does

1. **Analyzes** a GitHub repo by reading its files using the GitHub API
2. **Generates** a structured 2000+ word tutorial covering architecture, installation, key files, and code walkthrough — streamed live to the UI
3. **Exports** the tutorial as a styled PDF
4. **Indexes** the codebase into a knowledge graph (Neo4j) and vector database (Qdrant)
5. **Chats** with you about the codebase using a hybrid retrieval pipeline that combines vector search, graph descriptions, and graph traversal

---

## Architecture

```
User
 │
 ├── POST /analyze/{session_id}
 │     └── Report Creation Agent (OpenAI Agents SDK)
 │           ├── get_readme()              GitHub API
 │           ├── return_file_structure()   GitHub API
 │           ├── navigate_repository()     GitHub API
 │           └── create_chunks()           → Qdrant (documents_{repo_key})
 │
 ├── GET  /download/{session_id}
 │     └── Playwright → PDF bytes → browser
 │
 └── WS   /chat/{session_id}
       ├── create_knowledge_graph()
       │     ├── scroll Qdrant (documents_{repo_key})
       │     └── LLMGraphTransformer → GraphDocuments
       ├── prefix_graph_docs()     prefix node IDs with repo key
       ├── store_graph()           → Neo4j (prefixed node IDs)
       ├── store_knowledge_graph() → Qdrant (graph_documents_{repo_key})
       └── Chat loop
             └── Chat Agent (OpenAI Agents SDK)
                   └── Query_VectorDB()
                         ├── Qdrant vector search (graph_documents_{repo_key})
                         └── Neo4j traversal (1-hop relationships, filtered by prefix)
```

---

## Tech Stack

| Component | Technology |
|---|---|
| Backend | FastAPI |
| Frontend | Vanilla HTML/CSS/JS |
| Parent Agent | OpenAI Agents SDK + GPT-4o |
| Chat Agent | OpenAI Agents SDK + GPT-4o-mini |
| Graph extraction | LangChain `LLMGraphTransformer` |
| Knowledge graph | Neo4j (Aura) |
| Vector database | Qdrant Cloud |
| Embeddings | OpenAI `text-embedding-3-small` |
| Code chunking | `tree-sitter` via `chunk_ast` |
| PDF generation | `Playwright` + markdown rendering |
| Tracing | OpenAI Agents SDK tracing |

---

## Prerequisites

- Python 3.11+
- `playwright` installed and browser binaries available (`python -m playwright install chromium`)
- Neo4j Aura account (free tier works)
- Qdrant Cloud account (free tier works)
- OpenAI API key
- GitHub Personal Access Token

---

## Installation

```bash
git clone https://github.com/your-username/RepoLens.git
cd RepoLens
python -m venv myenv
source myenv/bin/activate  # Windows: myenv\Scripts\activate
pip install -r requirements.txt
```

---

## Environment Variables

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=sk-...

# GitHub
Github_access_token=Bearer ghp_...

# Qdrant Cloud
QDRANT_CLUSTER=https://your-cluster.qdrant.io
QDRANT_API_KEY=your-qdrant-api-key

# Neo4j Aura
NEO4J_URI=neo4j+s://your-instance.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your-neo4j-password
```

---

## Running the App

```bash
uvicorn main:app --reload
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

---

## Usage

**Step 1 — Enter repository details**

Fill in the GitHub URL, owner, repository name, and branch. The owner and repo name auto-fill from the URL as you type.

**Step 2 — Analyze**

Click **Analyze Repository**. The parent agent reads the README, maps the file structure, navigates all core files, chunks them into Qdrant, and streams a full technical tutorial to the screen.

**Step 3 — Download PDF**

Click **Download PDF** to get a styled dark-theme PDF of the tutorial.

**Step 4 — Open Chat**

Click **Open Chat**. The app builds a knowledge graph from the Qdrant chunks, stores it in Neo4j, embeds the graph documents back into Qdrant, and opens a chat interface. The chat agent decides on every turn whether to query the vector database or answer from conversation history.

---

## Project Structure

```
RepoLens/
├── main.py                   # FastAPI app — routes, caching, analysis, and chat WebSocket
├── frontend.html             # Single-page UI
├── pyproject.toml            # Python package metadata
├── requirements.txt          # Python dependencies
├── .cache.json               # optional local cache for reports and graph indexing
├── .env                      # environment variables (not checked in)
├── chatbot/
│   ├── chat.py               # Chat agent + answer streaming (per-call agent factory)
│   └── prompt.py             # Chat agent prompt instructions
├── db/
│   ├── context.py            # ContextVar for per-repo Qdrant collection routing
│   ├── neo4j.py              # Neo4j graph storage + node ID prefixing
│   └── qdrant.py             # Qdrant document storage helpers
├── graph/
│   ├── create_prompt.py      # final prompt builder for the chat pipeline
│   ├── graph_docs_Qdrant.py  # graph document stringification helper
│   ├── kg.py                 # graph extraction and storage pipeline
│   └── rag.py                # graph RAG helpers and queries
├── report/
│   ├── orchestrator.py       # repository analysis pipeline
│   └── tools.py              # analysis helper utilities
└── utils/
    └── download_pdf.py       # PDF generation helper
```

---

## How the Graph RAG Works

The chat uses a three-source hybrid retrieval pipeline:

**1. Vector search on graph documents (Qdrant)**
Each code chunk is processed by `LLMGraphTransformer` which extracts entities and relationships. The resulting `GraphDocument` is stringified into a text description and embedded. At query time, the most semantically similar graph docs are retrieved.

**2. Graph traversal (Neo4j)**
From the matched graph doc nodes, a 1-hop Cypher traversal finds directly connected entities — revealing how functions call each other, what they initialize, what they return. `MENTIONS` relationships are filtered out to reduce noise.

**3. Raw code chunks (Qdrant)**
The original code text is available in the graph doc payload and included as ground truth context.

All three sources are combined into a single prompt sent to the chat agent.

---

## Key Design Decisions

**Why Graph RAG over plain vector search?**
Vector search finds semantically similar chunks but misses structural relationships. A question like *"how does the upload endpoint connect to ChromaDB?"* requires following edges across files — which only graph traversal can do.

**Why stringify graph documents before embedding?**
Embedding models are trained on natural language. Converting `Node(id='Create_Db', type='Function')` to `"Function: Create_Db initializes Client"` produces richer embeddings that match developer questions more accurately.

**Why semaphore on LLM graph extraction?**
`LLMGraphTransformer` fires all documents concurrently by default. With large codebases this immediately exhausts the OpenAI TPM limit. A `Semaphore(3)` limits concurrent LLM calls to 3 at a time.

**Why session_id from the frontend?**
Using `crypto.randomUUID()` in the browser means no server round-trip is needed to start a session. The session_id ties the analysis (`/analyze/{id}`), download (`/download/{id}`), and chat (`/chat/{id}`) together without any persistent storage.

---

## Cache

RepoLens uses a local `.cache.json` file to speed up repeated repository analysis and chat initialization:

- `main.py` stores per-repo cache entries keyed by `owner/repo@branch`.
- On `/analyze`, if the latest GitHub commit SHA matches the cached SHA, the stored tutorial report is streamed instead of recomputing it.
- On `/chat`, if the repository was already indexed, the app checks whether its dedicated Qdrant collection (`graph_documents_{repo_key}`) still exists. If it does, the knowledge graph pipeline is skipped and chat starts immediately.
- The cache keeps up to 20 entries and avoids repeated work when the repo content has not changed.

### Per-repo isolation

Each repository gets its own pair of Qdrant collections:

| Collection | Contents |
|---|---|
| `documents_{repo_key}` | Raw code chunks stored during analysis |
| `graph_documents_{repo_key}` | Embedded graph documents used during chat |

`repo_key` is derived from `owner/repo@branch` with non-alphanumeric characters replaced by `_` (e.g. `openai_openai_python_main`).

All Neo4j nodes are prefixed with the repo key (`owner/repo@branch::NodeId`) so multiple repositories can coexist in the same Neo4j database without their entities colliding. Switching between repositories requires no cache invalidation — each repo's graph is always available independently.

---

## Troubleshooting

**PDF download fails**
Make sure `playwright` and its browser runtime are installed. Run:

```bash
python -m pip install playwright
python -m playwright install chromium
```

If your environment cannot launch Chromium, install the appropriate browser package or run inside a container with GUI support.

**`Collection 'documents_...' doesn't exist`**
This happens when the chat is opened before the parent agent has finished analyzing the repo. Complete the analysis step first so `create_chunks` has populated the per-repo Qdrant collection.

**Rate limit errors during graph extraction**
The semaphore limits concurrent calls but if your Qdrant collection has many chunks you may still hit TPM limits. Reduce the semaphore value to `asyncio.Semaphore(1)` or switch from `gpt-4o-mini` to a higher-tier model with more TPM.

**WebSocket disconnects immediately**
Make sure `await websocket.accept()` is the first line in the WebSocket handler — before any processing. The browser will time out if accept is delayed.

**Neo4j deprecation warnings flooding logs**
Add this near the top of `main.py`:
```python
import logging
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
```

---

## License

MIT

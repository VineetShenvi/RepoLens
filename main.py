from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from chatbot.chat import get_answer
from report.orchestrator import create_report
from utils.download_pdf import save_as_pdf
from graph.kg import create_knowledge_graph
from db.qdrant import store_knowledge_graph
from db.neo4j import store_graph, prefix_graph_docs
from db.context import current_docs_collection
from langchain_neo4j import Neo4jGraph
from qdrant_client import QdrantClient
from pydantic import BaseModel
from pathlib import Path
from dotenv import load_dotenv
import logging
import asyncio
import json
import os
import re
import time
import requests as _requests
import certifi
os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()


load_dotenv()

_CACHE_FILE = Path(".cache.json")

def _load_cache() -> dict:
    if _CACHE_FILE.exists():
        try:
            return json.loads(_CACHE_FILE.read_text())
        except Exception:
            return {}
    return {}

def _save_cache(cache: dict):
    if len(cache) > 20:
        cache = dict(list(cache.items())[-20:])
    _CACHE_FILE.write_text(json.dumps(cache, indent=2))

def _safe_collection_name(cache_key: str) -> str:
    """Turn 'owner/repo@branch' into a valid Qdrant collection name segment."""
    return re.sub(r'[^a-zA-Z0-9]', '_', cache_key)

def _get_commit_sha(owner: str, repo: str, branch: str) -> str | None:
    url = f"https://api.github.com/repos/{owner}/{repo}/commits/{branch}"
    try:
        r = _requests.get(
            url,
            headers={"Authorization": os.getenv("Github_access_token")},
            timeout=5,
            verify=certifi.where(),
        )
        if r.status_code == 200:
            return r.json().get("sha")
    except Exception:
        pass
    return None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)


class RepoInput(BaseModel):
    url: str
    owner: str
    repo_name: str
    branch: str

client = QdrantClient(
    url=os.getenv('QDRANT_CLUSTER'),
    api_key=os.getenv('QDRANT_API_KEY')
)

graph = Neo4jGraph(
    url=os.getenv('NEO4J_URI'),
    username=os.getenv('NEO4J_USERNAME'),
    password=os.getenv('NEO4J_PASSWORD')
)


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

report_store: dict[str, str] = {}
session_repo_store: dict[str, dict] = {}

@app.get("/")
async def serve_frontend():
    index_path = Path("frontend.html")
    if not index_path.exists():
        return JSONResponse(status_code=404, content={"error": "frontend.html not found"})
    return FileResponse('frontend.html')


@app.post('/analyze/{session_id}')
async def analyze(session_id: str, repo_input: RepoInput):
    """
    Stream the repository analysis. Stores the full text in memory
    so the download endpoint can generate a PDF from it.
    """
    cache_key = f"{repo_input.owner}/{repo_input.repo_name}@{repo_input.branch}"
    safe_key = _safe_collection_name(cache_key)
    docs_collection = f"documents_{safe_key}"
    graph_collection = f"graph_documents_{safe_key}"
    logger.info("[%s] /analyze — repo=%s branch=%s", session_id, cache_key, repo_input.branch)

    sha = await asyncio.to_thread(
        _get_commit_sha, repo_input.owner, repo_input.repo_name, repo_input.branch
    )
    logger.info("[%s] /analyze — commit SHA=%s", session_id, sha[:8] if sha else "unknown")

    cache = _load_cache()
    entry = cache.get(cache_key, {})

    # Always store collection names so the WebSocket handler can find them.
    session_repo_store[session_id] = {
        'cache_key': cache_key,
        'sha': sha,
        'safe_key': safe_key,
        'docs_collection': docs_collection,
        'graph_collection': graph_collection,
    }

    if sha and entry.get('sha') == sha and entry.get('report'):
        logger.info("[%s] /analyze — cache hit; streaming cached report", session_id)
        cached_report = entry['report']
        report_store[session_id] = cached_report

        async def stream_cached_report():
            yield cached_report

        return StreamingResponse(stream_cached_report(), media_type='text/markdown')

    message = (
        f'Explain this repo---> '
        f'url:{repo_input.url}, '
        f'owner:{repo_input.owner}, '
        f'repo_name:{repo_input.repo_name}, '
        f'branch:{repo_input.branch}'
    )

    async def stream_and_store():
        # Clear this repo's raw-chunk collection so stale data doesn't bleed into KG creation.
        try:
            client.delete_collection(collection_name=docs_collection)
            logger.info("[%s] /analyze — cleared '%s' collection for fresh ingest", session_id, docs_collection)
        except Exception:
            pass

        # Point create_chunks at this repo's documents collection for the duration of streaming.
        token = current_docs_collection.set(docs_collection)
        try:
            chunks = []
            async for chunk in create_report(message=message):
                chunks.append(chunk)
                yield chunk
        finally:
            current_docs_collection.reset(token)

        full_report = ''.join(chunks)
        report_store[session_id] = full_report
        logger.info("[%s] /analyze — streaming complete; total_chars=%s", session_id, len(full_report))

        if sha:
            cache[cache_key] = {**entry, 'sha': sha, 'report': full_report, 'indexed': False}
            _save_cache(cache)
            logger.info("[%s] /analyze — saved SHA %s to cache", session_id, sha[:8])

    try:
        return StreamingResponse(stream_and_store(), media_type='text/markdown')
    except Exception as e:
        logger.exception("[%s] /analyze failed: %s", session_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/download/{session_id}')
async def download_pdf(session_id: str):
    """Generate and return PDF from the stored report text."""
    text = report_store.get(session_id)
    if not text:
        raise HTTPException(
            status_code=404,
            detail='Report not found. Please analyze the repository first.'
        )
    try:
        pdf_bytes = await save_as_pdf(tutorial_text=text)
        return Response(
            content=pdf_bytes,
            media_type='application/pdf',
            headers={'Content-Disposition': 'attachment; filename="repo.pdf"'}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



async def run_chat_loop(websocket: WebSocket, session_id: str, graph_collection: str, docs_collection: str):
    history = []
    while True:
        try:
            user_message = await websocket.receive_text()

            if user_message == "__RESTART_CHAT__":
                history = []
                await websocket.send_text("__CHAT_RESTARTED__")
                continue

            full_response = ""
            async for chunk in get_answer(
                message=user_message,
                history=history,
                graph_collection=graph_collection,
                docs_collection=docs_collection,
            ):
                full_response += chunk
                await websocket.send_text(chunk)

            history.append({"role": "user", "content": user_message})
            history.append({"role": "assistant", "content": full_response})

        except WebSocketDisconnect:
            logging.info(f"Session {session_id} disconnected")
            break
        except Exception as e:
            logging.error(f"Chat error in session {session_id}: {e}")
            try:
                await websocket.send_text(f"__CHAT_ERROR__:{str(e)}")
            except Exception:
                break

@app.websocket("/chat/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: str):
    await websocket.accept()
    logger.info("[%s] WebSocket connected", session_id)

    try:
        await websocket.send_text("__LOADING__")

        session_info = session_repo_store.get(session_id, {})
        cache_key = session_info.get('cache_key')
        sha = session_info.get('sha')
        safe_key = session_info.get('safe_key', _safe_collection_name(cache_key) if cache_key else '')
        docs_collection = session_info.get('docs_collection', f"documents_{safe_key}")
        graph_collection = session_info.get('graph_collection', f"graph_documents_{safe_key}")

        if sha and cache_key:
            ws_cache = _load_cache()
            ws_entry = ws_cache.get(cache_key, {})
            # If this repo was previously indexed, check whether the Qdrant collection still exists.
            # Per-repo collections mean we don't need to track which repo is "active" — each repo
            # has its own collection and can be used independently.
            if ws_entry.get('sha') == sha and ws_entry.get('indexed'):
                try:
                    client.get_collection(graph_collection)
                    logger.info("[%s] Cache hit — using collection %s", session_id, graph_collection)
                    await websocket.send_text(f"__LOG__:Using cached knowledge graph ({graph_collection})...")
                    await websocket.send_text("__READY__")
                    await run_chat_loop(websocket, session_id, graph_collection, docs_collection)
                    return
                except Exception:
                    logger.info("[%s] Collection %s missing despite cache flag — re-indexing", session_id, graph_collection)

        t0 = time.perf_counter()
        logger.info("[%s] Starting create_knowledge_graph from %s...", session_id, docs_collection)
        list_graph_docs = await create_knowledge_graph(collection_name=docs_collection)
        logger.info("[%s] create_knowledge_graph done — %s graph docs in %.1fs", session_id, len(list_graph_docs), time.perf_counter() - t0)

        # Delete the old per-repo graph_documents collection so we start fresh.
        try:
            client.delete_collection(collection_name=graph_collection)
            logger.info("[%s] Deleted existing Qdrant collection '%s'", session_id, graph_collection)
        except Exception:
            pass

        if list_graph_docs:
            # Prefix node IDs with the repo key so nodes from different repos never collide in Neo4j.
            prefix_graph_docs(list_graph_docs, cache_key or safe_key)

            await websocket.send_text("__LOG__:Storing graph in Neo4j...")
            logger.info("[%s] store_graph start...", session_id)
            t1 = time.perf_counter()
            store_graph(list_graph_docs)
            logger.info("[%s] store_graph done in %.1fs", session_id, time.perf_counter() - t1)

            await websocket.send_text("__LOG__:Embedding and storing in Qdrant...")
            logger.info("[%s] store_knowledge_graph start...", session_id)
            t2 = time.perf_counter()
            store_knowledge_graph(list_graph_docs, collection_name=graph_collection)
            logger.info("[%s] store_knowledge_graph done in %.1fs", session_id, time.perf_counter() - t2)

            if sha and cache_key:
                updated_cache = _load_cache()
                updated_entry = updated_cache.get(cache_key, {})
                if updated_entry.get('sha') == sha:
                    updated_entry['indexed'] = True
                    updated_cache[cache_key] = updated_entry
                    _save_cache(updated_cache)
                    logger.info("[%s] Marked %s as indexed in cache", session_id, cache_key)
        else:
            logger.warning("[%s] No graph docs returned from create_knowledge_graph — skipping indexing", session_id)
            await websocket.send_text("__LOG__:No documents found — skipping graph indexing")

        logger.info("[%s] Pipeline ready — starting chat loop", session_id)
        await websocket.send_text("__READY__")
        await run_chat_loop(websocket, session_id, graph_collection, docs_collection)

    except WebSocketDisconnect:
        logger.info("[%s] disconnected during indexing", session_id)
    except Exception as e:
        logger.exception("[%s] Indexing error: %s", session_id, e)
        try:
            await websocket.send_text(f"__ERROR__:{str(e)}")
        except Exception:
            pass

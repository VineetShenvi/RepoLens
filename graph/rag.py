from openai import OpenAI
from langchain_neo4j import Neo4jGraph
from dotenv import load_dotenv
from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny
from qdrant_client import QdrantClient
from graph.create_prompt import build_prompt
import re
import os
import logging
import time

load_dotenv()
logger = logging.getLogger(__name__)

openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

qdrant_client = QdrantClient(
    url=os.getenv('QDRANT_CLUSTER'),
    api_key=os.getenv('QDRANT_API_KEY')
)

neo4j_client=Neo4jGraph(
    url=os.getenv('NEO4J_URI'),
    username=os.getenv('NEO4J_USERNAME'),
    password=os.getenv('NEO4J_PASSWORD'),
    database=os.getenv('NEO4J_DATABASE')
)

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "what", "how", "why",
    "does", "do", "in", "of", "to", "for", "and", "or", "with", "from",
    "that", "this", "it", "be", "have", "has", "can", "could", "would",
    "should", "will", "which", "when", "where", "who", "me", "my", "you",
    "your", "we", "our", "they", "their", "get", "set", "use", "used",
    "work", "works", "call", "calls", "return", "returns", "run", "runs",
    "make", "makes", "take", "takes", "show", "shows", "find", "finds",
    "give", "gives", "need", "needs",
}

def _extract_identifiers(query: str) -> list:
    tokens = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', query)
    candidates = set()
    for t in tokens:
        if t.lower() in _STOPWORDS or len(t) < 3:
            continue
        if '_' in t or (t != t.lower() and t != t.upper()) or len(t) >= 5:
            candidates.add(t)
    return list(candidates)


def Graph_Query_Qdrant(message: str):
    logger.info("Graph_Query_Qdrant — query='%s...'", message[:80])
    t0 = time.perf_counter()
    message_embedding = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=message)
    logger.info("Graph_Query_Qdrant — embedding done in %.2fs", time.perf_counter() - t0)

    t1 = time.perf_counter()
    results = qdrant_client.query_points(
        collection_name="graph_documents",
        query=message_embedding.data[0].embedding,
        limit=7,
    )
    logger.info("Graph_Query_Qdrant — Qdrant search returned %s points in %.2fs", len(results.points), time.perf_counter() - t1)
    return results


def keyword_search_documents(query: str, limit: int = 5) -> list:
    identifiers = _extract_identifiers(query)
    if not identifiers:
        return []
    try:
        from qdrant_client.models import PayloadSchemaType
        qdrant_client.create_payload_index(
            collection_name="documents",
            field_name="name",
            field_schema=PayloadSchemaType.KEYWORD,
        )
        results, _ = qdrant_client.scroll(
            collection_name="documents",
            scroll_filter=Filter(
                must=[FieldCondition(key="name", match=MatchAny(any=identifiers))]
            ),
            with_payload=True,
            with_vectors=False,
            limit=limit,
        )
        chunks = [r.payload.get("text", "") for r in results if r.payload]
        logger.info("keyword_search_documents — identifiers=%s hits=%s", identifiers, len(chunks))
        return [c for c in chunks if c]
    except Exception as exc:
        logger.warning("keyword_search_documents — failed: %s", exc)
        return []

def traversal_query(results, message: str, keyword_chunks: list = None):
    logger.info("traversal_query — processing %s Qdrant results", len(results.points))
    t_start = time.perf_counter()
    traversal_results = []
    code_results = []
    graph_data = []

    for i, result in enumerate(results.points):
        graph_file = result.payload['file']
        graph_name = result.payload['name']
        logger.info("traversal_query — result %s: file=%s name=%s", i + 1, graph_file, graph_name)
        graph_data.append(f'file name : {graph_file}')
        graph_data.append(f'name : {graph_name}')

        code_text = result.payload['Code']
        code_results.append(code_text)
        node_ids = result.payload['Nodes']
        logger.info("traversal_query — result %s has %s nodes to traverse", i + 1, len(node_ids))

        for node_ID in node_ids:
            node_id = node_ID.get('node_id')
            logger.debug("traversal_query — Neo4j traversal for node_id=%s", node_id)
            t_neo = time.perf_counter()
            result_query = neo4j_client.query("""
            MATCH (n {id: $node_id})-[r*1..2]-(neighbor)
            RETURN n.id AS source,
                   type(r[-1]) AS relationship,
                   neighbor.id AS target,
                   labels(neighbor) AS target_labels
            """, params={"node_id": node_id})
            logger.debug("traversal_query — Neo4j returned %s rows for node=%s in %.2fs",
                         len(result_query), node_id, time.perf_counter() - t_neo)
            traversal_results.extend(result_query)

    seen_edges = set()
    traversal_lines = []
    for row in traversal_results:
        edge = (row['source'], row['relationship'], row['target'])
        if edge not in seen_edges:
            seen_edges.add(edge)
            traversal_lines.append(f"{row['source']} --[{row['relationship']}]--> {row['target']}")

    graph_traversal = "\n".join(traversal_lines)
    graph_description = ',\n'.join(graph_data)
    code_string = ', \n'.join(code_results)
    keyword_context = '\n\n'.join(keyword_chunks) if keyword_chunks else ''

    logger.info(
        "traversal_query — %s unique traversal edges; keyword_chunks=%s; building prompt",
        len(traversal_lines), len(keyword_chunks) if keyword_chunks else 0,
    )

    final_prompt = build_prompt(
        question=message,
        doc_context=code_string,
        graph_context=graph_description,
        traversal_text=graph_traversal,
        keyword_context=keyword_context,
    )

    logger.info("traversal_query — done in %.2fs; prompt_len=%s", time.perf_counter() - t_start, len(final_prompt))
    return final_prompt

from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PayloadSchemaType
from qdrant_client.models import PointStruct
from qdrant_client.http.exceptions import UnexpectedResponse
from dotenv import load_dotenv
import uuid
import os
import logging
import time
load_dotenv()
from openai import OpenAI
from graph.graph_docs_Qdrant import create_string_payload

logger = logging.getLogger(__name__)

openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

client = QdrantClient(
    url=os.getenv('QDRANT_CLUSTER'),
    api_key=os.getenv('QDRANT_API_KEY')
)

def store_docs(chunks:list, collection_name="documents"):
    logger.info("store_docs — collection=%s chunks=%s", collection_name, len(chunks))
    if not chunks:
        logger.warning("store_docs — no chunks to store, skipping")
        return

    try:
        client.get_collection(collection_name)
        collection_exists = True
    except UnexpectedResponse:
        collection_exists = False

    if not collection_exists:
        logger.info("store_docs — creating collection '%s'", collection_name)
        try:
            client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=1536, distance=Distance.COSINE)
            )
        except UnexpectedResponse as e:
            if e.status_code != 409:
                raise

    # Ensure keyword index on 'name' exists so payload filters work without error.
    # create_payload_index is idempotent — safe to call on every upsert.
    if collection_name == "documents":
        client.create_payload_index(
            collection_name=collection_name,
            field_name="name",
            field_schema=PayloadSchemaType.KEYWORD,
        )

    t0 = time.perf_counter()
    BATCH_SIZE = 256
    texts = [chunk['text'] for chunk in chunks]
    all_embeddings = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        response = openai_client.embeddings.create(model="text-embedding-3-small", input=batch)
        all_embeddings.extend(r.embedding for r in response.data)
        logger.info("store_docs — embedded %s/%s chunks", min(i + BATCH_SIZE, len(texts)), len(texts))

    points = [
        PointStruct(id=str(uuid.uuid4()), vector=emb, payload=chunk)
        for chunk, emb in zip(chunks, all_embeddings)
    ]

    logger.info("store_docs — upserting %s points to '%s'...", len(points), collection_name)
    client.upsert(collection_name=collection_name, points=points)
    logger.info("store_docs — done in %.2fs", time.perf_counter() - t0)

def store_knowledge_graph(graph_docs, collection_name='graph_documents'):
    logger.info("store_knowledge_graph — start; graph_docs=%s collection=%s", len(graph_docs), collection_name)
    t_start = time.perf_counter()
    list_graph_docs=create_string_payload(graph_docs)
    logger.info("store_knowledge_graph — payload strings built: %s entries", len(list_graph_docs))
    try:
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=1536,
                distance=Distance.COSINE
            )
        )
        logger.info("store_knowledge_graph — created Qdrant collection '%s'", collection_name)
    except Exception:
        logger.debug("store_knowledge_graph — collection '%s' already exists", collection_name)

    try:
        BATCH_SIZE = 256
        texts = [doc.get('TEXT') for doc in list_graph_docs]
        all_embeddings = []

        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i:i + BATCH_SIZE]
            response = openai_client.embeddings.create(model="text-embedding-3-small", input=batch)
            all_embeddings.extend(r.embedding for r in response.data)
            logger.info("store_knowledge_graph — embedded %s/%s graph docs", min(i + BATCH_SIZE, len(texts)), len(texts))

        points = [
            PointStruct(id=str(uuid.uuid4()), vector=emb, payload=doc.get('PAYLOAD'))
            for doc, emb in zip(list_graph_docs, all_embeddings)
        ]

        logger.info("store_knowledge_graph — upserting %s points to '%s'...", len(points), collection_name)
        client.upsert(collection_name=collection_name, points=points)
        logger.info("store_knowledge_graph — done in %.1fs; %s points stored", time.perf_counter() - t_start, len(points))
    except Exception as exc:
        logger.exception("store_knowledge_graph — failed: %s", exc)
            
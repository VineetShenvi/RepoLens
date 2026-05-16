from langchain_experimental.graph_transformers import LLMGraphTransformer
from langchain_openai import ChatOpenAI
from langchain_core.documents import Document
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from openai import OpenAI
import os
import asyncio
import time
import logging

load_dotenv()
logger = logging.getLogger(__name__)

openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

client = QdrantClient(
    url=os.getenv('QDRANT_CLUSTER'),
    api_key=os.getenv('QDRANT_API_KEY')
)

sempaphore=asyncio.Semaphore(3)
   
llm=ChatOpenAI(model='gpt-4o-mini', api_key=os.getenv('OPENAI_API_KEY'), temperature=0)

llm_transformer=LLMGraphTransformer(llm=llm)

async def create_knowledge_graph(collection_name:str='documents'):
    logger.info("create_knowledge_graph — start; collection=%s", collection_name)
    t_start = time.perf_counter()
    points=[]
    offset=None
    i=0

    while True:
        i+=1
        result, offset= client.scroll(
            collection_name=collection_name,
            limit=50,
            with_payload=True,
            with_vectors=False,
            offset=offset
        )
        logger.info("create_knowledge_graph — scroll batch %s: got %s points", i, len(result))
        points.extend(result)

        if offset is None:
            break

    logger.info("create_knowledge_graph — total points fetched from Qdrant: %s", len(points))

    document=[]
    skipped=0
    for point in points:
        payload = point.payload

        text = payload.get('text')
        if not text:
            logger.warning("create_knowledge_graph — skipping point %s — no text field in payload", point.id)
            skipped += 1
            continue

        doc = Document(
        page_content=text,
        metadata={
            'file':       payload.get('file', 'unknown'),
            'node_type':  payload.get('node_type', 'unknown'),
            'name':       payload.get('name', 'unknown'),
            'start_line': payload.get('start_line', 0),
            'end_line':   payload.get('end_line', 0),
            'Source_type': 'Graph_Document',
        }
    )
        document.append(doc)

    logger.info("create_knowledge_graph — %s docs to process, %s skipped (no text)", len(document), skipped)

    sempaphore=asyncio.Semaphore(3)
    completed = [0]
    async def semaphore_doc_processing(doc):
        async with sempaphore:
            logger.info("create_knowledge_graph — LLM graph extraction: %s (file=%s name=%s)",
                        completed[0] + 1, doc.metadata.get('file'), doc.metadata.get('name'))
            result = await llm_transformer.aconvert_to_graph_documents([doc])
            completed[0] += 1
            logger.info("create_knowledge_graph — completed %s/%s graph docs", completed[0], len(document))
            return result

    tasks=[semaphore_doc_processing(doc) for doc in document]
    graph_documents=await asyncio.gather(*tasks)
    list_graph_docs=[graph[0] for graph in graph_documents]
    logger.info("create_knowledge_graph — done; %s graph docs created in %.1fs", len(list_graph_docs), time.perf_counter() - t_start)
    return list_graph_docs





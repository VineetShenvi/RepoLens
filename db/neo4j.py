from langchain_neo4j import Neo4jGraph
from dotenv import load_dotenv
import time
import logging
import os

logger = logging.getLogger(__name__)

load_dotenv()

neo4j_client=Neo4jGraph(
    url=os.getenv('NEO4J_URI'),
    username=os.getenv('NEO4J_USERNAME'),
    password=os.getenv('NEO4J_PASSWORD')
)

def prefix_graph_docs(docs: list, repo_id: str) -> list:
    """Prefix every node ID with repo_id so multiple repos coexist in Neo4j without collisions."""
    prefix = repo_id + '::'
    for doc in docs:
        for node in doc.nodes:
            if not node.id.startswith(prefix):
                node.id = prefix + node.id
        for rel in doc.relationships:
            if not rel.source.id.startswith(prefix):
                rel.source.id = prefix + rel.source.id
            if not rel.target.id.startswith(prefix):
                rel.target.id = prefix + rel.target.id
    return docs


def store_graph(documents):
    logger.info("store_graph — start; %s documents", len(documents))
    t0 = time.perf_counter()
    neo4j_client.add_graph_documents(
        documents,
        baseEntityLabel=True,
        include_source=True
    )
    logger.info("store_graph — done in %.1fs", time.perf_counter() - t0)
from agents import Agent, Runner, trace, function_tool
from graph.rag import Graph_Query_Qdrant, rerank_results, traversal_query, keyword_search_documents
from openai.types.responses import ResponseTextDeltaEvent

from openai import OpenAI
from chatbot.prompt import CHAT_AGENT_INSTRUCTION
from dotenv import load_dotenv
import os
import logging
import time
load_dotenv()

logger = logging.getLogger(__name__)

client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))


def _make_chat_agent(graph_collection: str, docs_collection: str) -> Agent:
    @function_tool
    def Query_VectorDB(message: str):
        '''
        When to call:
        If the history isn't sufficient to answer user's question, use the tool to query VectorDB (Qdrant) and retrieve relevant docs.

        What to pass:
        message : user's question

        What does the function return:
        It returns the retrived information as a string to make it LLM ingestible.

        What to do next:
        Return the retrieved information to Chat_Agent to give user the response
        '''
        logger.info("Query_VectorDB — message='%s...' graph=%s docs=%s", message[:80], graph_collection, docs_collection)
        t0 = time.perf_counter()
        results = Graph_Query_Qdrant(message, collection_name=graph_collection)
        results = rerank_results(results, message)
        keyword_chunks = keyword_search_documents(message, collection_name=docs_collection)
        logger.info("Query_VectorDB — Qdrant returned %s graph points, %s keyword chunks in %.2fs",
                    len(results.points), len(keyword_chunks), time.perf_counter() - t0)
        t1 = time.perf_counter()
        final_string = traversal_query(results, message, keyword_chunks)
        logger.info("Query_VectorDB — traversal_query done in %.2fs; prompt_len=%s", time.perf_counter() - t1, len(final_string))
        return final_string

    return Agent(name='Chat_Agent', instructions=CHAT_AGENT_INSTRUCTION, tools=[Query_VectorDB], model='gpt-4o-mini')


async def get_answer(message: str, history: list, graph_collection: str = 'graph_documents', docs_collection: str = 'documents'):
    logger.info("get_answer — message='%s...' history_len=%s graph=%s docs=%s",
                message[:80], len(history), graph_collection, docs_collection)
    agent = _make_chat_agent(graph_collection, docs_collection)
    chunk_count = 0
    with trace(workflow_name="Github Repo", group_id=graph_collection):
        result = Runner.run_streamed(starting_agent=agent, input=(history + [{"role": "user", "content": message}]), context=history)
        async for event in result.stream_events():
            if event.type == 'raw_response_event' and isinstance(event.data, ResponseTextDeltaEvent):
                chunk_count += 1
                yield event.data.delta
    logger.info("get_answer — streamed %s chunks for message='%s...'", chunk_count, message[:60])

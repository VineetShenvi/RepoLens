from agents import Agent, Runner, trace, function_tool
from graph.rag import Graph_Query_Qdrant, traversal_query, keyword_search_documents
from openai.types.responses import ResponseTextDeltaEvent

from openai import OpenAI
from chatbot.prompt import CHAT_AGENT_INSTRUCTION
from dotenv import load_dotenv
import os
import logging
import time
load_dotenv()

logger = logging.getLogger(__name__)

@function_tool
def Query_VectorDB(message:str):
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
    logger.info("Query_VectorDB — message='%s...'", message[:80])
    t0 = time.perf_counter()
    results = Graph_Query_Qdrant(message)
    keyword_chunks = keyword_search_documents(message)
    logger.info("Query_VectorDB — Qdrant returned %s graph points, %s keyword chunks in %.2fs",
                len(results.points), len(keyword_chunks), time.perf_counter() - t0)
    t1 = time.perf_counter()
    final_string = traversal_query(results, message, keyword_chunks)
    logger.info("Query_VectorDB — traversal_query done in %.2fs; prompt_len=%s", time.perf_counter() - t1, len(final_string))
    return final_string

tools=[Query_VectorDB]

client=OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

Chat_agent=Agent(name='Chat_Agent', instructions=CHAT_AGENT_INSTRUCTION , tools=tools, model='gpt-4o-mini')

async def get_answer(message:str, history:list, collection='documents'):
    logger.info("get_answer — message='%s...' history_len=%s", message[:80], len(history))
    chunk_count = 0
    with trace(workflow_name="Github Repo", group_id=collection):
        result= Runner.run_streamed(starting_agent=Chat_agent, input=(history + [{"role": "user", "content": message}]), context=history)
        async for event in result.stream_events():
            if event.type=='raw_response_event' and isinstance(event.data, ResponseTextDeltaEvent):
                chunk_count += 1
                yield event.data.delta
    logger.info("get_answer — streamed %s chunks for message='%s...'", chunk_count, message[:60])


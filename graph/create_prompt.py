def build_prompt(question: str, doc_context: str, graph_context: str, traversal_text: str, keyword_context: str = ""):

    exact_match_section = f"""
-------------------------------
EXACT MATCH CHUNKS
-------------------------------
{keyword_context}
""" if keyword_context else ""

    prompt = f"""
Each source provides different information:
- Code Chunks: raw source code from semantically similar graph docs, useful for implementation details
- Graph Descriptions: entities and relationships extracted from code, useful for understanding structure
- Graph Traversal: how entities connect to each other, useful for understanding flow and dependencies
- Exact Match Chunks: raw source code matched by identifier name, highest confidence for specific lookups

-------------------------------
CODE CHUNKS
-------------------------------
{doc_context}

-------------------------------
GRAPH DESCRIPTIONS
-------------------------------
{graph_context}

-------------------------------
GRAPH TRAVERSAL
-------------------------------
{traversal_text}
{exact_match_section}
-------------------------------
USER'S QUESTION
-------------------------------
{question}

-------------------------------
INSTRUCTIONS
-------------------------------
- Synthesize information across all sources
- Exact Match Chunks and Code Chunks are ground truth — prefer them over Graph sources if they conflict
- If the answer is not in the context, say so clearly
- Reference specific file names and function names where relevant
"""
    return prompt

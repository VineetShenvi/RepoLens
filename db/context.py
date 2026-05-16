from contextvars import ContextVar

# Set before calling create_report() so create_chunks tool stores into the right collection.
# asyncio propagates ContextVar into spawned Tasks, so parallel tool calls inherit the value.
current_docs_collection: ContextVar[str] = ContextVar('docs_collection', default='documents')

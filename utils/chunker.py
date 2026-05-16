from tree_sitter import Language, Parser
import logging

logger = logging.getLogger(__name__)

def get_parser(language: str) -> Parser:
    import importlib
    lang_map = {
        "python":     ("tree_sitter_python", "language"),
        "javascript": ("tree_sitter_javascript", "language"),
        "typescript": ("tree_sitter_typescript", "language_typescript"),
        "tsx":        ("tree_sitter_typescript", "language_tsx"),
        "java":       ("tree_sitter_java", "language"),
        "cpp":        ("tree_sitter_cpp", "language"),
        "c":          ("tree_sitter_c", "language"),
        "rust":       ("tree_sitter_rust", "language"),
        "go":         ("tree_sitter_go", "language"),
    }
    if language not in lang_map:
        logger.error("get_parser — unsupported language: %s", language)
        raise ValueError(f"Unsupported language: {language}")
    logger.debug("get_parser — loading parser for language=%s", language)
    mod_name, fn_name = lang_map[language]
    mod = importlib.import_module(mod_name)
    return Parser(Language(getattr(mod, fn_name)()))
 
def chunk_tree(code_string: str, language: str, file_name: str = "unknown"):
    logger.info("chunk_tree — file=%s language=%s code_len=%s", file_name, language, len(code_string))
    parser = get_parser(language)
    tree = parser.parse(bytes(code_string, "utf8"))

    root = tree.root_node
    chunks = []

    SKIP_TYPES = {
        "comment", "newline", "", "module",
        "import_statement", "import_from_statement",
        "import_declaration", "preproc_include",
    }

    # only chunk these meaningful top-level types
    CHUNK_TYPES = {
        "function_definition",      # Python functions
        "class_definition",         # Python classes
        "method_declaration",       # Java methods
        "class_declaration",        # Java classes
        "function_declarator",      # C++ functions
        "struct_specifier",         # C++ structs
        "decorated_definition",     # Python decorators + function/class
    }

    for node in root.children:
        if node.type in SKIP_TYPES:
            continue

        if node.type in CHUNK_TYPES:
            name_node = node.child_by_field_name("name")
            name = code_string[name_node.start_byte:name_node.end_byte] if name_node else node.type
            chunk_text = code_string[node.start_byte:node.end_byte]

            chunks.append({
                "file":       file_name,
                "node_type":  node.type,
                "name":       name,
                'Source_type': 'Documents',
                "text":       chunk_text,
                "start_line": node.start_point[0] + 1,
                "end_line":   node.end_point[0] + 1,
            })

        # anything else at top level (assignments, expressions) — group together
        else:
            chunk_text = code_string[node.start_byte:node.end_byte].strip()
            if len(chunk_text) > 30:   # skip trivial one-liners
                chunks.append({
                    "file":       file_name,
                    "node_type":  node.type,
                    "name":       node.type,
                    'Source_type': 'Documents',
                    "text":       chunk_text,
                    "start_line": node.start_point[0] + 1,
                    "end_line":   node.end_point[0] + 1,
                })

    logger.info("chunk_tree — produced %s chunks for %s", len(chunks), file_name)
    return chunks
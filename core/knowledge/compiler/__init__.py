"""
core/knowledge/compiler
========================
The Semantic Compiler — the first true "compiler" stage of the Network
Knowledge Compiler (see docs/nkc_architecture_blueprint.md Part 3, "Semantic
Analysis Layer", and Part 4, "Knowledge Graph Compilation").

Turns parsed CLI/config/document text into canonical, vendor-neutral
`core.vendor.models.NormalizedObject` instances and publishes them, plus
their derived relationships, into the existing `core.knowledge_graph`
knowledge graph. Deterministic wherever possible — no LLM in this package.

Pipeline (see individual modules for detail):
  tokens.py            → Lexer/Tokenizer: text -> Token stream
  ast_builder.py        → Parser/AST Builder: tokens -> ASTNode tree
  semantic_analyzer.py  → Semantic Analyzer: AST -> SemanticFinding list
  canonicalizer.py      → Canonical Object Generator: SemanticFinding -> NormalizedObject
  relationships.py      → Relationship Compiler: NormalizedObject list -> GraphRelationship list
  validation.py         → Validation Engine: objects/relationships -> Issue list
  compiler.py           → SemanticCompiler: orchestrates the above + publishes
"""
from core.knowledge.compiler.compiler import (
    CompilationReport,
    SemanticCompiler,
    get_compiled_graph,
)

__all__ = ["CompilationReport", "SemanticCompiler", "get_compiled_graph"]

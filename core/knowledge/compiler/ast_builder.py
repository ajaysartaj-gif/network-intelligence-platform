"""
core/knowledge/compiler/ast_builder.py
========================================
Parser / AST Builder for line-oriented CLI/config/syslog text.

A parser that builds a tree IS an AST builder — this module implements
both under one name (see tokens.py's docstring for the same reasoning
about lexer/tokenizer).

Hierarchy comes from indentation depth (the universal signal across
Cisco/Arista/Aruba-style config, where sub-commands are indented under a
parent like `interface Gi0/1`), plus a Cisco-specific reset: a bare `!`
line terminates the current stanza and returns to top level. Neither
signal is required — flat show-command output (no indentation) simply
produces a single-level tree of children under the root, which is exactly
the tree shape that text needs.

Does NOT use an LLM. Does NOT understand JSON/YAML/XML — those formats
already parse into a native tree (a dict / ElementTree) upstream in
core/knowledge/parsers/structured_parser.py, and semantic_analyzer.py
consumes that tree directly via analyze_structured(), skipping this
module entirely (see docs/nkc_architecture_blueprint.md Part 3's scope
note — building a second generic tree parser for formats that already
have one would duplicate existing code).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from core.knowledge.compiler.tokens import Token, TokenType, tokenize_line


@dataclass
class ASTNode:
    kind: str                                  # "root" | "command" | "comment" | "text"
    value: str                                  # raw, stripped source line (empty for root)
    line: int                                   # 1-indexed source line (0 for root)
    tokens: List[Token] = field(default_factory=list)
    children: List["ASTNode"] = field(default_factory=list)
    parent: Optional["ASTNode"] = None

    def add_child(self, child: "ASTNode") -> None:
        child.parent = self
        self.children.append(child)

    def walk(self):
        """Depth-first iterator over this node and every descendant."""
        yield self
        for c in self.children:
            yield from c.walk()

    def text_of_subtree(self) -> str:
        """Rejoin this node and its descendants' raw lines, in source order —
        useful for extractors that need the whole stanza (e.g. an interface
        block's description + address + mtu lines together)."""
        lines = [n.value for n in self.walk() if n.value]
        return "\n".join(lines)


def _classify_kind(tokens: List[Token]) -> str:
    if not tokens:
        return "text"
    if all(t.type == TokenType.COMMENT for t in tokens):
        return "comment"
    if tokens[0].type == TokenType.COMMAND:
        return "command"
    return "text"


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def build_ast(text: str) -> ASTNode:
    """
    Build an AST from line-oriented CLI/config/syslog text. Returns the
    root node (kind="root", line=0); every parsed line is a descendant,
    nested by indentation depth with a `!`-line stanza reset.
    """
    root = ASTNode(kind="root", value="", line=0)
    # ancestor stack of (indent_level, node); root always at the bottom
    stack: List[tuple] = [(-1, root)]

    for i, raw_line in enumerate(text.splitlines()):
        lineno = i + 1
        stripped = raw_line.strip()
        if not stripped:
            continue  # blank lines are separators, not nodes

        if stripped == "!":
            # Cisco stanza terminator — reset to top level, emit no node.
            stack = [(-1, root)]
            continue

        indent = _indent_of(raw_line)
        tokens = tokenize_line(stripped, lineno)
        node = ASTNode(kind=_classify_kind(tokens), value=stripped, line=lineno, tokens=tokens)

        while len(stack) > 1 and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        parent.add_child(node)
        stack.append((indent, node))

    return root

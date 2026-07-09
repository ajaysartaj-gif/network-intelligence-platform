"""
core/knowledge/compiler/tokens.py
==================================
Lexer / Tokenizer for line-oriented CLI/config/syslog text.

A lexer and a tokenizer are the same compiler stage (turning characters
into a token stream) — this module implements both under one name rather
than as two files that would do the same thing.

Deterministic only: one master regex, ordered most-specific-first (same
"ordered rules, first match wins" pattern as
core/topology/role_classifier.py::classify_role). A token's TYPE is a
purely LEXICAL category (is this text a number, an IPv4 address, a known
keyword, a comment...); assigning MEANING to a token in context (e.g. "this
identifier is a VRF name because it follows the keyword 'vrf'") is the
Semantic Analyzer's job (semantic_analyzer.py), not the lexer's — conflating
the two is what makes lexers unmaintainable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import List


class TokenType(str, Enum):
    COMMENT          = "comment"           # '!' or '#' to end of line
    IPV4_CIDR        = "ipv4_cidr"         # 10.0.0.0/24
    MASK             = "mask"              # 255.255.255.0
    IPV4             = "ipv4"              # 10.0.0.1
    STATE_WORD       = "state_word"        # up/down/full/exstart/2-way/...
    PROTOCOL_KEYWORD = "protocol_keyword"  # ospf/bgp/eigrp/isis/...
    KEYWORD          = "keyword"           # interface/vrf/permit/deny/...
    ERROR_WORD       = "error_word"        # %OSPF-5-ADJCHG style IOS facility codes
    WARNING_WORD     = "warning_word"      # warning/deprecated/caution
    INTERFACE_NAME   = "interface_name"    # GigabitEthernet0/1, Vlan10, ge-0/0/1...
    NUMBER           = "number"            # bare integer
    IDENTIFIER       = "identifier"        # generic word/name
    TEXT             = "text"              # fallback: punctuation/unrecognized
    COMMAND          = "command"           # re-tagged: first token on a line


@dataclass
class Token:
    type: TokenType
    value: str
    line: int   # 1-indexed source line number
    col: int    # 0-indexed column offset within the line


# Keyword lists are intentionally small and additive — extend by appending,
# never by restructuring the ordering logic below.
_KEYWORDS = (
    "interface", "ip", "ipv6", "vrf", "forwarding", "address", "router",
    "network", "area", "permit", "deny", "access-list", "access-group",
    "vlan", "class-map", "policy-map", "service-policy", "nat", "pool",
    "mtu", "hello-interval", "dead-interval", "description", "shutdown",
    "no", "exit", "end", "neighbor", "remote-as", "route-target", "rd",
    "switchport", "encapsulation", "zone-pair", "inside", "outside",
    "overload", "static", "route", "gateway", "priority", "timers",
)
_PROTOCOL_KEYWORDS = (
    "ospf", "ospfv3", "bgp", "eigrp", "isis", "is-is", "rip", "hsrp",
    "vrrp", "glbp", "mpls", "ldp", "bfd", "lacp", "stp", "vxlan", "evpn",
)
_STATE_WORDS = (
    "up", "down", "full", "2-way", "exstart", "exchange", "loading",
    "init", "attempt", "established", "idle", "active", "connect",
    "admin-down", "administratively down", "deprecated", "blocking",
    "forwarding", "learning", "listening", "disabled", "err-disabled",
)
_WARNING_WORDS = ("warning", "deprecated", "caution", "notice")

_INTERFACE_PREFIX = (
    r"GigabitEthernet|TenGigabitEthernet|FortyGigE|HundredGigE|"
    r"FastEthernet|Ethernet|Port-channel|Po|Loopback|Lo|Vlan|Tunnel|Tu|"
    r"Serial|Se|Management|mgmt|ge-|xe-|et-|irb"
)

_TOKEN_SPEC = [
    (TokenType.COMMENT,   r"(?:!|\#)[^\n]*"),
    (TokenType.IPV4_CIDR, r"\b(?:\d{1,3}\.){3}\d{1,3}/\d{1,2}\b"),
    (TokenType.MASK,      r"\b255\.(?:255|254|252|248|240|224|192|128|0)\."
                          r"(?:255|254|252|248|240|224|192|128|0)\."
                          r"(?:255|254|252|248|240|224|192|128|0)\b"),
    (TokenType.IPV4,      r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    (TokenType.STATE_WORD, r"(?i:\b(?:" + "|".join(re.escape(w) for w in _STATE_WORDS) + r")\b)"),
    (TokenType.PROTOCOL_KEYWORD, r"(?i:\b(?:" + "|".join(re.escape(w) for w in _PROTOCOL_KEYWORDS) + r")\b)"),
    (TokenType.KEYWORD,   r"(?i:\b(?:" + "|".join(re.escape(w) for w in _KEYWORDS) + r")\b)"),
    (TokenType.ERROR_WORD, r"%[A-Z0-9_\-]+"),
    (TokenType.WARNING_WORD, r"(?i:\b(?:" + "|".join(re.escape(w) for w in _WARNING_WORDS) + r")\b)"),
    (TokenType.INTERFACE_NAME, r"\b(?:" + _INTERFACE_PREFIX + r")[\w/\.:\-]*\b"),
    (TokenType.NUMBER,    r"\b\d+\b"),
    (TokenType.IDENTIFIER, r"[A-Za-z_][\w\-\.]*"),
    (TokenType.TEXT,      r"\S"),   # catch-all single char; guarantees progress
]

_MASTER_RE = re.compile(
    "|".join(f"(?P<{t.name}>{pat})" for t, pat in _TOKEN_SPEC) + r"|(?P<WS>\s+)"
)


def tokenize_line(line: str, lineno: int) -> List[Token]:
    """Tokenize one line of text. Whitespace is consumed, not emitted."""
    tokens: List[Token] = []
    for m in _MASTER_RE.finditer(line):
        if m.lastgroup == "WS":
            continue
        ttype = TokenType[m.lastgroup]
        tokens.append(Token(type=ttype, value=m.group(), line=lineno, col=m.start()))

    # Re-tag the first non-comment token on the line as COMMAND — this is a
    # positional property (what starts the line), not a lexical one, so it's
    # applied after the fact rather than folded into _TOKEN_SPEC.
    for tok in tokens:
        if tok.type == TokenType.COMMENT:
            continue
        if tok.type in (TokenType.IDENTIFIER, TokenType.KEYWORD, TokenType.PROTOCOL_KEYWORD):
            tok.type = TokenType.COMMAND
        break
    return tokens


def tokenize(text: str) -> List[List[Token]]:
    """Tokenize a multi-line document. Returns one token list per line
    (1-indexed line numbers preserved in each Token)."""
    return [tokenize_line(line, i + 1) for i, line in enumerate((text or "").splitlines())]

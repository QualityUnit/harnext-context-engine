"""Best-effort guard that rejects mutating Cypher.

Strips string literals and comments, then looks for write keywords as whole
tokens. Not a sandbox — if you need a hard guarantee, give FalkorDB a
read-only user. See README §Mutation guard.
"""

import re

_FORBIDDEN = (
    "CREATE",
    "MERGE",
    "SET",
    "DELETE",
    "REMOVE",
    "DROP",
    "CALL",
    "LOAD",
    "FOREACH",
)

# Strings: '...' or "..." with \-escapes. Comments: // line, /* block */.
_STRIP_PATTERN = re.compile(
    r"""
    '(?:\\.|[^'\\])*'      |  # single-quoted string
    "(?:\\.|[^"\\])*"      |  # double-quoted string
    //[^\n]*               |  # // line comment
    /\*[\s\S]*?\*/            # /* block comment */
    """,
    re.VERBOSE,
)

_KEYWORD_PATTERN = re.compile(
    r"\b(" + "|".join(_FORBIDDEN) + r")\b", re.IGNORECASE
)


class CypherWriteError(ValueError):
    """Raised when read_cypher receives a query that looks like a mutation."""


def reject_writes(query: str) -> None:
    stripped = _STRIP_PATTERN.sub(" ", query)
    match = _KEYWORD_PATTERN.search(stripped)
    if match:
        raise CypherWriteError(
            f"read_cypher rejects mutating/procedure keyword '{match.group(1).upper()}'. "
            "Use MATCH … RETURN only."
        )

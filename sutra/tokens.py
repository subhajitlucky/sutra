"""SUTRA token types."""

from enum import Enum, auto


class TokenType(Enum):
    # Keywords
    INTENT = auto()
    FACT = auto()
    QUERY = auto()
    OFFER = auto()
    ACCEPT = auto()
    REJECT = auto()
    COMMIT = auto()
    ACT = auto()

    # Secondary keywords
    FROM = auto()
    TO = auto()
    BY = auto()
    REASON = auto()
    ID = auto()

    # Literals
    STRING = auto()
    NUMBER = auto()
    TRUE = auto()
    FALSE = auto()
    NULL = auto()

    # Identifiers
    IDENTIFIER = auto()

    # Punctuation
    LPAREN = auto()      # (
    RPAREN = auto()      # )
    LBRACE = auto()      # {
    RBRACE = auto()      # }
    LBRACKET = auto()    # [
    RBRACKET = auto()    # ]
    COMMA = auto()       # ,
    COLON = auto()       # :
    SEMICOLON = auto()   # ;
    EQUALS = auto()      # =

    # Header
    HASH = auto()        # #

    # Special
    NEWLINE = auto()
    EOF = auto()


KEYWORDS = {
    "INTENT": TokenType.INTENT,
    "FACT": TokenType.FACT,
    "QUERY": TokenType.QUERY,
    "OFFER": TokenType.OFFER,
    "ACCEPT": TokenType.ACCEPT,
    "REJECT": TokenType.REJECT,
    "COMMIT": TokenType.COMMIT,
    "ACT": TokenType.ACT,
    "FROM": TokenType.FROM,
    "TO": TokenType.TO,
    "BY": TokenType.BY,
    "REASON": TokenType.REASON,
    "id": TokenType.ID,
    "true": TokenType.TRUE,
    "false": TokenType.FALSE,
    "null": TokenType.NULL,
}


class Token:
    __slots__ = ("type", "value", "line", "col")

    def __init__(self, type: TokenType, value: str, line: int = 0, col: int = 0):
        self.type = type
        self.value = value
        self.line = line
        self.col = col

    def __repr__(self):
        return f"Token({self.type.name}, {self.value!r}, L{self.line}:{self.col})"

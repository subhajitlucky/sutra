"""SUTRA v0.1 — Lexer (Tokenizer)

Converts raw SUTRA source text into a stream of tokens.
"""

from .tokens import Token, TokenType, KEYWORDS


class LexerError(Exception):
    def __init__(self, message: str, line: int, col: int):
        super().__init__(f"[Line {line}, Col {col}] {message}")
        self.line = line
        self.col = col


class Lexer:
    def __init__(self, source: str):
        self.source = source
        self.pos = 0
        self.line = 1
        self.col = 1
        self.tokens: list[Token] = []

    def _peek(self) -> str | None:
        if self.pos < len(self.source):
            return self.source[self.pos]
        return None

    def _advance(self) -> str:
        ch = self.source[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def _skip_whitespace(self):
        while self.pos < len(self.source) and self.source[self.pos] in (" ", "\t", "\r"):
            self._advance()

    def _skip_comment(self):
        """Skip // line comments."""
        if (
            self.pos + 1 < len(self.source)
            and self.source[self.pos] == "/"
            and self.source[self.pos + 1] == "/"
        ):
            while self.pos < len(self.source) and self.source[self.pos] != "\n":
                self._advance()

    def _read_string(self) -> Token:
        line, col = self.line, self.col
        self._advance()  # skip opening "
        buf = []
        while self.pos < len(self.source):
            ch = self.source[self.pos]
            if ch == '"':
                self._advance()  # skip closing "
                return Token(TokenType.STRING, "".join(buf), line, col)
            if ch == "\\":
                self._advance()
                esc = self._advance()
                escape_map = {"n": "\n", "t": "\t", "\\": "\\", '"': '"'}
                buf.append(escape_map.get(esc, esc))
            else:
                buf.append(ch)
                self._advance()
        raise LexerError("Unterminated string", line, col)

    def _read_number(self) -> Token:
        line, col = self.line, self.col
        buf = []
        if self._peek() == "-":
            buf.append(self._advance())
        while self.pos < len(self.source) and self.source[self.pos].isdigit():
            buf.append(self._advance())
        if self.pos < len(self.source) and self.source[self.pos] == ".":
            buf.append(self._advance())
            while self.pos < len(self.source) and self.source[self.pos].isdigit():
                buf.append(self._advance())
        return Token(TokenType.NUMBER, "".join(buf), line, col)

    def _read_identifier(self) -> Token:
        line, col = self.line, self.col
        buf = []
        while self.pos < len(self.source) and (
            self.source[self.pos].isalnum() or self.source[self.pos] == "_"
        ):
            buf.append(self._advance())
        word = "".join(buf)
        token_type = KEYWORDS.get(word, TokenType.IDENTIFIER)
        return Token(token_type, word, line, col)

    def tokenize(self) -> list[Token]:
        self.tokens = []
        while self.pos < len(self.source):
            self._skip_whitespace()
            self._skip_comment()

            if self.pos >= len(self.source):
                break

            ch = self.source[self.pos]
            line, col = self.line, self.col

            # Newlines
            if ch == "\n":
                self._advance()
                self.tokens.append(Token(TokenType.NEWLINE, "\\n", line, col))
                continue

            # Single-char tokens
            simple = {
                "(": TokenType.LPAREN,
                ")": TokenType.RPAREN,
                "{": TokenType.LBRACE,
                "}": TokenType.RBRACE,
                "[": TokenType.LBRACKET,
                "]": TokenType.RBRACKET,
                ",": TokenType.COMMA,
                ":": TokenType.COLON,
                ";": TokenType.SEMICOLON,
                "=": TokenType.EQUALS,
                "#": TokenType.HASH,
            }
            if ch in simple:
                self._advance()
                self.tokens.append(Token(simple[ch], ch, line, col))
                continue

            # Strings
            if ch == '"':
                self.tokens.append(self._read_string())
                continue

            # Numbers
            if ch.isdigit() or (ch == "-" and self.pos + 1 < len(self.source) and self.source[self.pos + 1].isdigit()):
                self.tokens.append(self._read_number())
                continue

            # Identifiers and keywords
            if ch.isalpha() or ch == "_":
                self.tokens.append(self._read_identifier())
                continue

            raise LexerError(f"Unexpected character: {ch!r}", line, col)

        self.tokens.append(Token(TokenType.EOF, "", self.line, self.col))
        return self.tokens

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
    # Class-level lookup table — avoids per-iteration dict creation
    _SIMPLE_TOKENS = {
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
    _ESCAPE_MAP = {"n": "\n", "t": "\t", "\\": "\\", '"': '"'}
    _WHITESPACE = frozenset((" ", "\t", "\r"))

    def __init__(self, source: str):
        self.source = source
        self.pos = 0
        self.line = 1
        self.col = 1
        self.tokens: list[Token] = []
        self._len = len(source)  # cache length

    def _peek(self) -> str | None:
        if self.pos < self._len:
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
        src = self.source
        pos = self.pos
        length = self._len
        ws = self._WHITESPACE
        while pos < length and src[pos] in ws:
            if src[pos] == "\n":
                self.line += 1
                self.col = 1
            else:
                self.col += 1
            pos += 1
        self.pos = pos

    def _skip_comment(self):
        """Skip // line comments."""
        if (
            self.pos + 1 < self._len
            and self.source[self.pos] == "/"
            and self.source[self.pos + 1] == "/"
        ):
            src = self.source
            pos = self.pos
            length = self._len
            while pos < length and src[pos] != "\n":
                pos += 1
            self.col += (pos - self.pos)
            self.pos = pos

    def _read_string(self) -> Token:
        line, col = self.line, self.col
        self._advance()  # skip opening "
        src = self.source
        pos = self.pos
        length = self._len
        escape_map = self._ESCAPE_MAP
        buf = []
        buf_append = buf.append
        while pos < length:
            ch = src[pos]
            if ch == '"':
                pos += 1
                self.col += 1
                self.pos = pos
                return Token(TokenType.STRING, "".join(buf), line, col)
            if ch == "\\":
                pos += 1
                self.col += 1
                esc = src[pos]
                pos += 1
                self.col += 1
                buf_append(escape_map.get(esc, esc))
            else:
                buf_append(ch)
                pos += 1
                if ch == "\n":
                    self.line += 1
                    self.col = 1
                else:
                    self.col += 1
        self.pos = pos
        raise LexerError("Unterminated string", line, col)

    def _read_number(self) -> Token:
        line, col = self.line, self.col
        src = self.source
        start = self.pos
        pos = self.pos
        length = self._len
        if src[pos] == "-":
            pos += 1
        while pos < length and src[pos].isdigit():
            pos += 1
        if pos < length and src[pos] == ".":
            pos += 1
            while pos < length and src[pos].isdigit():
                pos += 1
        advance = pos - start
        self.col += advance
        self.pos = pos
        return Token(TokenType.NUMBER, src[start:pos], line, col)

    def _read_identifier(self) -> Token:
        line, col = self.line, self.col
        src = self.source
        start = self.pos
        pos = self.pos
        length = self._len
        while pos < length and (src[pos].isalnum() or src[pos] == "_"):
            pos += 1
        advance = pos - start
        self.col += advance
        self.pos = pos
        word = src[start:pos]
        token_type = KEYWORDS.get(word, TokenType.IDENTIFIER)
        return Token(token_type, word, line, col)

    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        tokens_append = tokens.append
        simple = self._SIMPLE_TOKENS
        src = self.source

        while self.pos < self._len:
            self._skip_whitespace()
            self._skip_comment()

            if self.pos >= self._len:
                break

            ch = src[self.pos]
            line, col = self.line, self.col

            # Newlines
            if ch == "\n":
                self._advance()
                tokens_append(Token(TokenType.NEWLINE, "\\n", line, col))
                continue

            # Single-char tokens
            tt = simple.get(ch)
            if tt is not None:
                self._advance()
                tokens_append(Token(tt, ch, line, col))
                continue

            # Strings
            if ch == '"':
                tokens_append(self._read_string())
                continue

            # Numbers
            if ch.isdigit() or (ch == "-" and self.pos + 1 < self._len and src[self.pos + 1].isdigit()):
                tokens_append(self._read_number())
                continue

            # Identifiers and keywords
            if ch.isalpha() or ch == "_":
                tokens_append(self._read_identifier())
                continue

            raise LexerError(f"Unexpected character: {ch!r}", line, col)

        tokens_append(Token(TokenType.EOF, "", self.line, self.col))
        self.tokens = tokens
        return tokens

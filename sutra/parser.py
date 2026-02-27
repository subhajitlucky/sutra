"""SUTRA v0.1 — Recursive Descent Parser

Converts a token stream into an AST (Program node).
"""

from __future__ import annotations

from .tokens import Token, TokenType
from .ast_nodes import (
    Program, Header,
    IntentStmt, FactStmt, QueryStmt, OfferStmt, OfferField,
    AcceptStmt, RejectStmt, CommitStmt, ActStmt,
    Predicate, NamedArg,
    StringVal, NumberVal, BoolVal, NullVal, MapVal, ListVal,
)


class ParseError(Exception):
    def __init__(self, message: str, token: Token):
        super().__init__(f"[Line {token.line}, Col {token.col}] {message}")
        self.token = token


class Parser:
    def __init__(self, tokens: list[Token]):
        # Filter out newlines — they are insignificant in SUTRA
        self.tokens = [t for t in tokens if t.type != TokenType.NEWLINE]
        self.pos = 0

    # ── helpers ─────────────────────────────────────────

    def _current(self) -> Token:
        return self.tokens[self.pos]

    def _peek_type(self) -> TokenType:
        return self.tokens[self.pos].type

    def _at(self, *types: TokenType) -> bool:
        return self._peek_type() in types

    def _expect(self, tt: TokenType, msg: str = "") -> Token:
        tok = self._current()
        if tok.type != tt:
            raise ParseError(msg or f"Expected {tt.name}, got {tok.type.name}", tok)
        self.pos += 1
        return tok

    def _match(self, *types: TokenType) -> Token | None:
        if self._peek_type() in types:
            tok = self._current()
            self.pos += 1
            return tok
        return None

    # ── top level ───────────────────────────────────────

    def parse(self) -> Program:
        headers = self._parse_headers()
        statements = []
        while not self._at(TokenType.EOF):
            statements.append(self._parse_statement())
        return Program(headers=headers, statements=statements)

    # ── headers ─────────────────────────────────────────

    def _parse_headers(self) -> list[Header]:
        headers: list[Header] = []
        while self._at(TokenType.HASH):
            self._expect(TokenType.HASH)
            key_tok = self._expect(TokenType.IDENTIFIER, "Expected header key after #")
            val_tok = self._expect(TokenType.STRING, "Expected string value for header")
            headers.append(Header(key=key_tok.value, value=val_tok.value))
        return headers

    # ── statements ──────────────────────────────────────

    def _parse_statement(self):
        tt = self._peek_type()
        dispatch = {
            TokenType.INTENT: self._parse_intent,
            TokenType.FACT: self._parse_fact,
            TokenType.QUERY: self._parse_query,
            TokenType.OFFER: self._parse_offer,
            TokenType.ACCEPT: self._parse_accept,
            TokenType.REJECT: self._parse_reject,
            TokenType.COMMIT: self._parse_commit,
            TokenType.ACT: self._parse_act,
        }
        fn = dispatch.get(tt)
        if fn is None:
            raise ParseError(f"Unexpected token: {self._current().value!r}", self._current())
        return fn()

    def _parse_intent(self) -> IntentStmt:
        self._expect(TokenType.INTENT)
        pred = self._parse_predicate()
        self._expect(TokenType.SEMICOLON, "Expected ';' after INTENT")
        return IntentStmt(predicate=pred)

    def _parse_fact(self) -> FactStmt:
        self._expect(TokenType.FACT)
        pred = self._parse_predicate()
        self._expect(TokenType.SEMICOLON, "Expected ';' after FACT")
        return FactStmt(predicate=pred)

    def _parse_query(self) -> QueryStmt:
        self._expect(TokenType.QUERY)
        pred = self._parse_predicate()
        self._expect(TokenType.FROM, "Expected 'FROM' in QUERY")
        agent = self._expect(TokenType.STRING, "Expected agent string after FROM")
        self._expect(TokenType.SEMICOLON, "Expected ';' after QUERY")
        return QueryStmt(predicate=pred, from_agent=agent.value)

    def _parse_offer(self) -> OfferStmt:
        self._expect(TokenType.OFFER)
        self._expect(TokenType.ID, "Expected 'id' in OFFER")
        self._expect(TokenType.EQUALS, "Expected '=' after 'id'")
        offer_id = self._expect(TokenType.STRING, "Expected offer id string")
        self._expect(TokenType.TO, "Expected 'TO' in OFFER")
        to_agent = self._expect(TokenType.STRING, "Expected agent string after TO")
        self._expect(TokenType.LBRACE, "Expected '{' to open OFFER body")
        fields = self._parse_offer_fields()
        self._expect(TokenType.RBRACE, "Expected '}' to close OFFER body")
        self._expect(TokenType.SEMICOLON, "Expected ';' after OFFER")
        return OfferStmt(offer_id=offer_id.value, to_agent=to_agent.value, fields=fields)

    def _parse_offer_fields(self) -> list[OfferField]:
        fields: list[OfferField] = []
        while not self._at(TokenType.RBRACE):
            key = self._expect(TokenType.IDENTIFIER, "Expected field name in OFFER body")
            self._expect(TokenType.COLON, "Expected ':' after field name")
            val = self._parse_value()
            fields.append(OfferField(key=key.value, value=val))
            self._match(TokenType.COMMA)  # optional trailing comma
        return fields

    def _parse_accept(self) -> AcceptStmt:
        self._expect(TokenType.ACCEPT)
        offer_id = self._expect(TokenType.STRING, "Expected offer id string")
        self._expect(TokenType.SEMICOLON, "Expected ';' after ACCEPT")
        return AcceptStmt(offer_id=offer_id.value)

    def _parse_reject(self) -> RejectStmt:
        self._expect(TokenType.REJECT)
        offer_id = self._expect(TokenType.STRING, "Expected offer id string")
        reason = None
        if self._match(TokenType.REASON):
            reason_tok = self._expect(TokenType.STRING, "Expected reason string")
            reason = reason_tok.value
        self._expect(TokenType.SEMICOLON, "Expected ';' after REJECT")
        return RejectStmt(offer_id=offer_id.value, reason=reason)

    def _parse_commit(self) -> CommitStmt:
        self._expect(TokenType.COMMIT)
        pred = self._parse_predicate()
        deadline = None
        if self._match(TokenType.BY):
            dl_tok = self._expect(TokenType.STRING, "Expected deadline string after BY")
            deadline = dl_tok.value
        self._expect(TokenType.SEMICOLON, "Expected ';' after COMMIT")
        return CommitStmt(predicate=pred, deadline=deadline)

    def _parse_act(self) -> ActStmt:
        self._expect(TokenType.ACT)
        pred = self._parse_predicate()
        self._expect(TokenType.SEMICOLON, "Expected ';' after ACT")
        return ActStmt(predicate=pred)

    # ── predicate ───────────────────────────────────────

    def _parse_predicate(self) -> Predicate:
        name = self._expect(TokenType.IDENTIFIER, "Expected predicate name")
        self._expect(TokenType.LPAREN, "Expected '(' after predicate name")
        args: list[NamedArg] = []
        while not self._at(TokenType.RPAREN):
            arg_name = self._expect(TokenType.IDENTIFIER, "Expected argument name")
            self._expect(TokenType.EQUALS, "Expected '=' after argument name")
            arg_val = self._parse_value()
            args.append(NamedArg(name=arg_name.value, value=arg_val))
            self._match(TokenType.COMMA)  # optional
        self._expect(TokenType.RPAREN, "Expected ')' to close predicate")
        return Predicate(name=name.value, args=args)

    # ── values ──────────────────────────────────────────

    def _parse_value(self):
        tok = self._current()

        if tok.type == TokenType.STRING:
            self.pos += 1
            return StringVal(tok.value)

        if tok.type == TokenType.NUMBER:
            self.pos += 1
            return NumberVal(float(tok.value))

        if tok.type == TokenType.TRUE:
            self.pos += 1
            return BoolVal(True)

        if tok.type == TokenType.FALSE:
            self.pos += 1
            return BoolVal(False)

        if tok.type == TokenType.NULL:
            self.pos += 1
            return NullVal()

        if tok.type == TokenType.LBRACE:
            return self._parse_map()

        if tok.type == TokenType.LBRACKET:
            return self._parse_list()

        raise ParseError(f"Expected a value, got {tok.type.name}", tok)

    def _parse_map(self) -> MapVal:
        self._expect(TokenType.LBRACE)
        entries: dict[str, any] = {}
        while not self._at(TokenType.RBRACE):
            key = self._expect(TokenType.IDENTIFIER, "Expected map key")
            self._expect(TokenType.COLON, "Expected ':' in map entry")
            val = self._parse_value()
            entries[key.value] = val
            self._match(TokenType.COMMA)
        self._expect(TokenType.RBRACE)
        return MapVal(entries=entries)

    def _parse_list(self) -> ListVal:
        self._expect(TokenType.LBRACKET)
        items = []
        while not self._at(TokenType.RBRACKET):
            items.append(self._parse_value())
            self._match(TokenType.COMMA)
        self._expect(TokenType.RBRACKET)
        return ListVal(items=items)

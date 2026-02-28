/**
 * SUTRA v0.5 — JavaScript Interpreter
 *
 * A complete, faithful port of the Python SUTRA lexer, parser, AST,
 * interpreter, and agent model to JavaScript.
 *
 * Runs in browsers, Node.js, Deno, and any WASM-capable runtime.
 * Zero dependencies. ~600 lines.
 *
 * Usage:
 *   const { SutraVM } = require("./sutra.js");   // Node
 *   const vm = new SutraVM("my-agent");
 *   const result = vm.execute('FACT known(item="TV", price=50000);');
 *   console.log(result);
 */

// ════════════════════════════════════════════════════════
//  TOKENS
// ════════════════════════════════════════════════════════

const T = Object.freeze({
  // Keywords (8 core)
  INTENT: "INTENT", FACT: "FACT", QUERY: "QUERY", OFFER: "OFFER",
  ACCEPT: "ACCEPT", REJECT: "REJECT", COMMIT: "COMMIT", ACT: "ACT",
  // Secondary keywords
  FROM: "FROM", TO: "TO", BY: "BY", REASON: "REASON", ID: "ID",
  // Literals
  STRING: "STRING", NUMBER: "NUMBER", TRUE: "TRUE", FALSE: "FALSE", NULL: "NULL",
  // Identifiers
  IDENTIFIER: "IDENTIFIER",
  // Punctuation
  LPAREN: "LPAREN", RPAREN: "RPAREN",
  LBRACE: "LBRACE", RBRACE: "RBRACE",
  LBRACKET: "LBRACKET", RBRACKET: "RBRACKET",
  COMMA: "COMMA", COLON: "COLON", SEMICOLON: "SEMICOLON", EQUALS: "EQUALS",
  HASH: "HASH",
  // Special
  NEWLINE: "NEWLINE", EOF: "EOF",
});

const KEYWORDS = {
  INTENT: T.INTENT, FACT: T.FACT, QUERY: T.QUERY, OFFER: T.OFFER,
  ACCEPT: T.ACCEPT, REJECT: T.REJECT, COMMIT: T.COMMIT, ACT: T.ACT,
  FROM: T.FROM, TO: T.TO, BY: T.BY, REASON: T.REASON,
  id: T.ID, true: T.TRUE, false: T.FALSE, null: T.NULL,
};

class Token {
  constructor(type, value, line = 0, col = 0) {
    this.type = type;
    this.value = value;
    this.line = line;
    this.col = col;
  }
  toString() { return `Token(${this.type}, ${JSON.stringify(this.value)}, L${this.line}:${this.col})`; }
}

// ════════════════════════════════════════════════════════
//  LEXER
// ════════════════════════════════════════════════════════

class LexerError extends Error {
  constructor(msg, line, col) {
    super(`[Line ${line}, Col ${col}] ${msg}`);
    this.line = line;
    this.col = col;
  }
}

class Lexer {
  constructor(source) {
    this.source = source;
    this.pos = 0;
    this.line = 1;
    this.col = 1;
    this.tokens = [];
  }

  _peek() { return this.pos < this.source.length ? this.source[this.pos] : null; }

  _advance() {
    const ch = this.source[this.pos];
    this.pos++;
    if (ch === "\n") { this.line++; this.col = 1; }
    else { this.col++; }
    return ch;
  }

  _skipWhitespace() {
    while (this.pos < this.source.length && " \t\r".includes(this.source[this.pos])) {
      this._advance();
    }
  }

  _skipComment() {
    if (this.pos + 1 < this.source.length &&
        this.source[this.pos] === "/" && this.source[this.pos + 1] === "/") {
      while (this.pos < this.source.length && this.source[this.pos] !== "\n") {
        this._advance();
      }
    }
  }

  _readString() {
    const line = this.line, col = this.col;
    this._advance(); // skip "
    const buf = [];
    while (this.pos < this.source.length) {
      const ch = this.source[this.pos];
      if (ch === '"') { this._advance(); return new Token(T.STRING, buf.join(""), line, col); }
      if (ch === "\\") {
        this._advance();
        const esc = this._advance();
        const escMap = { n: "\n", t: "\t", "\\": "\\", '"': '"' };
        buf.push(escMap[esc] !== undefined ? escMap[esc] : esc);
      } else {
        buf.push(ch);
        this._advance();
      }
    }
    throw new LexerError("Unterminated string", line, col);
  }

  _readNumber() {
    const line = this.line, col = this.col;
    const buf = [];
    if (this._peek() === "-") buf.push(this._advance());
    while (this.pos < this.source.length && /\d/.test(this.source[this.pos])) {
      buf.push(this._advance());
    }
    if (this.pos < this.source.length && this.source[this.pos] === ".") {
      buf.push(this._advance());
      while (this.pos < this.source.length && /\d/.test(this.source[this.pos])) {
        buf.push(this._advance());
      }
    }
    return new Token(T.NUMBER, buf.join(""), line, col);
  }

  _readIdentifier() {
    const line = this.line, col = this.col;
    const buf = [];
    while (this.pos < this.source.length && /[\w]/.test(this.source[this.pos])) {
      buf.push(this._advance());
    }
    const word = buf.join("");
    const type = KEYWORDS[word] || T.IDENTIFIER;
    return new Token(type, word, line, col);
  }

  tokenize() {
    this.tokens = [];
    const simple = {
      "(": T.LPAREN, ")": T.RPAREN,
      "{": T.LBRACE, "}": T.RBRACE,
      "[": T.LBRACKET, "]": T.RBRACKET,
      ",": T.COMMA, ":": T.COLON, ";": T.SEMICOLON, "=": T.EQUALS,
      "#": T.HASH,
    };

    while (this.pos < this.source.length) {
      this._skipWhitespace();
      this._skipComment();
      if (this.pos >= this.source.length) break;

      const ch = this.source[this.pos];
      const line = this.line, col = this.col;

      if (ch === "\n") {
        this._advance();
        this.tokens.push(new Token(T.NEWLINE, "\\n", line, col));
        continue;
      }
      if (simple[ch]) {
        this._advance();
        this.tokens.push(new Token(simple[ch], ch, line, col));
        continue;
      }
      if (ch === '"') { this.tokens.push(this._readString()); continue; }
      if (/\d/.test(ch) || (ch === "-" && this.pos + 1 < this.source.length && /\d/.test(this.source[this.pos + 1]))) {
        this.tokens.push(this._readNumber());
        continue;
      }
      if (/[a-zA-Z_]/.test(ch)) { this.tokens.push(this._readIdentifier()); continue; }

      throw new LexerError(`Unexpected character: '${ch}'`, line, col);
    }

    this.tokens.push(new Token(T.EOF, "", this.line, this.col));
    return this.tokens;
  }
}

// ════════════════════════════════════════════════════════
//  AST NODES
// ════════════════════════════════════════════════════════

class StringVal  { constructor(value) { this.type = "StringVal"; this.value = value; } }
class NumberVal  { constructor(value) { this.type = "NumberVal"; this.value = value; } }
class BoolVal    { constructor(value) { this.type = "BoolVal"; this.value = value; } }
class NullVal    { constructor()      { this.type = "NullVal"; this.value = null; } }
class MapVal     { constructor(entries) { this.type = "MapVal"; this.entries = entries; } }
class ListVal    { constructor(items)   { this.type = "ListVal"; this.items = items; } }
class NamedArg   { constructor(name, value) { this.type = "NamedArg"; this.name = name; this.value = value; } }
class Predicate  { constructor(name, args) { this.type = "Predicate"; this.name = name; this.args = args || []; } }
class Header     { constructor(key, value) { this.type = "Header"; this.key = key; this.value = value; } }

class IntentStmt { constructor(predicate) { this.type = "IntentStmt"; this.predicate = predicate; } }
class FactStmt   { constructor(predicate) { this.type = "FactStmt"; this.predicate = predicate; } }
class QueryStmt  { constructor(predicate, fromAgent) { this.type = "QueryStmt"; this.predicate = predicate; this.fromAgent = fromAgent; } }
class OfferStmt  { constructor(offerId, toAgent, fields) { this.type = "OfferStmt"; this.offerId = offerId; this.toAgent = toAgent; this.fields = fields; } }
class OfferField { constructor(key, value) { this.type = "OfferField"; this.key = key; this.value = value; } }
class AcceptStmt { constructor(offerId) { this.type = "AcceptStmt"; this.offerId = offerId; } }
class RejectStmt { constructor(offerId, reason) { this.type = "RejectStmt"; this.offerId = offerId; this.reason = reason || null; } }
class CommitStmt { constructor(predicate, deadline) { this.type = "CommitStmt"; this.predicate = predicate; this.deadline = deadline || null; } }
class ActStmt    { constructor(predicate) { this.type = "ActStmt"; this.predicate = predicate; } }
class Program    { constructor(headers, statements) { this.type = "Program"; this.headers = headers || []; this.statements = statements || []; } }

// ════════════════════════════════════════════════════════
//  PARSER
// ════════════════════════════════════════════════════════

class ParseError extends Error {
  constructor(msg, token) {
    super(`[Line ${token.line}, Col ${token.col}] ${msg}`);
    this.token = token;
  }
}

class Parser {
  constructor(tokens) {
    this.tokens = tokens.filter(t => t.type !== T.NEWLINE);
    this.pos = 0;
  }

  _current() { return this.tokens[this.pos]; }
  _peekType() { return this.tokens[this.pos].type; }
  _at(...types) { return types.includes(this._peekType()); }

  _expect(type, msg) {
    const tok = this._current();
    if (tok.type !== type) throw new ParseError(msg || `Expected ${type}, got ${tok.type}`, tok);
    this.pos++;
    return tok;
  }

  _match(...types) {
    if (types.includes(this._peekType())) {
      const tok = this._current();
      this.pos++;
      return tok;
    }
    return null;
  }

  parse() {
    const headers = this._parseHeaders();
    const statements = [];
    while (!this._at(T.EOF)) statements.push(this._parseStatement());
    return new Program(headers, statements);
  }

  _parseHeaders() {
    const headers = [];
    while (this._at(T.HASH)) {
      this._expect(T.HASH);
      const key = this._expect(T.IDENTIFIER, "Expected header key after #");
      const val = this._expect(T.STRING, "Expected string value for header");
      headers.push(new Header(key.value, val.value));
    }
    return headers;
  }

  _parseStatement() {
    const dispatch = {
      [T.INTENT]: () => this._parseIntent(),
      [T.FACT]:   () => this._parseFact(),
      [T.QUERY]:  () => this._parseQuery(),
      [T.OFFER]:  () => this._parseOffer(),
      [T.ACCEPT]: () => this._parseAccept(),
      [T.REJECT]: () => this._parseReject(),
      [T.COMMIT]: () => this._parseCommit(),
      [T.ACT]:    () => this._parseAct(),
    };
    const fn = dispatch[this._peekType()];
    if (!fn) throw new ParseError(`Unexpected token: '${this._current().value}'`, this._current());
    return fn();
  }

  _parseIntent() {
    this._expect(T.INTENT);
    const pred = this._parsePredicate();
    this._expect(T.SEMICOLON, "Expected ';' after INTENT");
    return new IntentStmt(pred);
  }

  _parseFact() {
    this._expect(T.FACT);
    const pred = this._parsePredicate();
    this._expect(T.SEMICOLON, "Expected ';' after FACT");
    return new FactStmt(pred);
  }

  _parseQuery() {
    this._expect(T.QUERY);
    const pred = this._parsePredicate();
    this._expect(T.FROM, "Expected 'FROM' in QUERY");
    const agent = this._expect(T.STRING, "Expected agent string after FROM");
    this._expect(T.SEMICOLON, "Expected ';' after QUERY");
    return new QueryStmt(pred, agent.value);
  }

  _parseOffer() {
    this._expect(T.OFFER);
    this._expect(T.ID, "Expected 'id' in OFFER");
    this._expect(T.EQUALS, "Expected '=' after 'id'");
    const offerId = this._expect(T.STRING, "Expected offer id string");
    this._expect(T.TO, "Expected 'TO' in OFFER");
    const toAgent = this._expect(T.STRING, "Expected agent string after TO");
    this._expect(T.LBRACE, "Expected '{' to open OFFER body");
    const fields = this._parseOfferFields();
    this._expect(T.RBRACE, "Expected '}' to close OFFER body");
    this._expect(T.SEMICOLON, "Expected ';' after OFFER");
    return new OfferStmt(offerId.value, toAgent.value, fields);
  }

  _parseOfferFields() {
    const fields = [];
    while (!this._at(T.RBRACE)) {
      const key = this._expect(T.IDENTIFIER, "Expected field name in OFFER body");
      this._expect(T.COLON, "Expected ':' after field name");
      const val = this._parseValue();
      fields.push(new OfferField(key.value, val));
      this._match(T.COMMA);
    }
    return fields;
  }

  _parseAccept() {
    this._expect(T.ACCEPT);
    const offerId = this._expect(T.STRING, "Expected offer id string");
    this._expect(T.SEMICOLON, "Expected ';' after ACCEPT");
    return new AcceptStmt(offerId.value);
  }

  _parseReject() {
    this._expect(T.REJECT);
    const offerId = this._expect(T.STRING, "Expected offer id string");
    let reason = null;
    if (this._match(T.REASON)) {
      reason = this._expect(T.STRING, "Expected reason string").value;
    }
    this._expect(T.SEMICOLON, "Expected ';' after REJECT");
    return new RejectStmt(offerId.value, reason);
  }

  _parseCommit() {
    this._expect(T.COMMIT);
    const pred = this._parsePredicate();
    let deadline = null;
    if (this._match(T.BY)) {
      deadline = this._expect(T.STRING, "Expected deadline string after BY").value;
    }
    this._expect(T.SEMICOLON, "Expected ';' after COMMIT");
    return new CommitStmt(pred, deadline);
  }

  _parseAct() {
    this._expect(T.ACT);
    const pred = this._parsePredicate();
    this._expect(T.SEMICOLON, "Expected ';' after ACT");
    return new ActStmt(pred);
  }

  _parsePredicate() {
    const name = this._expect(T.IDENTIFIER, "Expected predicate name");
    this._expect(T.LPAREN, "Expected '(' after predicate name");
    const args = [];
    while (!this._at(T.RPAREN)) {
      const argName = this._expect(T.IDENTIFIER, "Expected argument name");
      this._expect(T.EQUALS, "Expected '=' after argument name");
      const argVal = this._parseValue();
      args.push(new NamedArg(argName.value, argVal));
      this._match(T.COMMA);
    }
    this._expect(T.RPAREN, "Expected ')' to close predicate");
    return new Predicate(name.value, args);
  }

  _parseValue() {
    const tok = this._current();
    if (tok.type === T.STRING) { this.pos++; return new StringVal(tok.value); }
    if (tok.type === T.NUMBER) { this.pos++; return new NumberVal(parseFloat(tok.value)); }
    if (tok.type === T.TRUE)   { this.pos++; return new BoolVal(true); }
    if (tok.type === T.FALSE)  { this.pos++; return new BoolVal(false); }
    if (tok.type === T.NULL)   { this.pos++; return new NullVal(); }
    if (tok.type === T.LBRACE) return this._parseMap();
    if (tok.type === T.LBRACKET) return this._parseList();
    throw new ParseError(`Expected a value, got ${tok.type}`, tok);
  }

  _parseMap() {
    this._expect(T.LBRACE);
    const entries = {};
    while (!this._at(T.RBRACE)) {
      const key = this._expect(T.IDENTIFIER, "Expected map key");
      this._expect(T.COLON, "Expected ':' in map entry");
      entries[key.value] = this._parseValue();
      this._match(T.COMMA);
    }
    this._expect(T.RBRACE);
    return new MapVal(entries);
  }

  _parseList() {
    this._expect(T.LBRACKET);
    const items = [];
    while (!this._at(T.RBRACKET)) {
      items.push(this._parseValue());
      this._match(T.COMMA);
    }
    this._expect(T.RBRACKET);
    return new ListVal(items);
  }
}

// ════════════════════════════════════════════════════════
//  AGENT
// ════════════════════════════════════════════════════════

class Agent {
  constructor(agentId) {
    this.agentId = agentId;
    this.beliefBase = [];     // Pramana
    this.goalSet = [];        // Sankalpa
    this.offerLedger = {};    // Samvida
    this.commitLedger = [];   // Dharma
    this.actionQueue = [];    // Kriya
    this.messageLog = [];
  }

  addFact(predicate, args)  { this.beliefBase.push({ predicate, args, ts: Date.now() }); }
  addIntent(predicate, args) { this.goalSet.push({ predicate, args, ts: Date.now() }); }

  addOffer(offerId, fromAgent, toAgent, fields) {
    this.offerLedger[offerId] = {
      offerId, fromAgent, toAgent, fields, status: "open", ts: Date.now(),
    };
  }

  acceptOffer(offerId) {
    const o = this.offerLedger[offerId];
    if (!o || o.status !== "open") return false;
    o.status = "accepted";
    return true;
  }

  rejectOffer(offerId, reason) {
    const o = this.offerLedger[offerId];
    if (!o || o.status !== "open") return false;
    o.status = "rejected";
    o.reason = reason || null;
    return true;
  }

  addCommit(predicate, args, deadline) {
    this.commitLedger.push({ predicate, args, deadline: deadline || null, ts: Date.now() });
  }

  addAction(predicate, args) {
    this.actionQueue.push({ predicate, args, ts: Date.now() });
  }

  queryFacts(predicate, args) {
    return this.beliefBase.filter(f => {
      if (f.predicate !== predicate) return false;
      for (const [k, v] of Object.entries(args)) {
        if (k in f.args && f.args[k] !== v) return false;
      }
      return true;
    });
  }

  stateSummary() {
    const lines = [
      `╔══════ Agent: ${this.agentId} ══════`,
      `║ Beliefs (${this.beliefBase.length}):`,
    ];
    for (const f of this.beliefBase) lines.push(`║   • FACT ${f.predicate}(${fmtArgs(f.args)})`);
    lines.push(`║ Goals (${this.goalSet.length}):`);
    for (const g of this.goalSet) lines.push(`║   • INTENT ${g.predicate}(${fmtArgs(g.args)})`);
    lines.push(`║ Offers (${Object.keys(this.offerLedger).length}):`);
    for (const o of Object.values(this.offerLedger)) lines.push(`║   • OFFER id=${JSON.stringify(o.offerId)} [${o.status}] → ${o.toAgent}`);
    lines.push(`║ Commitments (${this.commitLedger.length}):`);
    for (const c of this.commitLedger) {
      const dl = c.deadline ? ` BY ${c.deadline}` : "";
      lines.push(`║   • COMMIT ${c.predicate}(${fmtArgs(c.args)})${dl}`);
    }
    lines.push(`║ Actions (${this.actionQueue.length}):`);
    for (const a of this.actionQueue) lines.push(`║   • ACT ${a.predicate}(${fmtArgs(a.args)})`);
    lines.push(`║ Log (${this.messageLog.length} entries)`);
    lines.push("╚" + "═".repeat(40));
    return lines.join("\n");
  }
}

function fmtArgs(args) {
  return Object.entries(args).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ");
}

// ════════════════════════════════════════════════════════
//  INTERPRETER
// ════════════════════════════════════════════════════════

class SutraRuntimeError extends Error {}

class Interpreter {
  constructor(agent) {
    this.agent = agent;
    this.responses = [];
  }

  static resolveValue(node) {
    if (node instanceof StringVal) return node.value;
    if (node instanceof NumberVal) return node.value;
    if (node instanceof BoolVal) return node.value;
    if (node instanceof NullVal) return null;
    if (node instanceof MapVal) {
      const obj = {};
      for (const [k, v] of Object.entries(node.entries)) obj[k] = Interpreter.resolveValue(v);
      return obj;
    }
    if (node instanceof ListVal) return node.items.map(i => Interpreter.resolveValue(i));
    throw new SutraRuntimeError(`Cannot resolve value: ${JSON.stringify(node)}`);
  }

  static predArgs(pred) {
    const args = {};
    for (const a of pred.args) args[a.name] = Interpreter.resolveValue(a.value);
    return args;
  }

  execute(program) {
    this.responses = [];
    const meta = {};
    for (const h of program.headers) meta[h.key] = h.value;
    for (const stmt of program.statements) this._execStmt(stmt, meta);
    return this.responses;
  }

  _execStmt(stmt, meta) {
    const handlers = {
      IntentStmt:  () => this._execIntent(stmt),
      FactStmt:    () => this._execFact(stmt),
      QueryStmt:   () => this._execQuery(stmt),
      OfferStmt:   () => this._execOffer(stmt, meta),
      AcceptStmt:  () => this._execAccept(stmt),
      RejectStmt:  () => this._execReject(stmt),
      CommitStmt:  () => this._execCommit(stmt),
      ActStmt:     () => this._execAct(stmt),
    };
    const fn = handlers[stmt.type];
    if (!fn) throw new SutraRuntimeError(`Unknown statement type: ${stmt.type}`);
    fn();
  }

  _execIntent(s) {
    const args = Interpreter.predArgs(s.predicate);
    this.agent.addIntent(s.predicate.name, args);
    this.responses.push(`[INTENT] ${s.predicate.name}(${fmtArgs(args)})`);
  }

  _execFact(s) {
    const args = Interpreter.predArgs(s.predicate);
    this.agent.addFact(s.predicate.name, args);
    this.responses.push(`[FACT] ${s.predicate.name}(${fmtArgs(args)})`);
  }

  _execQuery(s) {
    const args = Interpreter.predArgs(s.predicate);
    const results = this.agent.queryFacts(s.predicate.name, args);
    if (results.length > 0) {
      for (const r of results) {
        this.responses.push(`[QUERY RESULT] FACT ${r.predicate}(${fmtArgs(r.args)})`);
      }
    } else {
      this.responses.push(`[QUERY] No matching facts for ${s.predicate.name}(${fmtArgs(args)})`);
    }
  }

  _execOffer(s, meta) {
    const fields = {};
    for (const f of s.fields) fields[f.key] = Interpreter.resolveValue(f.value);
    const fromAgent = meta.from || this.agent.agentId;
    this.agent.addOffer(s.offerId, fromAgent, s.toAgent, fields);
    this.responses.push(`[OFFER] id=${JSON.stringify(s.offerId)} → ${s.toAgent}`);
  }

  _execAccept(s) {
    const ok = this.agent.acceptOffer(s.offerId);
    this.responses.push(ok
      ? `[ACCEPT] Offer ${JSON.stringify(s.offerId)} accepted`
      : `[ACCEPT FAILED] Offer ${JSON.stringify(s.offerId)} not found or not open`);
  }

  _execReject(s) {
    const ok = this.agent.rejectOffer(s.offerId, s.reason);
    const r = s.reason ? ` — ${s.reason}` : "";
    this.responses.push(ok
      ? `[REJECT] Offer ${JSON.stringify(s.offerId)} rejected${r}`
      : `[REJECT FAILED] Offer ${JSON.stringify(s.offerId)} not found or not open`);
  }

  _execCommit(s) {
    const args = Interpreter.predArgs(s.predicate);
    this.agent.addCommit(s.predicate.name, args, s.deadline);
    const dl = s.deadline ? ` BY ${s.deadline}` : "";
    this.responses.push(`[COMMIT] ${s.predicate.name}(${fmtArgs(args)})${dl}`);
  }

  _execAct(s) {
    const args = Interpreter.predArgs(s.predicate);
    this.agent.addAction(s.predicate.name, args);
    this.responses.push(`[ACT] ${s.predicate.name}(${fmtArgs(args)})`);
  }
}

// ════════════════════════════════════════════════════════
//  SANDBOX — Resource-limited execution
// ════════════════════════════════════════════════════════

const ALL_KW = new Set(["INTENT", "FACT", "QUERY", "OFFER", "ACCEPT", "REJECT", "COMMIT", "ACT"]);

const STMT_KW = {
  IntentStmt: "INTENT", FactStmt: "FACT", QueryStmt: "QUERY", OfferStmt: "OFFER",
  AcceptStmt: "ACCEPT", RejectStmt: "REJECT", CommitStmt: "COMMIT", ActStmt: "ACT",
};

class SutraSandbox {
  constructor(opts = {}) {
    this.agentId = opts.agentId || "sandbox-agent";
    this.maxStatements = opts.maxStatements ?? 100;
    this.maxTimeMs = opts.maxTimeMs ?? 5000;
    this.maxBeliefs = opts.maxBeliefs ?? 500;
    this.maxSource = opts.maxSource ?? 65536;
    this.allowed = opts.allowedKeywords
      ? new Set(opts.allowedKeywords.map(k => k.toUpperCase()))
      : new Set(ALL_KW);
  }

  execute(source) {
    const audit = [];
    const start = performance.now();

    if (new TextEncoder().encode(source).length > this.maxSource) {
      audit.push({ event: "blocked", detail: "Source too large" });
      return { success: false, responses: [], violations: ["Source too large"], audit, elapsed: 0 };
    }

    let program;
    try {
      const tokens = new Lexer(source).tokenize();
      program = new Parser(tokens).parse();
    } catch (e) {
      return { success: false, responses: [], violations: [`Parse error: ${e.message}`], audit, elapsed: 0 };
    }

    if (program.statements.length > this.maxStatements) {
      const msg = `Too many statements: ${program.statements.length} (max ${this.maxStatements})`;
      return { success: false, responses: [], violations: [msg], audit, elapsed: 0 };
    }

    // Filter by capability
    const allowed = [];
    const violations = [];
    for (const stmt of program.statements) {
      const kw = STMT_KW[stmt.type] || "UNKNOWN";
      if (!this.allowed.has(kw)) {
        violations.push(`Keyword '${kw}' not allowed`);
        audit.push({ event: "blocked", detail: `${kw} blocked by capability` });
      } else {
        allowed.push(stmt);
        audit.push({ event: "allowed", detail: `${kw} passed` });
      }
    }

    const agent = new Agent(this.agentId);
    const interp = new Interpreter(agent);
    let responses;
    try {
      responses = interp.execute(new Program(program.headers, allowed));
    } catch (e) {
      return { success: false, responses: [], violations: [`Runtime error: ${e.message}`], audit, elapsed: performance.now() - start };
    }

    const elapsed = performance.now() - start;
    if (elapsed > this.maxTimeMs) violations.push(`Execution too slow: ${elapsed.toFixed(1)}ms`);
    if (agent.beliefBase.length > this.maxBeliefs) violations.push(`Too many beliefs: ${agent.beliefBase.length}`);

    return { success: violations.length === 0, responses, violations, audit, elapsed, agent };
  }
}

// ════════════════════════════════════════════════════════
//  SutraVM — High-level API
// ════════════════════════════════════════════════════════

class SutraVM {
  constructor(agentId = "js-agent") {
    this.agent = new Agent(agentId);
  }

  execute(source) {
    const tokens = new Lexer(source).tokenize();
    const program = new Parser(tokens).parse();
    const interp = new Interpreter(this.agent);
    return interp.execute(program);
  }

  parse(source) {
    const tokens = new Lexer(source).tokenize();
    return new Parser(tokens).parse();
  }

  tokenize(source) {
    return new Lexer(source).tokenize();
  }

  state() { return this.agent.stateSummary(); }
  reset(agentId) { this.agent = new Agent(agentId || this.agent.agentId); }
}

// ════════════════════════════════════════════════════════
//  EXPORTS (UMD)
// ════════════════════════════════════════════════════════

const SUTRA = {
  // Core
  Lexer, Parser, Interpreter, Agent, SutraVM,
  // Sandbox
  SutraSandbox,
  // AST nodes
  StringVal, NumberVal, BoolVal, NullVal, MapVal, ListVal,
  NamedArg, Predicate, Header,
  IntentStmt, FactStmt, QueryStmt, OfferStmt, OfferField,
  AcceptStmt, RejectStmt, CommitStmt, ActStmt, Program,
  // Tokens
  T, Token,
  // Errors
  LexerError, ParseError, SutraRuntimeError,
  // Version
  VERSION: "0.6.0",
};

// UMD export
if (typeof module !== "undefined" && module.exports) {
  module.exports = SUTRA;
} else if (typeof globalThis !== "undefined") {
  globalThis.SUTRA = SUTRA;
}

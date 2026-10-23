"""Semicolons are optional — the semicolon-fragility lesson, enforced."""

import unittest

from sutra_lang.lexer import Lexer
from sutra_lang.parser import Parser


def parse(src: str):
    return Parser(Lexer(src).tokenize()).parse()


class TestOptionalTerminators(unittest.TestCase):

    def test_statements_without_semicolons(self):
        src = (
            'FACT available(item="TV", price=5)\n'
            'FACT committed(id="o1", status="signed")\n'
            'QUERY availability(item="TV") FROM "seller"'
        )
        program = parse(src)
        self.assertEqual(len(program.statements), 3)

    def test_mixed_semicolons_and_line_layouts(self):
        src = 'INTENT buy(item="TV"); ACT transfer(amount=1, to="s")\nFACT ok(x=1);'
        self.assertEqual(len(parse(src).statements), 3)

    def test_single_line_statements_without_terminator(self):
        src = 'OFFER id="o1" TO "s" { give: {money: 5}, want: {item: "TV"} } ACCEPT "o1"'
        program = parse(src)
        self.assertEqual(len(program.statements), 2)

    def test_existing_examples_still_parse(self):
        for path in ("examples/buyer.sutra", "examples/seller.sutra",
                     "examples/finalize.sutra", "examples/knowledge.sutra"):
            with open(path) as f:
                self.assertGreaterEqual(len(parse(f.read()).statements), 1, path)


if __name__ == "__main__":
    unittest.main()

"""CLAUDE.md と AGENTS.md の内容が同一であることのテスト

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name: str) -> str:
    with open(os.path.join(ROOT, name), encoding="utf-8", newline="") as f:
        return f.read().replace("\r\n", "\n")


class AgentDocsTest(unittest.TestCase):
    def test_claude_md_and_agents_md_are_identical(self):
        self.assertEqual(_read("CLAUDE.md"), _read("AGENTS.md"),
                         "CLAUDE.md と AGENTS.md の内容が異なります。同じ内容にそろえてください")


if __name__ == "__main__":
    unittest.main()

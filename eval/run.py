"""Run methods A-E on eval/questions.jsonl and write eval/results/*.csv.

Owner: Mehmet Doruk Artan
Usage: python eval/run.py --method D [--questions eval/questions.jsonl]

Per question record: id, method, status, correct, attempts, model calls,
input/output tokens, latency per stage, prompt version, model id, dataset checksum.
Gold results come from running gold_sql on the same snapshot.
"""

from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--method", choices=["A", "B", "C", "D", "E"], required=True)
    parser.add_argument("--questions", default="eval/questions.jsonl")
    parser.parse_args()
    raise NotImplementedError("eval.run.main")


if __name__ == "__main__":
    raise SystemExit(main())

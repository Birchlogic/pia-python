#!/usr/bin/env python3
"""
RLM Demo — Needle-in-a-Haystack test.

Generates a synthetic context with a hidden magic number embedded in
random text, then uses the RLM to find it. This demonstrates the core
RLM loop: the LLM writes REPL code to chunk and explore the context,
uses llm_query for sub-LLM analysis, and returns via FINAL().

Usage:
    python rlm_demo.py                          # default: anthropic
    python rlm_demo.py --backend openai         # use OpenAI
    python rlm_demo.py --haystack-size 100000   # larger haystack
    python rlm_demo.py --verbose                # colorful logging
"""

import os
import sys
import random
import string
import argparse
import time

# Ensure the project root is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from rlm import RLM


def generate_haystack(size: int = 50000, seed: int = 42) -> tuple[str, int]:
    """
    Generate a haystack of random words with a hidden magic number.

    Returns:
        (haystack_text, magic_number)
    """
    rng = random.Random(seed)
    magic_number = rng.randint(100000, 999999)

    words = []
    chars_generated = 0
    insert_point = rng.randint(size // 3, 2 * size // 3)

    while chars_generated < size:
        if abs(chars_generated - insert_point) < 100 and magic_number not in [
            int(w) for w in words if w.isdigit()
        ]:
            # Insert the needle
            needle = (
                f"\n\n--- IMPORTANT RECORD ---\n"
                f"The magic number for verification is: {magic_number}\n"
                f"This number must be reported exactly as shown.\n"
                f"--- END RECORD ---\n\n"
            )
            words.append(needle)
            chars_generated += len(needle)
        else:
            # Generate random filler text
            word_len = rng.randint(3, 12)
            word = "".join(rng.choices(string.ascii_lowercase, k=word_len))
            words.append(word)
            chars_generated += word_len + 1  # +1 for space

            # Add occasional line breaks for realism
            if rng.random() < 0.05:
                words.append("\n")

    haystack = " ".join(words)
    return haystack, magic_number


def main():
    parser = argparse.ArgumentParser(description="RLM Needle-in-a-Haystack Demo")
    parser.add_argument(
        "--backend", choices=["anthropic", "openai"], default="anthropic",
        help="LLM backend to use (default: anthropic)",
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help="Model name override",
    )
    parser.add_argument(
        "--haystack-size", type=int, default=50000,
        help="Size of the haystack in characters (default: 50000)",
    )
    parser.add_argument(
        "--max-iterations", type=int, default=15,
        help="Max RLM iterations (default: 15)",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable colorful logging output",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducibility",
    )
    args = parser.parse_args()

    # Generate haystack
    print(f"\n🔨 Generating haystack ({args.haystack_size:,} chars, seed={args.seed})...")
    haystack, magic_number = generate_haystack(size=args.haystack_size, seed=args.seed)
    print(f"   Hidden magic number: {magic_number}")
    print(f"   Haystack length: {len(haystack):,} chars")

    # Initialize RLM
    print(f"\n🚀 Initializing RLM (backend={args.backend})...")
    rlm = RLM(
        backend=args.backend,
        model=args.model,
        max_iterations=args.max_iterations,
        verbose=args.verbose,
    )

    # Run completion
    query = (
        "Find the magic number hidden in the text. "
        "The number is embedded somewhere in the context as an 'IMPORTANT RECORD'. "
        "Return ONLY the magic number, nothing else."
    )

    print(f"\n🔍 Query: {query}")
    print(f"{'='*60}")

    start_time = time.time()
    result = rlm.completion(context=haystack, query=query)
    elapsed = time.time() - start_time

    # Results
    print(f"\n{'='*60}")
    print(f"✅ RLM Response: {result.response}")
    print(f"📊 Iterations:   {result.iterations}")
    print(f"⏱️  Time:         {elapsed:.1f}s")

    # Verify
    found = str(magic_number) in result.response
    if found:
        print(f"🎯 CORRECT! Magic number {magic_number} was found.")
    else:
        print(f"❌ INCORRECT. Expected {magic_number}, got: {result.response}")

    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main())

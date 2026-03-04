#!/usr/bin/env python3
"""
RLM Demo on Example Input Folder

Reads all text files in the example_input directory and uses the RLM
engine to extract structured compliance information (Entities, Data Types,
Processes, Risks, Compliance Gaps).
"""

import os
import sys
import time
import argparse

# Ensure the project root is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from rlm import RLM


def main():
    parser = argparse.ArgumentParser(description="RLM on Example Input Data")
    parser.add_argument(
        "--backend", choices=["anthropic", "openai"], default="anthropic",
        help="LLM backend to use (default: anthropic)",
    )
    parser.add_argument(
        "--max-iterations", type=int, default=15,
        help="Max RLM iterations (default: 15)",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable colorful logging output",
    )
    args = parser.parse_args()

    input_dir = os.path.join(os.path.dirname(__file__), "example_input")
    
    if not os.path.exists(input_dir):
        print(f"Error: Directory {input_dir} not found.")
        return 1

    print(f"\n📂 Loading transcripts from {input_dir}...")
    transcripts = []
    
    for filename in sorted(os.listdir(input_dir)):
        if filename.endswith(".txt"):
            filepath = os.path.join(input_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
                # Wrap each file's content nicely
                transcripts.append(f"--- FILE: {filename} ---\n{content}\n")
                print(f"  - Loaded {filename} ({len(content):,} chars)")
                
    if not transcripts:
        print("No .txt files found in example_input.")
        return 1

    total_chars = sum(len(t) for t in transcripts)
    print(f"\nTotal context length: {total_chars:,} characters across {len(transcripts)} files.")

    # Initialize RLM
    print(f"\n🚀 Initializing RLM (backend={args.backend})...")
    rlm = RLM(
        backend=args.backend,
        max_iterations=args.max_iterations,
        verbose=args.verbose,
    )

    # We provide the transcripts as a single long string or a list of strings.
    # Passing as a list of strings allows the RLM to chunk them more easily if it wants.
    context = transcripts 

    query = (
        "You are a professional Compliance Analyst. Analyze all the provided transcripts "
        "You have to check that do we have any transcript file related to \n"
        "Manish communicate to birchlogic team via whatsapp and backups all whatsapp messages on google drive \n"
        ""
    )

    print(f"\n🔍 Query: {query}")
    print(f"{'='*60}")

    start_time = time.time()
    result = rlm.completion(context=context, query=query)
    elapsed = time.time() - start_time

    # Results
    print(f"\n{'='*60}")
    print(f"✅ RLM Final Response:\n\n{result.response}")
    print(f"\n{'='*60}")
    print(f"📊 Iterations:   {result.iterations}")
    print(f"⏱️  Time:         {elapsed:.1f}s")

    return 0


if __name__ == "__main__":
    sys.exit(main())

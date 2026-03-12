from utils.llm_adapter import get_llm_client
"""
RLM-Powered Ingestion Agent

Uses the Recursive Language Model engine to process ALL transcripts
together as context chunks, enabling cross-transcript analysis and
handling arbitrarily long inputs.

Returns the same ExtractedTranscriptData Pydantic model as IngestionAgent,
so it's a drop-in replacement.
"""

import os
import json
import sys
from typing import List

from config import Config
from utils.logger import setup_logger
from models.extracted_data import ExtractedTranscriptData

logger = setup_logger("RLMIngestionAgent")

# JSON schema the RLM must produce (matches ExtractedTranscriptData)
_EXPECTED_SCHEMA = """{
    "entities": [{ "name": "...", "type": "...", "description": "..." }],
    "data_inventory": [{ "data_type": "...", "source": "...", "destination": "...", "protection_level": "..." }],
    "processes": [{ "name": "...", "description": "...", "involved_entities": ["...", "..."] }],
    "risks": [{ "title": "...", "description": "...", "impact": "...", "likelihood": "..." }],
    "compliance_gaps": [{ "requirement": "...", "observation": "...", "gap_description": "..." }]
}"""


class RLMIngestionAgent:
    """
    Ingest ALL transcripts simultaneously using RLM.

    Advantages over per-file IngestionAgent:
    - Cross-references entities/risks across sessions
    - Handles arbitrary number/size of files
    - Deduplicates naturally (one consolidated output)
    """

    def __init__(self, verbose: bool = False, max_iterations: int = 15, ai_config: dict = None):
        self.verbose = verbose
        self.max_iterations = max_iterations
        self.ai_config = ai_config or {}

    def ingest_all(self, file_paths: List[str]) -> ExtractedTranscriptData:
        """
        Process all transcript files together using RLM.

        Args:
            file_paths: List of paths to transcript text files.

        Returns:
            A single consolidated ExtractedTranscriptData object.
        """
        from rlm import RLM

        logger.info(f"RLM ingestion: loading {len(file_paths)} files")

        # Load each file as a separate context chunk
        chunks = []
        for fp in file_paths:
            with open(fp, "r", encoding="utf-8") as f:
                content = f.read()
            basename = os.path.basename(fp)
            chunks.append(f"--- FILE: {basename} ---\n{content}")
            logger.info(f"  Loaded {basename} ({len(content):,} chars)")

        total_chars = sum(len(c) for c in chunks)
        logger.info(f"  Total context: {total_chars:,} chars across {len(chunks)} chunks")

        # Determine backend/api_key/model from ai_config
        backend = "anthropic"
        if self.ai_config.get("type") == "OPENAI":
            backend = "openai"
        elif self.ai_config.get("type") == "OPENROUTER":
            backend = "openrouter"
            
        api_key = self.ai_config.get("apiKey") or Config.ANTHROPIC_API_KEY
        model = self.ai_config.get("model") or Config.CLAUDE_MODEL

        # Initialize RLM engine
        rlm = RLM(
            backend=backend,
            api_key=api_key,
            model=model,
            max_iterations=self.max_iterations,
            verbose=self.verbose,
        )

        # Build a query that asks the RLM to produce the exact JSON schema
        query = f"""You are a professional Compliance Analyst performing an ISO27001/DPDPA assessment.

Analyze ALL the provided transcript files and extract structured information.

You MUST return your final answer as a JSON object matching this EXACT schema:
{_EXPECTED_SCHEMA}

Guidelines:
- entities: Systems, Departments, Third Parties mentioned across ALL transcripts
- data_inventory: All PII, Financial, Recording data types with source, destination, protection_level
- processes: How data is collected, processed, stored, shared — with involved_entities
- risks: Security and privacy risks identified (with impact: High/Medium/Low, likelihood: High/Medium/Low)
- compliance_gaps: Gaps against ISO27001, DPDPA, or other security standards

Cross-reference findings across all transcript sessions. Deduplicate entities and processes.
Be thorough — examine every transcript chunk carefully.

When done, use FINAL_VAR(result_json) where result_json is the JSON string you built."""

        result = rlm.completion(context=chunks, query=query)
        logger.info(f"RLM completed in {result.iterations} iterations")

        # Parse the response into ExtractedTranscriptData
        return self._parse_response(result.response)

    def _parse_response(self, response: str) -> ExtractedTranscriptData:
        """Parse the RLM response into ExtractedTranscriptData."""
        # Try direct JSON parse
        try:
            data = json.loads(response)
            return ExtractedTranscriptData(**data)
        except (json.JSONDecodeError, Exception):
            pass

        # Try to extract JSON from markdown fences
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0].strip()
            try:
                data = json.loads(json_str)
                return ExtractedTranscriptData(**data)
            except (json.JSONDecodeError, Exception):
                pass

        # Try to find first { ... } block
        start = response.find("{")
        end = response.rfind("}")
        if start != -1 and end != -1:
            try:
                data = json.loads(response[start : end + 1])
                return ExtractedTranscriptData(**data)
            except (json.JSONDecodeError, Exception):
                pass

        # Last resort: return empty data with a warning
        logger.warning("Could not parse RLM response as ExtractedTranscriptData JSON")
        logger.debug(f"Raw response (first 500 chars): {response[:500]}")
        return ExtractedTranscriptData()

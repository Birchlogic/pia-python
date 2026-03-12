from utils.llm_adapter import get_llm_client
"""
Flow Canonicalization Agent — Merges fragmented data flows into
canonical DFD-ready flows by mapping people to roles and deduplicating.
"""
import json
import anthropic
from collections import defaultdict
from rapidfuzz import fuzz
from config import Config
from utils.logger import setup_logger

logger = setup_logger("FlowCanonAgent")

SYSTEM_PROMPT = """You are a data flow canonicalization expert. Given raw extracted data flows and normalized entities, produce canonical DFD flows.

Rules:
1. MAP people to their roles. E.g. "Nikhil" and "Farhan" are both "Customer Care Agent".
2. MERGE flows with the same source→destination by combining their data elements.
3. REMOVE duplicate flows.
4. Each flow must have: source, destination, data_elements (list), channel.
5. Use canonical entity names from the normalized entities provided.

Return ONLY valid JSON array of canonical flows:
[
  {
    "source": "Customer",
    "destination": "Customer Care Agent",
    "data_elements": ["PAN", "Loan Account Number", "EMI Amount"],
    "channel": "phone/WhatsApp/system/manual/API/email",
    "evidence": "brief source text reference"
  }
]"""


class FlowCanonicalizerAgent:

    def __init__(self, ai_config: dict = None):
        self.ai_config = ai_config or {}
        self.client = get_llm_client(self.ai_config)
        self.model = self.ai_config.get("model") or Config.CLAUDE_MODEL

    def _build_name_map(self, normalized_entities):
        """Build a mapping from original names to canonical names."""
        name_map = {}
        for entity in normalized_entities.get("actors", []):
            canonical = entity["name"]
            for orig in entity.get("original_names", [canonical]):
                name_map[orig.lower()] = canonical
        for entity in normalized_entities.get("systems", []):
            canonical = entity["name"]
            for orig in entity.get("original_names", [canonical]):
                name_map[orig.lower()] = canonical
        return name_map

    def _resolve_name(self, name, name_map):
        """Resolve a name to its canonical form using the name map."""
        lower = name.lower().strip()
        if lower in name_map:
            return name_map[lower]
        # Try fuzzy match
        best_score, best_match = 0, name
        for key, canonical in name_map.items():
            score = fuzz.ratio(lower, key)
            if score > best_score and score >= 80:
                best_score = score
                best_match = canonical
        return best_match

    def _deterministic_merge(self, flows, name_map):
        """Rule-based flow merging: resolve names + group + combine data."""
        grouped = defaultdict(lambda: {"data_elements": set(), "channels": set(), "evidence": []})

        for flow in flows:
            source = self._resolve_name(flow.get("source", ""), name_map)
            dest = self._resolve_name(flow.get("destination", ""), name_map)
            key = (source, dest)

            data = flow.get("data", flow.get("data_elements", ""))
            if isinstance(data, list):
                for d in data:
                    grouped[key]["data_elements"].add(d)
            elif isinstance(data, str) and data:
                grouped[key]["data_elements"].add(data)

            channel = flow.get("channel", "unspecified")
            grouped[key]["channels"].add(channel)

            evidence = flow.get("evidence", "")
            if evidence:
                grouped[key]["evidence"].append(evidence)

        merged = []
        for (source, dest), info in grouped.items():
            if source == dest:
                continue  # Skip self-loops
            merged.append({
                "source": source,
                "destination": dest,
                "data_elements": sorted(info["data_elements"]),
                "channel": ", ".join(sorted(info["channels"])),
                "evidence": "; ".join(info["evidence"][:3])  # Keep top 3
            })

        return merged

    def canonicalize(self, data_flows, normalized_entities, data_elements=None):
        """
        Canonicalize flows: map people to roles, merge, deduplicate.

        Args:
            data_flows: list of raw flow dicts
            normalized_entities: output from EntityNormalizationAgent
            data_elements: list of known data element names

        Returns:
            list of canonical flow dicts
        """
        name_map = self._build_name_map(normalized_entities)

        # ── Step 1: Deterministic merge ──────────────
        merged = self._deterministic_merge(data_flows, name_map)
        logger.info(f"Deterministic merge: {len(data_flows)} raw → {len(merged)} merged flows")

        # ── Step 2: LLM refinement ───────────────────
        try:
            context = json.dumps({
                "merged_flows": merged,
                "canonical_actors": [a["name"] for a in normalized_entities.get("actors", [])],
                "canonical_systems": [s["name"] for s in normalized_entities.get("systems", [])],
                "known_data_elements": data_elements or []
            }, indent=2)

            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                temperature=0,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": context}]
            )
            content = response.content[0].text.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                content = content.rsplit("```", 1)[0]
            canonical_flows = json.loads(content)
            logger.info(f"LLM refined: {len(canonical_flows)} canonical flows")
            return canonical_flows

        except Exception as e:
            logger.error(f"FlowCanonAgent LLM failed: {e}, using deterministic merge")
            return merged

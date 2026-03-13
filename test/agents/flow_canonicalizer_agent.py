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
4. Use canonical entity names from the normalized entities provided.
5. PRESERVE all evidence provenance — timestamps, speakers, and source files must carry through.

For each canonical flow you MUST return a JSON object with EXACTLY these fields:

```json
{
  "source": "string — canonical source entity name",
  "destination": "string — canonical destination entity name",
  "data_elements": ["array of specific data items"],
  "channel": "string — phone/WhatsApp/system/manual/API/email",
  "evidence": "string — combined evidence text",
  "evidence_trail": [
    {
      "evidence": "string — exact quote",
      "timestamp": "string — from transcript",
      "speaker": "string — who said it",
      "speaker_role": "string — their role",
      "source_file": "string — filename"
    }
  ]
}
```

Return ONLY a valid JSON array. No markdown fences, no explanation text."""


class FlowCanonicalizerAgent:

    def __init__(self, ai_config: dict = None):
        self.ai_config = ai_config or {}
        self.client = get_llm_client(self.ai_config)
        self.model = self.ai_config.get("model") or "claude-3-5-sonnet-20241022"

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
        """Rule-based flow merging: resolve names + group + combine data + preserve evidence trail."""
        grouped = defaultdict(lambda: {
            "data_elements": set(), "channels": set(),
            "evidence": [], "evidence_trail": []
        })

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
            if evidence and len(grouped[key]["evidence"]) < 5:
                grouped[key]["evidence"].append(evidence)

            # Preserve structured evidence trail
            if len(grouped[key]["evidence_trail"]) < 10:
                trail_entry = {
                    "evidence": evidence,
                    "timestamp": flow.get("evidence_timestamp", ""),
                    "speaker": flow.get("evidence_speaker", ""),
                    "speaker_role": flow.get("evidence_speaker_role", ""),
                    "source_file": flow.get("source_file", "")
                }
                # Also check for nested evidence_trail from earlier merges
                existing_trail = flow.get("evidence_trail", [])
                if existing_trail:
                    for et in existing_trail:
                        if len(grouped[key]["evidence_trail"]) < 10:
                            grouped[key]["evidence_trail"].append(et)
                elif trail_entry["evidence"]:
                    grouped[key]["evidence_trail"].append(trail_entry)

        merged = []
        for (source, dest), info in grouped.items():
            if source == dest:
                continue  # Skip self-loops
            merged.append({
                "source": source,
                "destination": dest,
                "data_elements": sorted(info["data_elements"]),
                "channel": ", ".join(sorted(info["channels"])),
                "evidence": "; ".join(info["evidence"][:3]),
                "evidence_trail": info["evidence_trail"]
            })

        return merged

    def canonicalize(self, data_flows, normalized_entities, data_elements=None):
        """
        Canonicalize flows: map people to roles, merge, deduplicate.
        Preserves evidence_trail through all steps.

        Args:
            data_flows: list of raw flow dicts
            normalized_entities: output from EntityNormalizationAgent
            data_elements: list of known data element names

        Returns:
            list of canonical flow dicts with evidence_trail
        """
        name_map = self._build_name_map(normalized_entities)

        # ── Step 1: Deterministic merge ──────────────
        merged = self._deterministic_merge(data_flows, name_map)
        logger.info(f"Deterministic merge: {len(data_flows)} raw → {len(merged)} merged flows")

        # Build a lookup of evidence_trail by (source, dest) for re-attachment after LLM
        trail_lookup = {}
        for m in merged:
            key = (m["source"].lower(), m["destination"].lower())
            trail_lookup[key] = m.get("evidence_trail", [])

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

            # Re-attach evidence_trail if LLM dropped it
            for flow in canonical_flows:
                if not flow.get("evidence_trail"):
                    key = (flow.get("source", "").lower(), flow.get("destination", "").lower())
                    flow["evidence_trail"] = trail_lookup.get(key, [])

            logger.info(f"LLM refined: {len(canonical_flows)} canonical flows")
            return canonical_flows

        except Exception as e:
            logger.error(f"FlowCanonAgent LLM failed: {e}, using deterministic merge")
            return merged

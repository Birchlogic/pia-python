"""
Flow Merger — Merges fragmented data flows across multiple documents
into a unified set of canonical flows with combined data elements.
"""
from collections import defaultdict
from rapidfuzz import fuzz
from utils.logger import setup_logger

logger = setup_logger("FlowMerger")


class FlowMerger:

    def __init__(self, name_map=None):
        self.name_map = name_map or {}

    def _resolve(self, name):
        """Resolve a name to its canonical form."""
        lower = name.lower().strip()
        if lower in self.name_map:
            return self.name_map[lower]
        # Fuzzy fallback
        best_score, best = 0, name
        for key, canonical in self.name_map.items():
            score = fuzz.ratio(lower, key)
            if score > best_score and score >= 80:
                best_score = score
                best = canonical
        return best

    def merge(self, doc_outputs):
        """
        Merge flows from multiple document outputs.

        Args:
            doc_outputs: list of dicts, each with 'flows' or 'data_flows' and 'metadata'

        Returns:
            list of merged canonical flow dicts
        """
        grouped = defaultdict(lambda: {
            "data_elements": set(),
            "channels": set(),
            "evidence": [],
            "sources": set(),
            "count": 0
        })

        for doc in doc_outputs:
            source_file = doc.get("metadata", {}).get("source_file", "unknown")
            flows = doc.get("flows", doc.get("data_flows", []))

            for flow in flows:
                src = self._resolve(flow.get("source", ""))
                dst = self._resolve(flow.get("destination", flow.get("target", "")))

                if not src or not dst or src == dst:
                    continue

                key = (src, dst)

                # Collect data elements
                data = flow.get("data_elements", flow.get("data", []))
                if isinstance(data, str):
                    data = [data] if data else []
                for d in data:
                    grouped[key]["data_elements"].add(d)

                # Collect channels
                channel = flow.get("channel", "")
                if channel:
                    grouped[key]["channels"].add(channel)

                # Collect evidence
                evidence = flow.get("evidence", "")
                if evidence and len(grouped[key]["evidence"]) < 5:
                    grouped[key]["evidence"].append(evidence)

                grouped[key]["sources"].add(source_file)
                grouped[key]["count"] += 1

        # Build merged flows
        merged = []
        for (src, dst), info in grouped.items():
            merged.append({
                "source": src,
                "target": dst,
                "data_elements": sorted(info["data_elements"]),
                "channel": ", ".join(sorted(info["channels"])) or "unspecified",
                "inferred": False,
                "sources": sorted(info["sources"]),
                "evidence": info["evidence"],
                "mention_count": info["count"]
            })

        # Sort by mention count (most mentioned first)
        merged.sort(key=lambda f: f["mention_count"], reverse=True)

        logger.info(f"Merged flows → {len(merged)} canonical flows")
        return merged

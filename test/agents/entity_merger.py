"""
Entity Merger — Merges duplicate entities across multiple document outputs
using fuzzy matching and alias tracking.
"""
import re
from rapidfuzz import fuzz
from utils.logger import setup_logger

logger = setup_logger("EntityMerger")

# Canonical name overrides
CANONICAL_NAMES = {
    "sfdc": "Salesforce",
    "salesforce crm": "Salesforce",
    "ms excel": "Excel",
    "microsoft excel": "Excel",
    "ms teams": "Microsoft Teams",
    "onedrive for business": "OneDrive",
    "google sheets": "Google Sheets",
    "wa": "WhatsApp",
    "whatsapp business": "WhatsApp",
}

# Type classification rules
SYSTEM_KEYWORDS = {
    "salesforce", "ameyo", "whatsapp", "excel", "onedrive", "outlook",
    "sharepoint", "teams", "jira", "zendesk", "sap", "oracle", "zoho",
    "freshdesk", "hubspot", "slack", "google drive", "intercom", "servicenow"
}

DATA_STORE_KEYWORDS = {"excel", "onedrive", "sharepoint", "google drive", "s3", "database"}

EXTERNAL_KEYWORDS = {"customer", "client", "vendor", "partner", "regulator", "dsa", "borrower", "applicant"}

PROCESS_KEYWORDS = {"processing", "calling", "escalation", "closure", "verification", "onboarding", "audit"}


def _slugify(name):
    """Create a normalized ID from a name."""
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def _classify_type(name):
    """Classify an entity into a node type."""
    lower = name.lower()
    for kw in SYSTEM_KEYWORDS:
        if kw in lower:
            if any(ds in lower for ds in DATA_STORE_KEYWORDS):
                return "data_store"
            return "system"
    for kw in EXTERNAL_KEYWORDS:
        if kw in lower:
            return "external_entity"
    for kw in PROCESS_KEYWORDS:
        if kw in lower:
            return "process"
    return "actor"


class EntityMerger:

    def __init__(self, threshold=80):
        self.threshold = threshold

    def _find_canonical(self, name):
        """Look up a canonical name override."""
        lower = name.lower().strip()
        if lower in CANONICAL_NAMES:
            return CANONICAL_NAMES[lower]
        return name.strip()

    def merge(self, doc_outputs):
        """
        Merge entities from multiple document outputs into a unified entity registry.

        Args:
            doc_outputs: list of dicts, each with 'actors', 'systems', 'data_elements',
                         'metadata' (with 'source_file')

        Returns:
            dict with 'entities' (list of merged entity dicts) and 'name_map' (original→canonical)
        """
        # Collect all raw entities with source tracking
        raw_entities = []

        for doc in doc_outputs:
            source = doc.get("metadata", {}).get("source_file", "unknown")

            for actor in doc.get("actors", []):
                name = actor["name"] if isinstance(actor, dict) else str(actor)
                etype = actor.get("type", "actor") if isinstance(actor, dict) else "actor"
                raw_entities.append({"name": name, "type": etype, "source": source})

            for sys in doc.get("systems", []):
                name = sys["name"] if isinstance(sys, dict) else str(sys)
                raw_entities.append({"name": name, "type": "system", "source": source})

        # Apply canonical name overrides
        for e in raw_entities:
            e["name"] = self._find_canonical(e["name"])

        # Fuzzy-group entities
        merged = []
        used = set()
        name_map = {}

        for i, ent in enumerate(raw_entities):
            if i in used:
                continue

            group = [ent]
            used.add(i)

            for j, other in enumerate(raw_entities):
                if j in used:
                    continue
                score = fuzz.ratio(ent["name"].lower(), other["name"].lower())
                partial = fuzz.partial_ratio(ent["name"].lower(), other["name"].lower())
                if score >= self.threshold or partial >= 92:
                    group.append(other)
                    used.add(j)

            # Pick canonical name (longest)
            canonical = max(group, key=lambda g: len(g["name"]))["name"]
            aliases = list(set(g["name"] for g in group if g["name"] != canonical))
            sources = list(set(g["source"] for g in group))
            entity_type = _classify_type(canonical)

            # Map all original names to canonical
            for g in group:
                name_map[g["name"].lower()] = canonical

            merged.append({
                "id": _slugify(canonical),
                "name": canonical,
                "type": entity_type,
                "aliases": aliases,
                "sources": sources
            })

        # Deduplicate by id
        seen_ids = set()
        unique = []
        for m in merged:
            if m["id"] not in seen_ids:
                seen_ids.add(m["id"])
                unique.append(m)
            else:
                # Merge aliases into existing
                existing = next(u for u in unique if u["id"] == m["id"])
                existing["aliases"] = list(set(existing["aliases"] + m["aliases"]))
                existing["sources"] = list(set(existing["sources"] + m["sources"]))

        logger.info(f"Merged {len(raw_entities)} raw entities → {len(unique)} unique")
        return {"entities": unique, "name_map": name_map}

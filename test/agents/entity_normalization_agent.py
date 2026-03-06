"""
Entity Normalization Agent — Deduplicates, classifies, and cleans
all extracted entities using fuzzy matching + Claude reasoning.
"""
import json
import anthropic
from rapidfuzz import fuzz
from config import Config
from utils.logger import setup_logger

logger = setup_logger("EntityNormAgent")

# ── Rule-based classification seeds ────────────────────
KNOWN_SYSTEMS = {
    "salesforce", "ameyo", "whatsapp", "excel", "onedrive",
    "microsoft 365", "outlook", "sharepoint", "teams",
    "google drive", "slack", "jira", "zendesk", "hubspot",
    "sap", "oracle", "zoho", "freshdesk", "intercom"
}

KNOWN_ROLES = {
    "agent", "team lead", "manager", "supervisor", "analyst",
    "officer", "head", "director", "executive", "coordinator",
    "auditor", "consultant"
}

KNOWN_EXTERNAL = {
    "customer", "client", "vendor", "partner", "regulator",
    "government", "third party", "borrower", "applicant"
}

PROCESS_INDICATORS = {
    "process", "handling", "management", "verification",
    "closure", "escalation", "resolution", "onboarding",
    "collection", "disbursement", "audit", "review"
}

SYSTEM_PROMPT = """You are an expert entity normalization specialist. Given raw extracted entities from a privacy assessment pipeline, clean and normalize them.

You will receive:
- actors: list of extracted actor names (may contain duplicates, misclassifications)
- systems: list of extracted system names
- data_elements: list of extracted data elements

Your job:
1. DEDUPLICATE: Merge "Nikhil" and "Nikhil Joshi" into "Nikhil Joshi"
2. CLASSIFY: Each entity must be one of: PERSON, TEAM, SYSTEM, EXTERNAL_ENTITY, DATA_STORE, PROCESS
3. REMOVE INVALID: Remove things that are categories/processes misclassified as actors (e.g. "Loan Closure", "Customer Issues")
4. CANONICALIZE: Use proper role names — "Customer Care Agent" instead of just "Agent"

Return ONLY valid JSON:
{
  "actors": [{"name": "...", "type": "PERSON|TEAM|EXTERNAL_ENTITY", "original_names": ["..."]}],
  "systems": [{"name": "...", "type": "SYSTEM|DATA_STORE", "original_names": ["..."]}],
  "removed": [{"name": "...", "reason": "..."}]
}"""


class EntityNormalizationAgent:

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        self.model = Config.CLAUDE_MODEL

    def _fuzzy_group(self, names, threshold=75):
        """Group names by fuzzy similarity."""
        groups = []
        used = set()
        for i, name in enumerate(names):
            if i in used:
                continue
            group = [name]
            used.add(i)
            for j, other in enumerate(names):
                if j in used:
                    continue
                # Fuzzy match
                score = fuzz.ratio(name.lower(), other.lower())
                partial = fuzz.partial_ratio(name.lower(), other.lower())
                if score >= threshold or partial >= 90:
                    group.append(other)
                    used.add(j)
            groups.append(group)
        return groups

    def _rule_classify(self, name):
        """Rule-based entity classification."""
        lower = name.lower().strip()

        # Check known systems
        for sys in KNOWN_SYSTEMS:
            if sys in lower:
                return "SYSTEM"

        # Check known external entities
        for ext in KNOWN_EXTERNAL:
            if ext in lower:
                return "EXTERNAL_ENTITY"

        # Check if it's a role/team
        for role in KNOWN_ROLES:
            if role in lower:
                return "TEAM"

        # Check if it's actually a process
        for proc in PROCESS_INDICATORS:
            if proc in lower:
                return "PROCESS"

        return None  # Unknown — let LLM decide

    def _pick_canonical(self, group):
        """Pick the most complete name from a group."""
        return max(group, key=lambda n: len(n))

    def normalize(self, actors, systems, data_elements, data_flows=None):
        """
        Normalize entities: deduplicate, classify, clean.

        Returns normalized dict with cleaned actors, systems, removed entities.
        """
        # ── Step 1: Rule-based pre-filtering ──────────
        pre_actors = []
        pre_systems = list(systems)
        removed = []

        for actor in actors:
            classification = self._rule_classify(actor)
            if classification == "SYSTEM":
                pre_systems.append(actor)
                removed.append({"name": actor, "reason": "Reclassified as SYSTEM"})
            elif classification == "PROCESS":
                removed.append({"name": actor, "reason": "Is a process/category, not an actor"})
            else:
                pre_actors.append(actor)

        # ── Step 2: Fuzzy deduplication ───────────────
        actor_groups = self._fuzzy_group(pre_actors)
        deduped_actors = [self._pick_canonical(g) for g in actor_groups]

        system_groups = self._fuzzy_group(pre_systems)
        deduped_systems = [self._pick_canonical(g) for g in system_groups]

        logger.info(
            f"Rule-based: {len(actors)} actors → {len(deduped_actors)}, "
            f"{len(systems)} systems → {len(deduped_systems)}, "
            f"{len(removed)} removed"
        )

        # ── Step 3: LLM refinement ───────────────────
        try:
            context = json.dumps({
                "actors": deduped_actors,
                "systems": deduped_systems,
                "data_elements": data_elements,
            }, indent=2)

            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                temperature=0,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": context}]
            )
            content = response.content[0].text.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                content = content.rsplit("```", 1)[0]
            result = json.loads(content)

            # Merge removed lists
            llm_removed = result.get("removed", [])
            result["removed"] = removed + llm_removed

            logger.info(
                f"LLM normalized: {len(result.get('actors', []))} actors, "
                f"{len(result.get('systems', []))} systems, "
                f"{len(result.get('removed', []))} removed"
            )
            return result

        except Exception as e:
            logger.error(f"EntityNormAgent LLM failed: {e}")
            # Fallback to rule-based results
            return {
                "actors": [{"name": a, "type": self._rule_classify(a) or "PERSON", "original_names": [a]} for a in deduped_actors],
                "systems": [{"name": s, "type": "SYSTEM", "original_names": [s]} for s in deduped_systems],
                "removed": removed
            }

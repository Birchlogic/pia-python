"""
Pipeline Verification Agent — Verifies pipeline output against source text,
computes accuracy scores, detects hallucinations, and triggers reprocessing.
"""
import re
import json
import anthropic
from rapidfuzz import fuzz
from config import Config
from utils.logger import setup_logger

logger = setup_logger("VerificationAgent")

# ── Ground-truth extraction patterns ──────────────────

SYSTEM_PATTERNS = [
    "Salesforce", "Ameyo", "WhatsApp", "Excel", "OneDrive",
    "Microsoft 365", "Outlook", "SharePoint", "Teams",
    "Google Drive", "Slack", "Jira", "Zendesk", "SAP",
    "Oracle", "Zoho", "Freshdesk", "HubSpot", "ServiceNow"
]

DATA_ELEMENT_PATTERNS = [
    "PAN", "Aadhaar", "Mobile Number", "Email Address",
    "Loan Account Number", "Customer Name", "Residential Address",
    "Property Address", "Payment History", "EMI Amount",
    "Interest Rate", "Credit Score", "Bank Account",
    "Date of Birth", "Income", "Salary", "KYC"
]

RISK_KEYWORDS = [
    r"unmasked", r"visible to", r"no retention", r"no audit",
    r"personal phone", r"not encrypted", r"no field-level security",
    r"cross-border", r"bulk export", r"CSV download"
]


class PipelineVerificationAgent:

    def __init__(self, reprocess_threshold=0.85):
        self.client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        self.model = Config.CLAUDE_MODEL
        self.reprocess_threshold = reprocess_threshold

    def _extract_ground_truth_systems(self, text):
        """Extract systems directly from raw text."""
        found = []
        for s in SYSTEM_PATTERNS:
            if s.lower() in text.lower():
                found.append(s)
        return list(set(found))

    def _extract_ground_truth_data_elements(self, text):
        """Extract data elements directly from raw text."""
        found = []
        for elem in DATA_ELEMENT_PATTERNS:
            if elem.lower() in text.lower():
                found.append(elem)
        return list(set(found))

    def _extract_ground_truth_risks(self, text):
        """Detect risk indicators directly from raw text."""
        found = []
        for pattern in RISK_KEYWORDS:
            if re.search(pattern, text, re.IGNORECASE):
                found.append(pattern)
        return found

    def _compute_recall(self, ground_truth, pipeline_output, field="name"):
        """Compute recall: how many ground truth items appear in pipeline output."""
        if not ground_truth:
            return 1.0  # Nothing to find = perfect recall

        pipeline_names = set()
        for item in pipeline_output:
            if isinstance(item, dict):
                pipeline_names.add(item.get(field, item.get("name", "")).lower())
            else:
                pipeline_names.add(str(item).lower())

        found = 0
        for gt in ground_truth:
            gt_lower = gt.lower()
            # Check exact match or fuzzy match
            if gt_lower in pipeline_names:
                found += 1
            elif any(fuzz.ratio(gt_lower, pn) >= 80 for pn in pipeline_names):
                found += 1

        return found / len(ground_truth) if ground_truth else 1.0

    def _detect_hallucinations(self, pipeline_actors, source_text):
        """Find pipeline entities that don't appear in the source text."""
        hallucinated = []
        for actor in pipeline_actors:
            name = actor["name"] if isinstance(actor, dict) else str(actor)
            # Check if any word from the name appears in source
            words = name.split()
            found = any(
                w.lower() in source_text.lower()
                for w in words
                if len(w) > 2  # Skip short words
            )
            if not found:
                hallucinated.append(name)
        return hallucinated

    def _find_missing(self, ground_truth, pipeline_output):
        """Find ground truth items not in pipeline output."""
        pipeline_names = set()
        for item in pipeline_output:
            if isinstance(item, dict):
                pipeline_names.add(item.get("name", "").lower())
            else:
                pipeline_names.add(str(item).lower())

        missing = []
        for gt in ground_truth:
            gt_lower = gt.lower()
            if gt_lower not in pipeline_names and not any(
                fuzz.ratio(gt_lower, pn) >= 80 for pn in pipeline_names
            ):
                missing.append(gt)
        return missing

    def verify(self, source_text, pipeline_output):
        """
        Verify pipeline output against source text.

        Returns verification report with scores, missing/hallucinated entities,
        and whether reprocessing is needed.
        """
        # ── Step 1: Extract ground truth from raw text ──
        gt_systems = self._extract_ground_truth_systems(source_text)
        gt_data_elements = self._extract_ground_truth_data_elements(source_text)
        gt_risks = self._extract_ground_truth_risks(source_text)

        # ── Step 2: Compute recall scores ───────────────
        pipeline_systems = pipeline_output.get("systems", [])
        pipeline_data_elements = pipeline_output.get("data_elements", [])
        pipeline_risks = pipeline_output.get("risks", [])
        pipeline_flows = pipeline_output.get("flows", pipeline_output.get("data_flows", []))

        systems_score = self._compute_recall(gt_systems, pipeline_systems)
        data_elements_score = self._compute_recall(gt_data_elements, pipeline_data_elements)
        risks_score = self._compute_recall(gt_risks, pipeline_risks, field="risk_name")

        # Flow score: at least some flows should exist if systems and actors exist
        flow_score = min(1.0, len(pipeline_flows) / max(len(gt_systems), 1) * 0.5) if gt_systems else 1.0

        overall_score = (
            systems_score * 0.30 +
            data_elements_score * 0.25 +
            risks_score * 0.20 +
            flow_score * 0.25
        )

        # ── Step 3: Find missing entities ───────────────
        missing_systems = self._find_missing(gt_systems, pipeline_systems)
        missing_data_elements = self._find_missing(gt_data_elements, pipeline_data_elements)

        # ── Step 4: Detect hallucinations ───────────────
        pipeline_actors = pipeline_output.get("actors", [])
        hallucinated = self._detect_hallucinations(pipeline_actors, source_text)

        # ── Step 5: Generate report ─────────────────────
        report = {
            "scores": {
                "systems_score": round(systems_score, 2),
                "data_elements_score": round(data_elements_score, 2),
                "risks_score": round(risks_score, 2),
                "flow_score": round(flow_score, 2),
                "overall_score": round(overall_score, 2)
            },
            "ground_truth": {
                "systems": gt_systems,
                "data_elements": gt_data_elements,
                "risk_indicators": gt_risks
            },
            "missing_entities": {
                "systems": missing_systems,
                "data_elements": missing_data_elements
            },
            "hallucinated_entities": hallucinated,
            "reprocess_required": overall_score < self.reprocess_threshold
        }

        logger.info(
            f"Verification: overall={overall_score:.2f} "
            f"(systems={systems_score:.2f}, data={data_elements_score:.2f}, "
            f"risks={risks_score:.2f}, flows={flow_score:.2f}) "
            f"| missing_systems={len(missing_systems)} "
            f"| hallucinated={len(hallucinated)} "
            f"| reprocess={'YES' if report['reprocess_required'] else 'NO'}"
        )

        return report

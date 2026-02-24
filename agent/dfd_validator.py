"""
DFD Validator
Scores a DFD JSON object (0-100) and returns structured feedback.
Used in the agentic feedback loop for automatic retry if score < 75.
"""

from typing import Any, Dict, List


PASS_THRESHOLD = 75


def validate_dfd(dfd: Dict[str, Any]) -> Dict[str, Any]:
    """
    Score a DFD JSON object against quality criteria.
    Returns: {score, passed, feedback, breakdown}
    """
    score = 0
    breakdown = {}
    feedback = []

    # ── 1. Three actor types (external, internal, vendor) — 20 pts ──
    actor_types = {a.get("type") for a in dfd.get("actors", [])}
    required_types = {"external", "internal", "vendor"}
    actor_type_hits = len(actor_types & required_types)
    pts = round((actor_type_hits / 3) * 20)
    score += pts
    breakdown["actor_types"] = pts
    if actor_type_hits < 3:
        missing = required_types - actor_types
        feedback.append(
            f"Missing actor types: {missing}. Add actors for "
            f"{'external (Customers)' if 'external' in missing else ''} "
            f"{'internal (departments)' if 'internal' in missing else ''} "
            f"{'vendor (third parties)' if 'vendor' in missing else ''}."
        )

    # ── 2. Each actor has at least 1 business process — 15 pts ──
    actors = dfd.get("actors", [])
    actors_with_procs = sum(
        1 for a in actors if len(a.get("business_processes", [])) >= 1
    )
    pts = round((actors_with_procs / max(len(actors), 1)) * 15) if actors else 0
    score += pts
    breakdown["business_processes"] = pts
    for a in actors:
        if not a.get("business_processes"):
            feedback.append(
                f"Actor '{a.get('name')}' has no business processes. "
                f"Add at least one business process with collection sources."
            )

    # ── 3. Collection sources in business processes — 15 pts ──
    all_bps = [
        bp
        for a in actors
        for bp in a.get("business_processes", [])
    ]
    bps_with_sources = sum(
        1 for bp in all_bps if len(bp.get("collection_sources", [])) >= 1
    )
    pts = round((bps_with_sources / max(len(all_bps), 1)) * 15) if all_bps else 0
    score += pts
    breakdown["collection_sources"] = pts
    for bp in all_bps:
        if not bp.get("collection_sources"):
            feedback.append(
                f"Business process '{bp.get('name')}' has no collection sources. "
                f"Add the data sources and data elements collected."
            )

    # ── 4. Central process identified — 10 pts ──
    if dfd.get("central_process"):
        score += 10
        breakdown["central_process"] = 10
    else:
        breakdown["central_process"] = 0
        feedback.append(
            "No central process identified. "
            "Set 'central_process' to the main processing unit (e.g. the department itself)."
        )

    # ── 5. At least 2 dispersal sinks — 15 pts ──
    sinks = dfd.get("dispersal_sinks", [])
    if len(sinks) >= 2:
        score += 15
        breakdown["dispersal_sinks"] = 15
    elif len(sinks) == 1:
        score += 7
        breakdown["dispersal_sinks"] = 7
        feedback.append(
            "Only 1 dispersal sink found. Identify all destinations where data is sent "
            "(e.g. other departments, vendors, automated systems)."
        )
    else:
        breakdown["dispersal_sinks"] = 0
        feedback.append(
            "No dispersal sinks found. Identify where processed data flows to "
            "(e.g. grievance departments, sales, external vendors)."
        )

    # ── 6. At least 1 storage system — 10 pts ──
    storage = dfd.get("storage_systems", [])
    if storage:
        score += 10
        breakdown["storage_systems"] = 10
    else:
        breakdown["storage_systems"] = 0
        feedback.append(
            "No storage systems identified. "
            "Add all systems where data is persisted (CRM, cloud drives, databases)."
        )

    # ── 7. Data flows connect sources to process and to sinks — 15 pts ──
    flows = dfd.get("data_flows", [])
    inbound = [f for f in flows if f.get("to_id") == "central_process"]
    outbound = [f for f in flows if f.get("from_id") == "central_process"]
    flow_score = 0
    if inbound:
        flow_score += 7
    else:
        feedback.append(
            "No inbound data flows to the central process. "
            "Map flows from each collection source to the central process."
        )
    if outbound:
        flow_score += 8
    else:
        feedback.append(
            "No outbound data flows from the central process. "
            "Map flows from the central process to each dispersal sink."
        )
    score += flow_score
    breakdown["data_flows"] = flow_score

    passed = score >= PASS_THRESHOLD

    return {
        "score": score,
        "passed": passed,
        "threshold": PASS_THRESHOLD,
        "breakdown": breakdown,
        "feedback": feedback,
    }


def format_validation_report(result: Dict[str, Any]) -> str:
    """Format the validation result as a readable string for logging."""
    status = "PASSED ✓" if result["passed"] else "FAILED ✗"
    lines = [
        f"DFD Validation: {status} ({result['score']}/{result['threshold']}+ to pass)",
        "Breakdown:",
    ]
    for k, v in result["breakdown"].items():
        lines.append(f"  {k:25s}: {v} pts")
    if result["feedback"]:
        lines.append("Feedback for improvement:")
        for fb in result["feedback"]:
            lines.append(f"  - {fb}")
    return "\n".join(lines)

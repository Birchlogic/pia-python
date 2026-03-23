"""
AI-powered validation methods for Master DFD Agent
"""
import json
from typing import List, Dict, Any
from utils.logger import setup_logger
from utils.llm_adapter import get_llm_client, AIConfig

logger = setup_logger("MasterDFDAI")


def ai_validate_nodes(nodes: List[Dict], sessions_data: List[Dict], ai_config: Dict) -> List[Dict]:
    """
    Use AI to validate and resolve conflicts in merged nodes.
    
    AI will:
    - Identify duplicate entities with different names
    - Resolve conflicts in data elements
    - Validate risk severity consistency
    - Suggest entity type corrections
    """
    api_key = ai_config.get("apiKey")
    model = ai_config.get("model", "anthropic/claude-3.5-sonnet")
    
    if not api_key or len(nodes) == 0:
        return nodes
    
    logger.info(f"AI validating {len(nodes)} merged nodes...")
    
    # Prepare context for AI
    node_summary = []
    for node in nodes[:50]:  # Limit to first 50 for token efficiency
        node_summary.append({
            "name": node.get("name"),
            "type": node.get("type"),
            "data_elements": node.get("data_elements", [])[:5],  # First 5 data elements
            "risk_count": len(node.get("risks", [])),
            "source_sessions": node.get("_source_sessions", [])
        })
    
    prompt = f"""You are a data privacy expert reviewing a merged Master DFD from {len(sessions_data)} different department sessions.

**Merged Entities Summary:**
{json.dumps(node_summary, indent=2)}

**Your Task:**
1. Identify potential duplicate entities (same entity with different names)
2. Flag inconsistencies in entity types (e.g., "Customer" marked as "system" vs "actor")
3. Validate risk severity across departments
4. Suggest corrections for entity classification

**Output Format (JSON):**
{{
  "duplicates_found": [
    {{"entity_1": "Salesforce", "entity_2": "Sales Force", "confidence": "high", "action": "merge"}}
  ],
  "type_corrections": [
    {{"entity": "Customer", "current_type": "unknown", "suggested_type": "actor", "reason": "..."}}
  ],
  "validation_summary": "Brief summary of findings",
  "critical_issues": ["Issue 1", "Issue 2"]
}}

Respond ONLY with valid JSON."""

    try:
        # Create AI config and get LLM client
        client = get_llm_client(ai_config)
        
        # Call LLM with messages format
        response = client.messages.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000
        )
        
        # Extract text from response
        response_text = response.content[0].text
        
        validation_result = json.loads(response_text)
        logger.info(f"AI Validation: {validation_result.get('validation_summary', 'Complete')}")
        
        # Apply AI suggestions
        nodes = apply_ai_corrections(nodes, validation_result)
        
        return nodes
    except Exception as e:
        logger.error(f"AI validation failed: {e}")
        return nodes


def apply_ai_corrections(nodes: List[Dict], validation: Dict) -> List[Dict]:
    """Apply AI-suggested corrections to nodes."""
    
    # Apply type corrections
    type_corrections = validation.get("type_corrections", [])
    for correction in type_corrections:
        entity_name = correction.get("entity", "").lower()
        suggested_type = correction.get("suggested_type")
        
        for node in nodes:
            if node.get("name", "").lower() == entity_name and suggested_type:
                logger.info(f"AI corrected type for '{node['name']}': {node['type']} → {suggested_type}")
                node["type"] = suggested_type
    
    return nodes


def generate_executive_summary(nodes: List[Dict], edges: List[Dict], overview: Dict, ai_config: Dict) -> str:
    """
    Generate AI-powered executive summary for Master DFD.
    
    Provides:
    - High-level data flow overview
    - Critical risk highlights
    - Compliance gaps
    - Recommendations
    """
    api_key = ai_config.get("apiKey")
    model = ai_config.get("model", "anthropic/claude-3.5-sonnet")
    
    if not api_key:
        return "AI executive summary not available (no API key provided)"
    
    logger.info("Generating AI executive summary...")
    
    # Prepare context
    context = {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "total_sessions": overview.get("total_sessions", 0),
        "departments": overview.get("departments", []),
        "total_risks": overview.get("total_risks", 0),
        "risk_breakdown": overview.get("risk_severity_breakdown", {}),
        "total_actors": overview.get("total_actors", 0),
        "total_systems": overview.get("total_systems", 0),
        "total_flows": overview.get("total_flows", 0),
        "unique_data_elements": overview.get("total_data_elements", 0)
    }
    
    # Sample high-risk nodes
    high_risk_nodes = [
        {"name": n["name"], "type": n["type"], "risk_count": len(n.get("risks", []))}
        for n in nodes if len(n.get("risks", [])) > 3
    ][:10]
    
    prompt = f"""You are a Chief Privacy Officer reviewing a company-wide Master Data Flow Diagram.

**Project Overview:**
{json.dumps(context, indent=2)}

**High-Risk Entities:**
{json.dumps(high_risk_nodes, indent=2)}

**Generate an Executive Summary covering:**
1. **Data Flow Overview** - Key data movements across departments
2. **Critical Risks** - Top privacy/security concerns (focus on critical/high severity)
3. **Compliance Gaps** - Potential regulatory issues
4. **Recommendations** - Top 3-5 actionable recommendations

**Format:** Professional executive summary (300-400 words), suitable for C-level stakeholders.

Write in clear, business-focused language. Highlight critical issues that require immediate attention."""

    try:
        # Create AI config and get LLM client
        client = get_llm_client(ai_config)
        
        # Call LLM with messages format
        response = client.messages.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500
        )
        
        # Extract text from response
        summary = response.content[0].text
        
        logger.info("Executive summary generated successfully")
        return summary.strip()
    except Exception as e:
        logger.error(f"Failed to generate executive summary: {e}")
        return f"Executive summary generation failed: {str(e)}"

from utils.llm_adapter import get_llm_client
import anthropic
import json
from typing import List, Dict, Any
from config import Config
from utils.logger import setup_logger
from models.extracted_data import ExtractedTranscriptData

logger = setup_logger("ReportGenerationAgent")

class ReportGenerationAgent:
    def __init__(self, ai_config: dict = None):
        self.ai_config = ai_config or {}
        self.client = get_llm_client(self.ai_config)
        self.model = self.ai_config.get("model") or "claude-3-5-sonnet-20241022"

    def generate_report(self, 
                        extracted_data_list: List[ExtractedTranscriptData], 
                        context: str, 
                        metadata: Dict[str, Any],
                        privacy_dfd_content: str = "") -> str:
        logger.info(f"Generating report for department: {metadata.get('department', 'Unknown')}")
        
        # Consolidate data from multiple sessions if needed
        consolidated_data = self._consolidate_data(extracted_data_list)
        
        # Embed pre-generated Privacy DFD section if available
        dfd_section = ""
        if privacy_dfd_content:
            dfd_section = f"""
## Privacy Data Flow Diagram

> The following Privacy DFD was generated from structured analysis of all interview transcripts.
> It maps personal data flows by lifecycle phase (Collection → Processing → Storage → Sharing → External Transfer)
> and identifies privacy risks at each stage.

{privacy_dfd_content}
"""
        
        prompt = f"""
        You are a Production-Grade AI Compliance Consultant specialized in ISO27001 and DPDPA.
        Your task is to generate a professional Departmental Assessment Report.
        
        Metadata:
        {json.dumps(metadata, indent=2)}
        
        Consolidated Extracted Data:
        {consolidated_data.model_dump_json(indent=2)}
        
        Historical Context (from Vector DB):
        {context}
        
        A Privacy DFD has already been generated and will be embedded in the report at Section 5.
        Do NOT regenerate the DFD. Focus on the audit findings, risk register, and recommendations.
        
        ---
        REPORT REQUIREMENTS:
        - Tone: Formal, professional compliance consulting.
        - Structure: Markdown formatted.
        - Sections:
          1. # Department Assessment Report
          2. ## Introduction
          3. ## Objectives
          4. ## Department Overview
          5. ## Systems Landscape
          6. [PRIVACY DFD SECTION — will be auto-inserted here, write a placeholder]
          7. ## Key Observations
          8. ## Findings (Audit-style, numbered F1, F2... with Observation, Impact, Evidence)
          9. ## Risks (Table: Risk ID, Title, Description, Impact, Likelihood, Rating)
          10. ## Recommendations (Grouped: Immediate 0-30 days, Short-term 30-90 days, Long-term)
          11. ## Conclusion

        Important: Write Section 6 as exactly this text: {{PRIVACY_DFD_PLACEHOLDER}}

        DO NOT hallucinate systems. DO NOT use informal writing. Be precise and formal.
        """

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8000,
                temperature=0,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            report_text = response.content[0].text
            
            # Inject the Privacy DFD section in place of placeholder
            if dfd_section:
                report_text = report_text.replace("{PRIVACY_DFD_PLACEHOLDER}", dfd_section)
            
            return report_text
            
        except Exception as e:
            logger.error(f"Error during report generation: {e}")
            raise

    def _consolidate_data(self, data_list: List[ExtractedTranscriptData]) -> ExtractedTranscriptData:
        # Simple consolidation: merge lists and remove duplicates by name/title
        consolidated = ExtractedTranscriptData()
        
        # Use dictionaries to deduplicate
        entities = {}
        data_inventory = [] # Harder to deduplicate perfectly, just append
        processes = {}
        risks = {}
        compliance_gaps = []
        
        for data in data_list:
            for e in data.entities:
                entities[e.name] = e
            data_inventory.extend(data.data_inventory)
            for p in data.processes:
                processes[p.name] = p
            for r in data.risks:
                risks[r.title] = r
            compliance_gaps.extend(data.compliance_gaps)
            
        consolidated.entities = list(entities.values())
        consolidated.data_inventory = data_inventory
        consolidated.processes = list(processes.values())
        consolidated.risks = list(risks.values())
        consolidated.compliance_gaps = compliance_gaps
        
        return consolidated

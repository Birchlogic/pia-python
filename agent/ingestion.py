import anthropic
import json
from typing import List, Dict
from config import Config
from utils.logger import setup_logger
from models.extracted_data import ExtractedTranscriptData

logger = setup_logger("IngestionAgent")

class IngestionAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        self.model = Config.CLAUDE_MODEL

    def ingest_transcript(self, file_path: str) -> ExtractedTranscriptData:
        logger.info(f"Ingesting transcript from {file_path}")
        with open(file_path, 'r') as f:
            content = f.read()

        prompt = f"""
        You are a professional Compliance Analyst. Extract structured information from the following transcript for an ISO27001/DPDPA assessment.
        
        Transcript content:
        {content}
        
        Extract the following:
        1. Entities (Systems, Departments, Third Parties)
        2. Data Types (PII, Financial, etc.) and their flows
        3. Processes (How data is handled)
        4. Risks identified
        5. Compliance gaps (Gaps against security standards)
        
        Respond ONLY with a JSON object matching this structure:
        {{
            "entities": [{{ "name": "...", "type": "...", "description": "..." }}],
            "data_inventory": [{{ "data_type": "...", "source": "...", "destination": "...", "protection_level": "..." }}],
            "processes": [{{ "name": "...", "description": "...", "involved_entities": ["...", "..."] }}],
            "risks": [{{ "title": "...", "description": "...", "impact": "...", "likelihood": "..." }}],
            "compliance_gaps": [{{ "requirement": "...", "observation": "...", "gap_description": "..." }}]
        }}
        """

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4000,
                temperature=0,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            # Extract JSON from response
            raw_content = response.content[0].text
            
            # Robust JSON extraction
            json_str = self._extract_json(raw_content)
            data = json.loads(json_str)
            return ExtractedTranscriptData(**data)
            
        except Exception as e:
            logger.error(f"Error during transcript ingestion: {e}")
            logger.debug(f"Raw response: {raw_content if 'raw_content' in locals() else 'N/A'}")
            raise

    def _extract_json(self, text: str) -> str:
        # Check for markdown code blocks
        if "```json" in text:
            return text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            return text.split("```")[1].split("```")[0].strip()
        return text.strip()

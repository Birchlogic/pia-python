from agent.kb_builder import KBBuilder
from utils.logger import setup_logger
from typing import Dict, Any

logger = setup_logger("LearningLoop")

class LearningLoop:
    def __init__(self, kb_builder: KBBuilder):
        self.kb_builder = kb_builder

    def process_feedback(self, report_id: str, report_content: str, metadata: Dict[str, Any]):
        logger.info(f"Processing learning loop for report {report_id}")
        
        # In a real system, this might involve manually corrected reports or user feedback.
        # Here we just store the generated report back into the vector DB as a 'successful' reference.
        self.kb_builder.add_generated_report(
            report_id=report_id,
            content=report_content,
            metadata=metadata
        )

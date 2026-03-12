"""
Pipeline Runner — Orchestrates the full document intelligence pipeline.

Pipeline Order:
  1. Document ingestion + type detection
  2. Text cleaning (transcripts / field notes)
  3. Deterministic extraction (entities, systems, data elements, risks)
  4. Agentic extraction (SystemAgent, DataFlowAgent, RiskAgent)
  5. Entity Normalization Agent (deduplicate, classify, clean)
  6. Flow Canonicalization Agent (merge fragmented flows)
  7. Pipeline Verification Agent (verify vs source text)
  8. Feedback loop (re-extract if score < threshold)
  9. Final DFD generation (DFDBuilderAgent)

Output: Structured JSON for DFD generation with verification report.
"""
import os
import json
from pathlib import Path
from datetime import datetime

from utils.logger import setup_logger
from config import Config

# Layer 1 — Deterministic NLP
from test.detect_document_type import detect_document_type
from test.clean_transcripts import CleanTranscripts
from test.clean_field_notes import CleanFieldNotes
from test.entity_extraction import extract_entities, extract_actors_from_dialogue
from test.extract_data_element import extract_data_elements
from test.extract_systems import extract_systems
from test.detect_risk import detect_risks, detect_risk_statements

# Layer 2 — Agentic AI
from test.agents.system_agent import SystemExtractionAgent
from test.agents.dataflow_agent import DataFlowAgent
from test.agents.risk_agent import RiskAnalysisAgent
from test.agents.dfd_agent import DFDBuilderAgent

# Layer 3 — Normalization, Canonicalization, Verification
from test.agents.entity_normalization_agent import EntityNormalizationAgent
from test.agents.flow_canonicalizer_agent import FlowCanonicalizerAgent
from test.agents.pipeline_verification_agent import PipelineVerificationAgent
from test.agents.schema_generator_agent import SchemaGeneratorAgent

logger = setup_logger("PipelineRunner")

MAX_REPROCESS_ATTEMPTS = 2


class PipelineRunner:

    def __init__(self, ai_config: dict = None):
        self.ai_config = ai_config or {}
        
        self.transcript_cleaner = CleanTranscripts()
        self.notes_cleaner = CleanFieldNotes()

        # Extraction agents
        self.system_agent = SystemExtractionAgent(ai_config=self.ai_config)
        self.dataflow_agent = DataFlowAgent(ai_config=self.ai_config)
        self.risk_agent = RiskAnalysisAgent(ai_config=self.ai_config)
        self.dfd_agent = DFDBuilderAgent(ai_config=self.ai_config)

        # Enhancement agents
        self.entity_norm_agent = EntityNormalizationAgent(ai_config=self.ai_config)
        self.flow_canon_agent = FlowCanonicalizerAgent(ai_config=self.ai_config)
        self.verification_agent = PipelineVerificationAgent(ai_config=self.ai_config)
        self.schema_agent = SchemaGeneratorAgent(ai_config=self.ai_config)

    # ─────────────────────────────────────────────────
    # Phase 1: Ingest + Clean
    # ─────────────────────────────────────────────────
    def _ingest(self, file_path, raw_text):
        """Detect doc type, parse, and return structured chunks."""
        doc_type_result = detect_document_type(raw_text)
        doc_type = doc_type_result["type"]
        logger.info(f"  [1] Doc type: {doc_type} (confidence: {doc_type_result['confidence']:.2f})")

        text_chunks = []
        metadata = {}
        actors = []

        if doc_type == "transcript":
            parsed = self.transcript_cleaner.clean_transcript(file_path)
            metadata = parsed.get("metadata", {})
            dialogue = parsed.get("dialogue", [])
            text_chunks = [r["text"] for r in dialogue]
            actor_info = extract_actors_from_dialogue(dialogue)
            actors = list(set(actor_info["speakers"] + actor_info["mentioned_persons"]))

        elif doc_type == "field_notes":
            parsed = self.notes_cleaner.clean_notes(file_path)
            metadata = parsed.get("metadata", {})
            sections = parsed.get("sections", {})
            for title, section in sections.items():
                text_chunks.append(section.get("raw", "") if isinstance(section, dict) else section)
        else:
            text_chunks = [raw_text]

        return doc_type_result, text_chunks, metadata, actors

    # ─────────────────────────────────────────────────
    # Phase 2: Deterministic extraction
    # ─────────────────────────────────────────────────
    def _deterministic_extract(self, combined_text, actors):
        """Run all deterministic NLP extractors."""
        entities = extract_entities(combined_text)
        actors += entities.get("persons", [])
        actors = list(set(actors))

        det_systems = extract_systems(combined_text)
        det_data_elements = extract_data_elements(combined_text)
        det_risks = detect_risks(combined_text)
        risk_statements = detect_risk_statements(combined_text)

        logger.info(
            f"  [2] Deterministic: Actors={len(actors)}, Systems={len(det_systems)}, "
            f"Elements={len(det_data_elements)}, Risks={len(det_risks)}"
        )
        return actors, det_systems, det_data_elements, det_risks, risk_statements, entities

    # ─────────────────────────────────────────────────
    # Phase 3: Agentic extraction
    # ─────────────────────────────────────────────────
    def _agentic_extract(self, text_chunks, actors, det_systems, det_data_elements, det_risks):
        """Run all LLM-powered extraction agents."""
        logger.info("  [3] Running agentic extraction...")

        agent_systems = self.system_agent.extract(text_chunks)
        all_system_names = list(set(
            det_systems + [s["name"] for s in agent_systems if "name" in s]
        ))

        data_flows = self.dataflow_agent.extract(
            text_chunks, actors=actors, systems=all_system_names,
            data_elements=det_data_elements
        )

        agent_risks = self.risk_agent.analyze(
            text_chunks, data_elements=det_data_elements,
            systems=all_system_names, deterministic_risks=det_risks
        )

        logger.info(
            f"  [3] Agentic: Systems={len(agent_systems)}, "
            f"Flows={len(data_flows)}, Risks={len(agent_risks)}"
        )
        return agent_systems, all_system_names, data_flows, agent_risks

    # ─────────────────────────────────────────────────
    # Phase 4: Entity normalization
    # ─────────────────────────────────────────────────
    def _normalize_entities(self, actors, agent_systems, det_data_elements, data_flows):
        """Deduplicate, classify, and clean entities."""
        logger.info("  [4] Running EntityNormalizationAgent...")
        system_names = [s["name"] if isinstance(s, dict) else s for s in agent_systems]
        normalized = self.entity_norm_agent.normalize(
            actors=actors, systems=system_names,
            data_elements=det_data_elements, data_flows=data_flows
        )
        return normalized

    # ─────────────────────────────────────────────────
    # Phase 5: Flow canonicalization
    # ─────────────────────────────────────────────────
    def _canonicalize_flows(self, data_flows, normalized_entities, det_data_elements):
        """Merge fragmented flows into canonical DFD flows."""
        logger.info("  [5] Running FlowCanonicalizerAgent...")
        canonical_flows = self.flow_canon_agent.canonicalize(
            data_flows=data_flows,
            normalized_entities=normalized_entities,
            data_elements=det_data_elements
        )
        return canonical_flows

    # ─────────────────────────────────────────────────
    # Phase 6: Verification
    # ─────────────────────────────────────────────────
    def _verify(self, raw_text, pipeline_output):
        """Verify pipeline output against source text."""
        logger.info("  [6] Running PipelineVerificationAgent...")
        report = self.verification_agent.verify(raw_text, pipeline_output)
        return report

    # ─────────────────────────────────────────────────
    # Full pipeline
    # ─────────────────────────────────────────────────
    def process_file(self, file_path):
        """Process a single file through the full enhanced pipeline."""
        file_path = Path(file_path)
        logger.info(f"Processing: {file_path.name}")

        raw_text = file_path.read_text(encoding="utf-8")

        # Phase 1: Ingest + Clean
        doc_type_result, text_chunks, metadata, actors = self._ingest(file_path, raw_text)
        combined_text = "\n".join(text_chunks)

        # Phase 2: Deterministic extraction
        actors, det_systems, det_data_elements, det_risks, risk_stmts, entities = \
            self._deterministic_extract(combined_text, actors)

        # Phase 3: Agentic extraction
        agent_systems, all_system_names, data_flows, agent_risks = \
            self._agentic_extract(text_chunks, actors, det_systems, det_data_elements, det_risks)

        # Phase 4: Entity normalization
        normalized = self._normalize_entities(actors, agent_systems, det_data_elements, data_flows)

        # Phase 5: Flow canonicalization
        canonical_flows = self._canonicalize_flows(data_flows, normalized, det_data_elements)

        # Build intermediate output for verification
        pipeline_output = {
            "actors": normalized.get("actors", []),
            "systems": normalized.get("systems", []),
            "data_elements": det_data_elements,
            "flows": canonical_flows,
            "risks": agent_risks
        }

        # Phase 6: Verification
        verification_report = self._verify(raw_text, pipeline_output)

        # Phase 7: Feedback loop
        attempt = 0
        while verification_report.get("reprocess_required", False) and attempt < MAX_REPROCESS_ATTEMPTS:
            attempt += 1
            logger.info(f"  [7] Feedback loop — re-extracting (attempt {attempt}/{MAX_REPROCESS_ATTEMPTS})...")

            # Add missing entities to extraction context
            missing = verification_report.get("missing_entities", {})
            missing_systems = missing.get("systems", [])
            missing_elements = missing.get("data_elements", [])

            # Re-run agentic extraction with enriched context
            enriched_chunks = text_chunks + [
                f"IMPORTANT: Also look for these systems: {', '.join(missing_systems)}" if missing_systems else "",
                f"IMPORTANT: Also look for these data elements: {', '.join(missing_elements)}" if missing_elements else ""
            ]
            enriched_chunks = [c for c in enriched_chunks if c]

            _, _, data_flows_v2, agent_risks_v2 = \
                self._agentic_extract(enriched_chunks, actors, det_systems + missing_systems,
                                      det_data_elements + missing_elements, det_risks)

            # Merge new flows with existing
            merged_flows = data_flows + data_flows_v2
            canonical_flows = self._canonicalize_flows(merged_flows, normalized, det_data_elements + missing_elements)

            # Merge risks
            existing_risk_names = {r.get("risk_name", "") for r in agent_risks}
            for r in agent_risks_v2:
                if r.get("risk_name", "") not in existing_risk_names:
                    agent_risks.append(r)

            pipeline_output["flows"] = canonical_flows
            pipeline_output["risks"] = agent_risks
            pipeline_output["data_elements"] = list(set(det_data_elements + missing_elements))

            verification_report = self._verify(raw_text, pipeline_output)

        # Phase 8: Schema and Data Inventory Generation
        logger.info("  [8] Generating Compliance Schema and Data Inventory...")
        schema_output = self.schema_agent.run(raw_text, pipeline_output)

        # Extract newly found entities from schema to enrich DFD
        schema_systems = []
        schema_elements = []
        try:
            inventory = schema_output.get("inventory", [])
            for item in inventory:
                if isinstance(item, dict):
                    sys_name = item.get("storage_location", "")
                    if sys_name and sys_name.lower() not in ["n/a", "unknown"]:
                        schema_systems.append(sys_name)
                    
                    data_cat = item.get("data_category", "")
                    if data_cat:
                        schema_elements.append(data_cat)
        except Exception as e:
            logger.warning(f"Failed to extract schema entities for DFD: {e}")

        # Safely extract names if systems/elements are dictionaries
        sys_list = [s["name"] if isinstance(s, dict) else s for s in normalized.get("systems", [])]
        elem_list = [e["name"] if isinstance(e, dict) else e for e in pipeline_output.get("data_elements", [])]

        enriched_systems = list(set(sys_list + schema_systems))
        enriched_elements = list(set(elem_list + schema_elements))

        # Phase 9: Final DFD generation
        logger.info("  [9] Running DFDBuilderAgent (final) with enriched Schema context...")
        actor_names = [a["name"] if isinstance(a, dict) else a for a in normalized.get("actors", [])]

        dfd_graph = self.dfd_agent.build(
            actors=actor_names,
            systems=enriched_systems,
            data_elements=enriched_elements,
            data_flows=canonical_flows,
            risks=agent_risks
        )
        
        # Assemble final output
        result = {
            "metadata": {
                **metadata,
                "source_file": file_path.name,
                "document_type": doc_type_result["type"],
                "processed_at": datetime.now().isoformat(),
                "reprocess_attempts": attempt
            },
            "actors": normalized.get("actors", []),
            "systems": normalized.get("systems", []),
            "data_elements": pipeline_output["data_elements"],
            "flows": canonical_flows,
            "risks": agent_risks,
            "verification_report": verification_report,
            "dfd_graph": dfd_graph,
            "compliance_schema": schema_output.get("schema"),
            "data_inventory": schema_output.get("inventory"),
            "normalization_report": {
                "removed_entities": normalized.get("removed", [])
            }
        }

        score = verification_report.get("scores", {}).get("overall_score", 0)
        logger.info(f"  ✅ Pipeline complete — score: {score:.2f}")
        return result

    def process_files(self, file_paths, output_dir=None):
        """Process multiple files and optionally save results."""
        results = []
        for fp in file_paths:
            try:
                result = self.process_file(fp)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to process {fp}: {e}", exc_info=True)

        if output_dir:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            for i, result in enumerate(results):
                source = result["metadata"].get("source_file", f"doc_{i}")
                stem = Path(source).stem
                out_path = output_dir / f"{stem}_intelligence.json"
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(result, f, indent=2)
                logger.info(f"Saved: {out_path}")

        return results

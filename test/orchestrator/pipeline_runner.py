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
import time
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


class TokenTracker:
    """Wraps an LLM client to intercept and accumulate token usage."""

    def __init__(self, real_client):
        self._real = real_client
        self.total_in = 0
        self.total_out = 0

    def reset(self):
        self.total_in = 0
        self.total_out = 0

    @property
    def messages(self):
        return _TrackedMessages(self._real.messages, self)


class _TrackedMessages:
    """Proxy for client.messages that records token counts."""

    def __init__(self, real_messages, tracker):
        self._real = real_messages
        self._tracker = tracker

    def create(self, **kwargs):
        resp = self._real.create(**kwargs)
        usage = getattr(resp, 'usage', None)
        if usage:
            self._tracker.total_in += getattr(usage, 'input_tokens', 0)
            self._tracker.total_out += getattr(usage, 'output_tokens', 0)
        return resp


class PipelineRunner:

    def __init__(self, ai_config: dict = None, stage_callback=None):
        """
        Args:
            ai_config: LLM provider config dict
            stage_callback: optional fn(stage_name, stage_order, output_summary, in_tokens, out_tokens, duration_ms)
        """
        self.ai_config = ai_config or {}
        self.stage_callback = stage_callback
        self._stage_order = 0

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

        # Wrap all LLM clients with token tracking
        self._trackers = []
        for agent in [self.system_agent, self.dataflow_agent, self.risk_agent,
                       self.dfd_agent, self.entity_norm_agent, self.flow_canon_agent,
                       self.verification_agent, self.schema_agent]:
            if hasattr(agent, 'client'):
                tracker = TokenTracker(agent.client)
                agent.client = tracker
                self._trackers.append(tracker)

    def _reset_tokens(self):
        for t in self._trackers:
            t.reset()

    def _sum_tokens(self):
        return sum(t.total_in for t in self._trackers), sum(t.total_out for t in self._trackers)

    def _report_stage(self, stage_name, output_summary, start_time):
        """Report stage completion to callback if registered."""
        self._stage_order += 1
        in_tok, out_tok = self._sum_tokens()
        duration_ms = int((time.time() - start_time) * 1000)
        self._reset_tokens()
        logger.info(f"  [{self._stage_order}] {stage_name}: in_tokens={in_tok} out_tokens={out_tok} duration={duration_ms}ms")
        if self.stage_callback:
            try:
                self.stage_callback(
                    stage_name=stage_name,
                    stage_order=self._stage_order,
                    output_summary=output_summary,
                    in_tokens=in_tok,
                    out_tokens=out_tok,
                    duration_ms=duration_ms
                )
            except Exception as e:
                logger.warning(f"Stage callback failed for {stage_name}: {e}")

    # ─────────────────────────────────────────────────
    # Phase 1: Ingest + Clean
    # ─────────────────────────────────────────────────
    def _ingest(self, file_path, raw_text):
        """Detect doc type, parse, and return structured chunks + dialogue records."""
        doc_type_result = detect_document_type(raw_text)
        doc_type = doc_type_result["type"]
        logger.info(f"  [1] Doc type: {doc_type} (confidence: {doc_type_result['confidence']:.2f})")

        text_chunks = []
        dialogue_records = []  # Structured evidence: {timestamp, speaker, role, text, systems, source_file}
        metadata = {}
        actors = []
        source_file = Path(file_path).name

        if doc_type == "transcript":
            parsed = self.transcript_cleaner.clean_transcript(file_path)
            metadata = parsed.get("metadata", {})
            dialogue = parsed.get("dialogue", [])
            text_chunks = [r["text"] for r in dialogue]
            for r in dialogue:
                dialogue_records.append({
                    "timestamp": r.get("timestamp", ""),
                    "speaker": r.get("speaker", ""),
                    "role": r.get("role", ""),
                    "text": r.get("text", ""),
                    "systems": r.get("systems", []),
                    "source_file": source_file
                })
            actor_info = extract_actors_from_dialogue(dialogue)
            actors = list(set(actor_info["speakers"] + actor_info["mentioned_persons"]))

        elif doc_type == "field_notes":
            parsed = self.notes_cleaner.clean_notes(file_path)
            metadata = parsed.get("metadata", {})
            sections = parsed.get("sections", {})
            for title, section in sections.items():
                raw = section.get("raw", "") if isinstance(section, dict) else section
                text_chunks.append(raw)
                dialogue_records.append({
                    "timestamp": "",
                    "speaker": metadata.get("analyst", ""),
                    "role": "analyst",
                    "text": raw,
                    "systems": [],
                    "source_file": source_file
                })
        else:
            text_chunks = [raw_text]
            dialogue_records.append({
                "timestamp": "",
                "speaker": "",
                "role": "",
                "text": raw_text[:2000],
                "systems": [],
                "source_file": source_file
            })

        return doc_type_result, text_chunks, dialogue_records, metadata, actors

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
    def _agentic_extract(self, text_chunks, actors, det_systems, det_data_elements, det_risks, structured_context=None):
        """Run all LLM-powered extraction agents with structured evidence context."""
        logger.info("  [3] Running agentic extraction...")

        # Use structured context (with timestamps) if available, else fall back to text_chunks
        context_for_agents = structured_context if structured_context else text_chunks

        agent_systems = self.system_agent.extract(text_chunks, structured_context=context_for_agents)
        all_system_names = list(set(
            det_systems + [s["name"] for s in agent_systems if "name" in s]
        ))

        data_flows = self.dataflow_agent.extract(
            text_chunks, actors=actors, systems=all_system_names,
            data_elements=det_data_elements, structured_context=context_for_agents
        )

        agent_risks = self.risk_agent.analyze(
            text_chunks, data_elements=det_data_elements,
            systems=all_system_names, deterministic_risks=det_risks,
            structured_context=context_for_agents
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
    def _build_structured_context(self, dialogue_records, max_lines=80):
        """Build a structured text context with timestamps and speakers for AI agents."""
        lines = []
        for r in dialogue_records[:max_lines]:
            ts = r.get("timestamp", "")
            speaker = r.get("speaker", "")
            role = r.get("role", "")
            text = r.get("text", "")
            src = r.get("source_file", "")
            prefix = f"[{ts}]" if ts else ""
            if speaker:
                prefix += f" {speaker} ({role})" if role else f" {speaker}"
            if src:
                prefix += f" [{src}]"
            lines.append(f"{prefix}: {text}" if prefix else text)
        return "\n".join(lines)

    def process_file(self, file_path):
        """Process a single file through the full enhanced pipeline."""
        file_path = Path(file_path)
        logger.info(f"Processing: {file_path.name}")
        self._stage_order = 0
        self._reset_tokens()

        raw_text = file_path.read_text(encoding="utf-8")

        # Phase 1: Ingest + Clean
        t0 = time.time()
        doc_type_result, text_chunks, dialogue_records, metadata, actors = self._ingest(file_path, raw_text)
        combined_text = "\n".join(text_chunks)
        structured_context = self._build_structured_context(dialogue_records)
        self._report_stage("ingest_and_clean", {
            "doc_type": doc_type_result["type"],
            "chunks": len(text_chunks),
            "dialogue_records": len(dialogue_records),
            "actors_found": len(actors)
        }, t0)

        # Phase 2: Deterministic extraction
        t0 = time.time()
        actors, det_systems, det_data_elements, det_risks, risk_stmts, entities = \
            self._deterministic_extract(combined_text, actors)
        self._report_stage("deterministic_extraction", {
            "actors": len(actors),
            "systems": len(det_systems),
            "data_elements": len(det_data_elements),
            "risks": len(det_risks)
        }, t0)

        # Phase 3: Agentic extraction
        t0 = time.time()
        agent_systems, all_system_names, data_flows, agent_risks = \
            self._agentic_extract(text_chunks, actors, det_systems, det_data_elements, det_risks,
                                  structured_context=structured_context)
        self._report_stage("agentic_extraction", {
            "agent_systems": len(agent_systems),
            "data_flows": len(data_flows),
            "agent_risks": len(agent_risks)
        }, t0)

        # Phase 4: Entity normalization
        t0 = time.time()
        normalized = self._normalize_entities(actors, agent_systems, det_data_elements, data_flows)
        self._report_stage("entity_normalization", {
            "actors": len(normalized.get("actors", [])),
            "systems": len(normalized.get("systems", [])),
            "removed": len(normalized.get("removed", []))
        }, t0)

        # Phase 5: Flow canonicalization
        t0 = time.time()
        canonical_flows = self._canonicalize_flows(data_flows, normalized, det_data_elements)
        self._report_stage("flow_canonicalization", {
            "raw_flows": len(data_flows),
            "canonical_flows": len(canonical_flows)
        }, t0)

        # Build intermediate output for verification
        pipeline_output = {
            "actors": normalized.get("actors", []),
            "systems": normalized.get("systems", []),
            "data_elements": det_data_elements,
            "flows": canonical_flows,
            "risks": agent_risks
        }

        # Phase 6: Verification
        t0 = time.time()
        verification_report = self._verify(raw_text, pipeline_output)
        self._report_stage("verification", {
            "scores": verification_report.get("scores", {}),
            "reprocess_required": verification_report.get("reprocess_required", False)
        }, t0)

        # Phase 7: Feedback loop
        attempt = 0
        while verification_report.get("reprocess_required", False) and attempt < MAX_REPROCESS_ATTEMPTS:
            attempt += 1
            t0 = time.time()
            logger.info(f"  [7] Feedback loop — re-extracting (attempt {attempt}/{MAX_REPROCESS_ATTEMPTS})...")

            missing = verification_report.get("missing_entities", {})
            missing_systems = missing.get("systems", [])
            missing_elements = missing.get("data_elements", [])

            enriched_chunks = text_chunks + [
                f"IMPORTANT: Also look for these systems: {', '.join(missing_systems)}" if missing_systems else "",
                f"IMPORTANT: Also look for these data elements: {', '.join(missing_elements)}" if missing_elements else ""
            ]
            enriched_chunks = [c for c in enriched_chunks if c]

            enriched_structured = structured_context
            if missing_systems:
                enriched_structured += f"\n\n[SYSTEM NOTE] Also look for these systems: {', '.join(missing_systems)}"
            if missing_elements:
                enriched_structured += f"\n\n[SYSTEM NOTE] Also look for these data elements: {', '.join(missing_elements)}"

            _, _, data_flows_v2, agent_risks_v2 = \
                self._agentic_extract(enriched_chunks, actors, det_systems + missing_systems,
                                      det_data_elements + missing_elements, det_risks,
                                      structured_context=enriched_structured)

            merged_flows = data_flows + data_flows_v2
            canonical_flows = self._canonicalize_flows(merged_flows, normalized, det_data_elements + missing_elements)

            existing_risk_names = {r.get("risk_name", "") for r in agent_risks}
            for r in agent_risks_v2:
                if r.get("risk_name", "") not in existing_risk_names:
                    agent_risks.append(r)

            pipeline_output["flows"] = canonical_flows
            pipeline_output["risks"] = agent_risks
            pipeline_output["data_elements"] = list(set(det_data_elements + missing_elements))

            verification_report = self._verify(raw_text, pipeline_output)
            self._report_stage(f"feedback_loop_attempt_{attempt}", {
                "scores": verification_report.get("scores", {}),
                "reprocess_required": verification_report.get("reprocess_required", False)
            }, t0)

        # Phase 8: Schema and Data Inventory Generation
        t0 = time.time()
        logger.info("  [8] Generating Compliance Schema and Data Inventory...")
        schema_output = self.schema_agent.run(raw_text, pipeline_output)

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

        sys_list = [s["name"] if isinstance(s, dict) else s for s in normalized.get("systems", [])]
        elem_list = [e["name"] if isinstance(e, dict) else e for e in pipeline_output.get("data_elements", [])]
        enriched_systems = list(set(sys_list + schema_systems))
        enriched_elements = list(set(elem_list + schema_elements))
        self._report_stage("schema_generation", {
            "schema_generated": schema_output.get("schema") is not None,
            "inventory_rows": len(schema_output.get("inventory", []))
        }, t0)

        # Phase 9: Final DFD generation
        t0 = time.time()
        logger.info("  [9] Running DFDBuilderAgent (final) with enriched Schema context...")
        actor_names = [a["name"] if isinstance(a, dict) else a for a in normalized.get("actors", [])]

        dfd_graph = self.dfd_agent.build(
            actors=actor_names,
            systems=enriched_systems,
            data_elements=enriched_elements,
            data_flows=canonical_flows,
            risks=agent_risks,
            structured_context=structured_context
        )
        self._report_stage("dfd_generation", {
            "nodes": len(dfd_graph.get("nodes", [])),
            "edges": len(dfd_graph.get("edges", []))
        }, t0)

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
            "dialogue_records": dialogue_records,
            "verification_report": verification_report,
            "dfd_graph": dfd_graph,
            "compliance_schema": schema_output.get("schema"),
            "data_inventory": schema_output.get("inventory"),
            "normalization_report": {
                "removed_entities": normalized.get("removed", [])
            }
        }

        score = verification_report.get("scores", {}).get("overall_score", 0)
        logger.info(f"  Pipeline complete — score: {score:.2f}")
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

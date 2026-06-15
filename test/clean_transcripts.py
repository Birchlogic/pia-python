from utils.logger import setup_logger
from pathlib import Path
import re
import json
import spacy
import unicodedata

logger = setup_logger("[CLEAN TRANSCRIPTS]")


class CleanTranscripts:

    def __init__(self):

        self.logger = logger

        self.base_dir = Path(__file__).resolve().parent
        self.input_dir = self.base_dir.parent / "example_input"
        self.output_dir = self.base_dir / "example_output"
        self.output_dir.mkdir(exist_ok=True)

        self.nlp = spacy.load("en_core_web_sm")

        self.FILLERS = [
            "um", "uh", "you know", "i mean",
            "kind of", "sort of", "let me think"
        ]

        self.SYSTEMS = [
            "Salesforce",
            "Ameyo",
            "WhatsApp",
            "Email"
        ]

    # --------------------------------
    # STEP 1 — Read transcript
    # --------------------------------
    def read_transcript(self, file_path):

        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()

    # --------------------------------
    # STEP 2 — Extract metadata
    # --------------------------------
    def extract_metadata(self, text):

        metadata = {}

        project = re.search(r"Project:\s*(.*)", text)
        department = re.search(r"Department:\s*(.*)", text)
        session = re.search(r"Session:\s*(.*)", text)

        if project:
            metadata["project"] = project.group(1).strip()

        if department:
            metadata["department"] = department.group(1).strip()

        if session:
            metadata["session"] = session.group(1).strip()

        return metadata

    # --------------------------------
    # STEP 3 — Extract roles
    # --------------------------------
    def extract_roles(self, text):

        role_map = {}

        interviewer = re.search(r"Interviewer:\s*([^\(\n]+)", text)
        interviewee = re.search(r"Interviewee:\s*([^\(\n]+)", text)
        note_taker = re.search(r"Note-taker:\s*([^\(\n]+)", text)

        if interviewer:
            role_map[interviewer.group(1).strip()] = "interviewer"

        if interviewee:
            role_map[interviewee.group(1).strip()] = "interviewee"

        if note_taker:
            role_map[note_taker.group(1).strip()] = "note_taker"

        return role_map

    # --------------------------------
    # STEP 4 — Remove metadata block
    # --------------------------------
    def remove_metadata_block(self, text):

        start = re.search(r"--- TRANSCRIPT BEGINS ---", text)
        end = re.search(r"--- TRANSCRIPT ENDS ---", text)

        if start and end:
            text = text[start.end():end.start()]

        return text.strip()

    # --------------------------------
    # STEP 5 — Normalize text
    # --------------------------------
    def normalize_text(self, text):

        return unicodedata.normalize("NFKC", text)

    # --------------------------------
    # STEP 6 — Parse speaker lines
    # --------------------------------
    def parse_speakers(self, text):

        # Supports both:
        # - "[00:01] Rahul: sentence"
        # - "Rahul: sentence"
        # - "Rahul:" followed by utterance on subsequent lines until next speaker
        pattern = r"^(?:\[(.*?)\]\s*)?([A-Za-z][A-Za-z\s]{0,60}):\s*(.*)$"

        records = []
        buffer = None  # {timestamp, speaker, parts: []}

        def flush_buffer():
            nonlocal buffer
            if not buffer:
                return
            text_out = "\n".join([p for p in buffer.get("parts", []) if p is not None]).strip()
            if text_out:
                records.append({
                    "timestamp": buffer.get("timestamp", ""),
                    "speaker": buffer.get("speaker", ""),
                    "text": text_out,
                })
            buffer = None

        for raw_line in text.split("\n"):
            line = raw_line.strip()
            if not line:
                continue

            match = re.match(pattern, line)
            if match:
                # Start a new speaker turn
                flush_buffer()
                timestamp, speaker, sentence = match.groups()
                timestamp = (timestamp or "").strip()
                speaker = (speaker or "").strip()
                sentence = (sentence or "").strip()
                buffer = {"timestamp": timestamp, "speaker": speaker, "parts": []}
                if sentence:
                    buffer["parts"].append(sentence)
                continue

            # Continuation line of current speaker turn
            if buffer is not None:
                buffer["parts"].append(line)

        flush_buffer()
        return records

    # --------------------------------
    # STEP 7 — Remove fillers
    # --------------------------------
    def remove_fillers(self, text):

        cleaned = text

        for filler in self.FILLERS:

            cleaned = re.sub(
                rf"\b{filler}\b",
                "",
                cleaned,
                flags=re.IGNORECASE
            )

        cleaned = re.sub(r"\s+", " ", cleaned)

        return cleaned.strip()

    # --------------------------------
    # STEP 8 — Sentence splitting
    # --------------------------------
    def split_sentences(self, record):

        doc = self.nlp(record["text"])

        sentences = []

        for sent in doc.sents:

            text = self.normalize_text(sent.text)

            cleaned = self.remove_fillers(text)

            if cleaned:

                sentences.append({
                    "timestamp": record["timestamp"],
                    "speaker": record["speaker"],
                    "text": cleaned
                })

        return sentences

    # --------------------------------
    # STEP 9 — Assign role
    # --------------------------------
    def assign_role(self, speaker, role_map):

        for name in role_map:

            if name.lower() in speaker.lower():
                return role_map[name]

        return "unknown"

    # --------------------------------
    # STEP 10 — Detect systems
    # --------------------------------
    def detect_systems(self, text):

        found = []

        for system in self.SYSTEMS:

            if system.lower() in text.lower():
                found.append(system)

        return found

    # --------------------------------
    # STEP 11 — Merge consecutive speaker sentences
    # --------------------------------
    def merge_speaker_sentences(self, records):

        merged = []

        buffer = None

        for r in records:

            if buffer is None:
                buffer = r
                continue

            if r["speaker"] == buffer["speaker"]:

                buffer["text"] += " " + r["text"]

                buffer["systems"] = list(
                    set(buffer["systems"] + r["systems"])
                )

            else:

                merged.append(buffer)

                buffer = r

        if buffer:
            merged.append(buffer)

        return merged

    # --------------------------------
    # STEP 12 — Cleaning pipeline
    # --------------------------------
    def clean_transcript(self, file_path):

        raw = self.read_transcript(file_path)

        metadata = self.extract_metadata(raw)

        role_map = self.extract_roles(raw)

        cleaned = self.remove_metadata_block(raw)

        speaker_lines = self.parse_speakers(cleaned)

        processed = []

        for record in speaker_lines:

            sentences = self.split_sentences(record)

            for s in sentences:

                systems = self.detect_systems(s["text"])

                processed.append({
                    "timestamp": s["timestamp"],
                    "speaker": s["speaker"],
                    "role": self.assign_role(s["speaker"], role_map),
                    "text": s["text"],
                    "systems": systems
                })

        merged = self.merge_speaker_sentences(processed)

        return {
            "metadata": metadata,
            "dialogue": merged
        }

    # --------------------------------
    # STEP 13 — Save JSON
    # --------------------------------
    def save_json(self, data, output_path):

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    # --------------------------------
    # STEP 14 — Clean all transcripts
    # --------------------------------
    def clean_transcripts(self):

        self.logger.info("Cleaning transcripts...")

        for file in self.input_dir.glob("*.txt"):

            self.logger.info(f"Cleaning {file.name}...")

            cleaned_data = self.clean_transcript(file)

            output_file = self.output_dir / f"{file.stem}_clean.json"

            self.save_json(cleaned_data, output_file)

            self.logger.info(f"Saved cleaned file → {output_file}")

        self.logger.info("All transcripts cleaned successfully.")
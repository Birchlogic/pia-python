import re
import json
from pathlib import Path


class CleanFieldNotes:

    def __init__(self):
        self.base_dir = Path(__file__).resolve().parent
        self.input_dir = self.base_dir / "input_notes"
        self.output_dir = self.base_dir / "cleaned_notes"
        self.output_dir.mkdir(exist_ok=True)

    def extract_metadata(self, text):
        metadata = {}
        patterns = {
            "project": r"Project:\s*(.*)",
            "department": r"Department:\s*(.*)",
            "session": r"Session:\s*(.*)",
            "analyst": r"Analyst:\s*(.*)",
            "date": r"Date:\s*(.*)",
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, text)
            if match:
                metadata[key] = match.group(1).strip()
        return metadata

    def extract_sections(self, text):
        sections = re.split(r"==\s*(.*?)\s*==", text)
        parsed = {}
        for i in range(1, len(sections), 2):
            title = sections[i].strip()
            content = sections[i + 1].strip() if i + 1 < len(sections) else ""
            parsed[title] = content
        return parsed

    def extract_list_items(self, section_text):
        """Extract bullet/numbered list items from a section."""
        items = []
        for line in section_text.split("\n"):
            line = line.strip()
            match = re.match(r"^[-•*]\s*(.*)", line) or re.match(r"^\d+[.)]\s*(.*)", line)
            if match:
                items.append(match.group(1).strip())
        return items

    def clean_notes(self, file):
        text = file.read_text(encoding="utf-8")
        metadata = self.extract_metadata(text)
        sections = self.extract_sections(text)

        # Also extract list items per section
        structured_sections = {}
        for title, content in sections.items():
            items = self.extract_list_items(content)
            structured_sections[title] = {
                "raw": content,
                "items": items
            }

        return {
            "metadata": metadata,
            "sections": structured_sections
        }

    def run(self):
        for file in self.input_dir.glob("*.txt"):
            cleaned = self.clean_notes(file)
            out = self.output_dir / f"{file.stem}.json"
            with open(out, "w", encoding="utf-8") as f:
                json.dump(cleaned, f, indent=2)
import re


def detect_document_type(text):
    """
    Detect document type using structural patterns, not keywords.

    Returns:
        dict with 'type' ('transcript', 'field_notes', 'unknown'),
        'confidence' (float), and 'signals' (list of reasons).
    """
    signals = []
    transcript_score = 0
    field_notes_score = 0

    # --- Transcript signals ---

    # Timestamp + Speaker pattern: [HH:MM:SS] Speaker:
    ts_pattern = re.findall(r"\[\d{1,2}:\d{2}(?::\d{2})?\]\s*[A-Z][a-zA-Z\s]+:", text)
    if len(ts_pattern) >= 3:
        transcript_score += 40
        signals.append(f"Found {len(ts_pattern)} timestamp-speaker lines")

    # Dialogue-like alternation (multiple speakers)
    speakers = set(re.findall(r"\[\d{1,2}:\d{2}(?::\d{2})?\]\s*([A-Za-z\s]+):", text))
    if len(speakers) >= 2:
        transcript_score += 30
        signals.append(f"Found {len(speakers)} unique speakers")

    # High ratio of lines starting with timestamps
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    ts_lines = [l for l in lines if re.match(r"\[\d{1,2}:\d{2}", l)]
    if lines and len(ts_lines) / len(lines) > 0.3:
        transcript_score += 20
        signals.append(f"{len(ts_lines)}/{len(lines)} lines have timestamps")

    # Speaker-only transcript pattern: "Name:" optionally followed by text
    # Many real-world transcripts omit timestamps and put the utterance on the next line.
    speaker_only = re.findall(
        r"^(?!\[\d{1,2}:\d{2})([A-Z][a-zA-Z]{1,30}(?:\s+[A-Z][a-zA-Z]{1,30}){0,3}):\s*(?:.+)?$",
        text,
        re.MULTILINE,
    )
    unique_speakers = set([s.strip() for s in speaker_only if s.strip()])
    if len(unique_speakers) >= 2 and len(speaker_only) >= 6:
        transcript_score += 40
        signals.append(f"Found {len(unique_speakers)} unique speakers without timestamps")

    # --- Field notes signals ---

    # Section headers: == TITLE ==
    section_headers = re.findall(r"==\s*.+?\s*==", text)
    if len(section_headers) >= 2:
        field_notes_score += 40
        signals.append(f"Found {len(section_headers)} section headers (== ... ==)")

    # Numbered items or bullet lists
    list_items = re.findall(r"^\s*(?:[-•*]|\d+[.)]) ", text, re.MULTILINE)
    if len(list_items) >= 5:
        field_notes_score += 25
        signals.append(f"Found {len(list_items)} list items")

    # Field-value patterns: "Field: Value"
    field_patterns = re.findall(r"^[A-Z][a-zA-Z\s]+:\s+\S", text, re.MULTILINE)
    if len(field_patterns) >= 3 and len(speakers) < 2:
        field_notes_score += 20
        signals.append(f"Found {len(field_patterns)} field-value patterns")

    # --- Decide ---
    if transcript_score > field_notes_score and transcript_score >= 40:
        return {
            "type": "transcript",
            "confidence": min(transcript_score / 100, 1.0),
            "signals": signals
        }
    elif field_notes_score > transcript_score and field_notes_score >= 40:
        return {
            "type": "field_notes",
            "confidence": min(field_notes_score / 100, 1.0),
            "signals": signals
        }
    else:
        return {
            "type": "unknown",
            "confidence": 0.0,
            "signals": signals
        }

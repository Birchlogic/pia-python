import spacy

# Load model once at module level
try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    import subprocess
    subprocess.run(["python", "-m", "spacy", "download", "en_core_web_sm"], check=True)
    nlp = spacy.load("en_core_web_sm")


def extract_entities(text):
    """
    Use spaCy NER to extract actors, organizations, and products.

    Returns:
        dict with 'persons', 'organizations', 'products', 'all_entities'
    """
    doc = nlp(text)

    persons = []
    organizations = []
    products = []
    all_entities = []

    seen = set()

    for ent in doc.ents:
        key = (ent.text.strip(), ent.label_)
        if key in seen or len(ent.text.strip()) < 2:
            continue
        seen.add(key)

        entity = {
            "text": ent.text.strip(),
            "label": ent.label_,
            "start": ent.start_char,
            "end": ent.end_char
        }
        all_entities.append(entity)

        if ent.label_ == "PERSON":
            persons.append(ent.text.strip())
        elif ent.label_ in ("ORG", "GPE", "FAC"):
            organizations.append(ent.text.strip())
        elif ent.label_ in ("PRODUCT", "WORK_OF_ART"):
            products.append(ent.text.strip())

    return {
        "persons": list(set(persons)),
        "organizations": list(set(organizations)),
        "products": list(set(products)),
        "all_entities": all_entities
    }


def extract_actors_from_dialogue(dialogue):
    """
    Extract actors (speakers) from parsed dialogue records.
    Also runs NER on dialogue text to find mentioned actors.
    """
    speakers = set()
    mentioned_persons = set()

    for record in dialogue:
        speakers.add(record.get("speaker", "Unknown"))
        entities = extract_entities(record.get("text", ""))
        for p in entities["persons"]:
            mentioned_persons.add(p)

    return {
        "speakers": list(speakers),
        "mentioned_persons": list(mentioned_persons)
    }

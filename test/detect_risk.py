import re

RISK_PATTERNS = {
    "Aadhaar Exposure": r"Aadhaar.*unmasked|full Aadhaar|Aadhaar.*visible",
    "PAN Exposure": r"PAN.*visible|PAN.*image|PAN.*unmasked",
    "Cross Border Transfer": r"cross-border|outside India|international transfer",
    "No Retention Policy": r"no retention policy|keeps everything|never deleted",
    "No Access Control": r"no field-level security|all users can see|everyone has access",
    "Data Export Risk": r"export.*CSV|download.*data|bulk export",
    "Sensitive Free Text": r"free text.*sensitive|notes.*PII|comments.*personal",
    "Unmanaged Device": r"personal phone|unmanaged.*device|personal laptop",
    "No Encryption": r"not encrypted|plain text|unencrypted",
    "No Audit Trail": r"no audit|no log|not tracked|no trail",
}

RISK_KEYWORDS = ["CRITICAL", "KEY ISSUE", "OBSERVATION", "NOTE", "WARNING", "RISK", "CONCERN"]


def detect_risks(text):
    """Detect privacy risks using regex patterns."""
    risks = []
    for name, pattern in RISK_PATTERNS.items():
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        for match in matches:
            # Extract surrounding context (the sentence containing the match)
            start = max(0, text.rfind(".", 0, match.start()) + 1)
            end = text.find(".", match.end())
            if end == -1:
                end = min(len(text), match.end() + 200)
            context = text[start:end].strip()
            risks.append({
                "risk_type": name,
                "evidence": context,
                "position": match.start()
            })
    return risks


def detect_risk_statements(text):
    """Detect sentences near risk keywords like CRITICAL, KEY ISSUE, etc."""
    statements = []
    for keyword in RISK_KEYWORDS:
        for match in re.finditer(rf"\b{keyword}\b", text, re.IGNORECASE):
            start = max(0, text.rfind("\n", 0, match.start()))
            end = text.find("\n", match.end())
            if end == -1:
                end = len(text)
            line = text[start:end].strip()
            if line:
                statements.append({
                    "keyword": keyword,
                    "statement": line
                })
    return statements
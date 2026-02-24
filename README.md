# PIA — Privacy Impact Assessment Agent

> AI-powered compliance documentation engine that transforms interview transcripts into professional Privacy Data Flow Diagrams (DFDs) and assessment reports.

---

## Architecture Overview

```mermaid
graph TB
    subgraph "Input Layer"
        T["📄 Transcripts (.txt)"]
        D["📋 Example DFDs (.docx)"]
    end

    subgraph "Agent Pipeline"
        IA["IngestionAgent<br/>LLM extraction"]
        KB["KBBuilder<br/>Vector store"]
        RA["RetrievalAgent<br/>RAG context"]
        DE["DFDExtractor<br/>JSON extraction + validation loop"]
        PD["PrivacyDFDAgent<br/>Mermaid generation"]
        RG["ReportGenAgent<br/>Assessment report"]
        LL["LearningLoop<br/>Feedback"]
    end

    subgraph "Rendering"
        VL["DFDValidator<br/>0-100 scoring"]
        HR["DFDHTMLRenderer<br/>Swimlane HTML + arrows"]
    end

    subgraph "Output Layer"
        HTML["🌐 Interactive HTML DFD"]
        MD["📝 Mermaid DFD (.md)"]
        RPT["📊 Assessment Report (.md)"]
        JSON["📦 DFD JSON"]
    end

    T --> IA --> KB
    KB --> RA
    RA --> DE & PD & RG
    DE --> VL --> HR --> HTML
    DE --> JSON
    PD --> MD
    RG --> RPT
    RPT --> LL --> KB

    D --> RE["reverse_engineer_dfds.py"]
    RE --> REF["📁 Reference DFDs<br/>data/reference_dfds/"]

    style IA fill:#e3f2fd
    style DE fill:#e3f2fd
    style PD fill:#e3f2fd
    style RG fill:#e3f2fd
    style HR fill:#fff3e0
    style VL fill:#fff3e0
    style HTML fill:#e8f5e9
    style REF fill:#e8f5e9
```

---

## Pipeline Flow — Single Department Assessment

```mermaid
sequenceDiagram
    participant U as User
    participant M as main.py
    participant IG as IngestionAgent
    participant KB as KBBuilder
    participant RA as RetrievalAgent
    participant PD as PrivacyDFDAgent
    participant EX as DFDExtractor
    participant VL as DFDValidator
    participant RN as DFDHTMLRenderer
    participant RG as ReportGenAgent

    U->>M: python main.py assess --dept "X" --files t1.txt t2.txt

    rect rgb(232, 245, 233)
    Note over M,IG: Step 1 — Ingest Transcripts
    loop Each transcript file
        M->>IG: ingest_transcript(file)
        IG->>IG: LLM extracts entities, data items, processes, risks, gaps
        IG-->>M: ExtractedTranscriptData
        M->>KB: add_transcript(content, metadata)
    end
    end

    rect rgb(227, 242, 253)
    Note over M,RA: Step 2 — RAG Context
    M->>RA: retrieve_context(query)
    RA->>KB: similarity search
    RA-->>M: context string
    end

    rect rgb(255, 243, 224)
    Note over M,PD: Step 3 — Mermaid DFD
    M->>PD: generate_department_dfd(dept, data, context)
    PD-->>M: Mermaid markdown
    end

    rect rgb(252, 228, 236)
    Note over M,RN: Step 4 — HTML DFD (with validation loop)
    M->>EX: extract(dept, data, context)
    loop Up to 3 attempts
        EX->>EX: LLM generates DFD JSON
        EX->>VL: validate_dfd(json)
        VL-->>EX: score + feedback
        alt Score >= 75
            EX-->>M: DFD JSON ✓
        else Score < 75
            EX->>EX: Inject feedback, retry
        end
    end
    M->>RN: render(dfd_json)
    RN-->>M: HTML string
    end

    rect rgb(243, 229, 245)
    Note over M,RG: Step 5 — Report
    M->>RG: generate_report(data, context, metadata, dfd_md)
    RG-->>M: Assessment Report (MD)
    end

    M-->>U: 4 output files saved
```

---

## Project Structure

```
pia-python/
├── main.py                          # CLI orchestrator (assess / master)
├── config.py                        # API keys, paths, model settings
├── reverse_engineer_dfds.py         # Docx → reference DFD generator
├── preview_dfd.py                   # Standalone HTML DFD preview
│
├── agent/                           # AI agent modules
│   ├── ingestion.py                 # Transcript → structured data (LLM)
│   ├── kb_builder.py                # Vector store builder (embeddings)
│   ├── retrieval.py                 # RAG context retrieval
│   ├── privacy_dfd.py               # Mermaid DFD generation (LLM)
│   ├── dfd_extractor.py             # DFD JSON extraction (LLM + retry)
│   ├── dfd_validator.py             # DFD quality scoring (0-100)
│   ├── dfd_html_renderer.py         # Swimlane HTML + SVG arrows
│   ├── report_gen.py                # Assessment report generation (LLM)
│   └── learning.py                  # Feedback loop for KB
│
├── models/
│   └── extracted_data.py            # Pydantic data models
│
├── utils/
│   └── logger.py                    # Logging configuration
│
├── data/
│   ├── reports/                     # Generated assessment outputs
│   ├── reference_dfds/              # Pre-generated reference DFDs (16 depts)
│   └── vectors/                     # ChromaDB vector store
│
├── example_input/                   # Sample transcript files
│   ├── Session1_CC_Kickoff*.txt
│   ├── Session2_CC_IVR*.txt
│   ├── Session3_CC_Compliance*.txt
│   └── Session4_CC_Systems*.txt
│
└── example_dfds/                    # Original department docx reports
    ├── CustomerCare Department v1.1.docx
    ├── HR Department v1.2.docx
    ├── ... (17 department files)
    └── Master Assessment Report v1.1.docx
```

---

## How to Run

### Prerequisites

```bash
# 1. Python 3.11+
# 2. Install dependencies
pip install anthropic python-docx pydantic chromadb sentence-transformers

# 3. Set environment variables
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
```

### Command Reference

#### Single Department Assessment

```bash
# Full LLM-powered assessment (generates report + DFDs)
python main.py assess \
  --dept "Customer Care" \
  --files example_input/Session1*.txt example_input/Session2*.txt

# Output:
#   → data/reports/Customer_Care_Assessment_Report_YYYYMMDD.md
#   → data/reports/Customer_Care_Privacy_DFD_YYYYMMDD.md
#   → data/reports/Customer_Care_DFD_YYYYMMDD.html    ← Interactive DFD
#   → data/reports/Customer_Care_DFD_YYYYMMDD.json
```

#### Zero-Variance Mode (for demos)

```bash
# Uses pre-generated reference JSON — no LLM calls for DFD
python main.py assess \
  --dept "Customer Care" \
  --files example_input/Session1*.txt \
  --use-reference
```

#### Multi-Department + Master DFD

```bash
python main.py master \
  --depts "Customer Care" "HR" "IT" \
  --file-groups "cc1.txt,cc2.txt" "hr1.txt" "it1.txt"

# Output: individual reports + MASTER_DFD.html + MASTER_Privacy_DFD.md
```

#### Generate Reference DFDs from Example Docx

```bash
# Reverse-engineer all 17 department docx files → JSON + HTML
python reverse_engineer_dfds.py

# Output: data/reference_dfds/{dept_slug}.json + .html
```

#### Preview DFD (standalone test)

```bash
python preview_dfd.py
open data/reports/Customer_Care_DFD_preview.html
```

---

## How the Reference DFD System Works

```mermaid
flowchart LR
    subgraph "One-Time Setup"
        DOCX["📋 example_dfds/*.docx"] --> RE["reverse_engineer_dfds.py"]
        RE -->|"Table extraction<br/>(no LLM)"| JSON["📦 reference JSON"]
        RE -->|"HTML rendering"| HTML["🌐 reference HTML"]
        JSON --> DIR["data/reference_dfds/"]
        HTML --> DIR
    end

    subgraph "Demo Re-run"
        CLI["python main.py assess<br/>--use-reference"] --> LOAD["_load_reference_dfd()"]
        LOAD -->|"slug match"| DIR
        DIR -->|"JSON loaded"| RENDER["DFDHTMLRenderer"]
        RENDER --> OUT["Identical HTML output<br/>every time"]
    end

    style RE fill:#fff3e0
    style OUT fill:#e8f5e9
```

**How slug matching works:**

| User Input | Slugified | Matches File |
|-----------|-----------|-------------|
| `"Customer Care"` | `customer_care` | `customer_care_department.json` |
| `"HR"` | `hr` | `human_resources_hr_ops_ta_training_development.json` |
| `"IT"` | `it` | `information_technology_department.json` |

The lookup tries exact match first, then substring match as fallback.

---

## DFD Validation Scoring

The `DFDValidator` scores every generated DFD on a 0-100 scale:

| Criteria | Points | Requirement |
|---------|--------|-------------|
| Actor types | 20 | Must have all 3: external, internal, vendor |
| Business processes | 10 | At least 2 per actor |
| Collection sources | 15 | Each process has data elements |
| Central process | 10 | Named processing unit exists |
| Dispersal sinks | 15 | At least 2 output destinations |
| Storage systems | 10 | At least 1 storage system |
| Data flows | 15 | Inbound + outbound flows present |
| **Pass threshold** | **75** | |

If the LLM produces a score < 75, DFDExtractor **automatically injects feedback** and retries (up to 3 attempts), keeping the highest-scoring result.

---

## HTML DFD Features

- **Swimlane layout** — CSS Grid with actor rows (Customers / Internal / Vendors)
- **4 lifecycle columns** — Data Collection → Processing → Dispersal → Storage
- **SVG fanned arrows** — Cubic Bezier curves with per-color arrowhead markers
- **Flow labels** — Mid-arrow text showing data type (e.g., "Customer Data")
- **Print/PDF support** — `@page A3 landscape`, `print-color-adjust: exact`, `beforeprint` arrow redraw
- **Edit mode** — Toggle to make all labels editable in-browser
- **Improved sink boxes** — Color-coded left bar, department/vendor icons, bold names

---

## Data Models

```mermaid
classDiagram
    class ExtractedTranscriptData {
        entities: ExtractedEntity[]
        data_inventory: DataItem[]
        processes: Process[]
        risks: Risk[]
        compliance_gaps: ComplianceGap[]
    }

    class ExtractedEntity {
        name: str
        type: str
        description: str
    }

    class DataItem {
        data_type: str
        source: str
        destination: str
        protection_level: str
    }

    class Process {
        name: str
        description: str
        involved_entities: str[]
    }

    class Risk {
        title: str
        description: str
        impact: str
        likelihood: str
    }

    class ComplianceGap {
        requirement: str
        observation: str
        gap_description: str
    }

    ExtractedTranscriptData --> ExtractedEntity
    ExtractedTranscriptData --> DataItem
    ExtractedTranscriptData --> Process
    ExtractedTranscriptData --> Risk
    ExtractedTranscriptData --> ComplianceGap
```

---

## Environment Variables

| Variable | Required | Description |
|---------|----------|-------------|
| `ANTHROPIC_API_KEY` | ✅ | Claude API key for LLM calls |
| `DATABASE_URL` | ❌ | Optional database URL |

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| LLM | Claude Sonnet 4 (Anthropic) |
| Embeddings | all-MiniLM-L6-v2 (sentence-transformers) |
| Vector Store | ChromaDB |
| Data Models | Pydantic v2 |
| Docx Parsing | python-docx |
| HTML DFD | Vanilla HTML/CSS/JS + SVG |
| Config | python-dotenv |

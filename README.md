# Intent-Store — Predictive Semantic Archival Engine for Linux Storage

A Linux-native storage intelligence CLI that understands **why** a file matters — not just when it was last touched — and proactively recommends explainable archival actions. **Never auto-deletes. Always proposes, waits for accept/reject.**

---

## 🎯 Objective

To build a Linux-native storage intelligence tool that understands why a file matters — not just when it was last touched — and proactively recommends (never silently executes) archival actions, closing the gap between purely reactive cleanup tools and purely low-level storage-tuning research.

---

## 📖 Description

**Intent-Store** walks a filesystem directory, builds a lightweight semantic profile of each file (content embeddings + access recency + inferred purpose), and scores predicted future access against semantic importance.

When a file's predicted future use drops while its inferred importance stays high (e.g., a tax document opened once a year), Intent-Store surfaces a plain-language archival recommendation the user can accept, edit, or reject. Rejected/accepted decisions feed back into the importance model.

---

## 🔬 Novelty

Prior work splits into two distinct camps:
1. **LLM-Based Semantic File Systems** (e.g., *AIOS-LSFS*, ICLR 2025): Focus primarily on retrieving files by meaning.
2. **Intent-Driven Storage Tuning Frameworks** (e.g., *IDSS*): Use LLMs to adjust low-level hardware/OS configurations.

> **The Gap:** Neither approach decides which files should move to cold storage and explains *why*.
>
> **Intent-Store sits directly in that gap:** semantic understanding applied to proactive archival decisions, backed by a human-in-the-loop feedback signal, rather than either pure retrieval or pure infrastructure tuning.

---

## 💡 Key Innovations

* **Explainable Recommendations:** Delivers human-readable justifications instead of black-box deletion or silent tiering.
* **Semantic + Structural Scoring:** Combines embedding-based cosine similarity to "important document" archetypes with recency decay and recurring file-pattern detection — far beyond "file not opened in N days."
* **Human-in-the-Loop Feedback Loop:** Accept/reject decisions continuously recalibrate the importance score.
* **Offline-First:** 100% local — no data leaves the machine. Uses `sentence-transformers` for embeddings and Ollama for LLM reasoning.

---

## 🛠️ Tech Stack

| Component | Technology | Description |
| :--- | :--- | :--- |
| **Core Runtime** | Python 3.10+ | Core daemon logic and orchestration |
| **Semantic Embeddings** | `sentence-transformers` (all-MiniLM-L6-v2) | Lightweight local embedding for content signatures |
| **Local Indexing** | SQLite | Fast, embedded metadata + profile storage |
| **Reasoning Engine** | Open-Source LLM via Ollama | Offline LLM for explanations and archival justifications |
| **Fallback Reasoning** | Rule-augmented heuristics | Rich multi-signal fallback when Ollama is unavailable |
| **CLI** | Click + Rich | Interactive terminal interface with coloured tables |

---

## 🏗️ Architecture

```
scanner.py    →  SQLite (path, size, atime, mtime)
profiler.py   →  SQLite (embedding BLOB via sentence-transformers)
scorer.py     →  SQLite (importance_score = recency_decay × pattern_bonus)
reasoner.py   →  SQLite (action, justification via Ollama or fallback)
cli.py        →  User interface (scan / report / accept / reject)
```

---

## 🚀 How to Run the Demo

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. (Optional) Pull a local LLM via Ollama

```bash
# Install Ollama: https://ollama.com/download
ollama pull llama3      # or phi3, mistral, etc.
ollama serve            # starts the local API on localhost:11434
```

> **Note:** Ollama is optional. If it is not running, Intent-Store uses a rich rule-augmented fallback that still considers semantic similarity, recurring patterns, file size, and recency — not just age.

### 3. Run the full demo end-to-end

```bash
# Step 1 — Scan the demo directory (index + embed + score + reason in one command)
python3 cli.py scan demo/

# Step 2 — Seed realistic access-time overrides into the DB
#   (The profiler opens each file to read content, which resets the OS atime.
#    This script corrects the DB timestamps to simulate real-world file ages.)
python3 demo_seed.py

# Step 3 — Re-run scoring and reasoning with corrected timestamps
python3 -c "from scorer import score_all; from reasoner import reason_all; score_all(); reason_all()"

# Step 4 — View the recommendation report
python3 cli.py report

# Accept a recommendation (boosts importance score — feedback loop)
python3 cli.py accept demo/invoice_2024.txt

# Reject a recommendation (penalises score, clears recommendation)
python3 cli.py reject demo/debug_crawler_2022.log

# Show ALL files including those without recommendations
python3 cli.py report --all

# Use verbose logging to see internal pipeline steps
python3 cli.py --verbose scan demo/

# Use a custom database path
python3 cli.py --db my_custom.db scan demo/
```

> **Note on `demo_seed.py`:** This script is only needed for the demo because Linux updates a file's `atime` when it is read (which happens during the embedding step). On a live system with real user files, the scanner captures whatever the OS reports — `demo_seed.py` is not needed in production use.

### 4. (Optional) Install as a package

```bash
pip install -e .
intent-store scan demo/
python3 demo_seed.py        # see note above
intent-store report
```

### 5. Expected demo output

Running `python3 cli.py report` after a successful scan will display a table similar to:

```
╭──────────────────────────────────────────────────────────────────────────────────╮
│                        Intent-Store Recommendations                              │
├──────────────────────────┬──────┬─────────────┬───────┬──────────┬──────────────┤
│ File                     │ Size │ Last Access │ Score │ Action   │ Justification│
├──────────────────────────┼──────┼─────────────┼───────┼──────────┼──────────────┤
│ debug_crawler_2022.log   │ 1.1KB│ 1500d ago   │ 0.000 │ 📦 archive│ …           │
│ project_alpha_notes_2021 │ 820B │ 900d ago    │ 0.001 │ 📦 archive│ …           │
│ invoice_2024.txt         │ 847B │ 200d ago    │ 0.230 │ ✅ keep  │ …            │
╰──────────────────────────┴──────┴─────────────┴───────┴──────────┴──────────────╯
```

---

## 🧠 Model Type & Privacy Justification

* **Local Embeddings:** `sentence-transformers` (all-MiniLM-L6-v2)
* **Inference Engine:** Open-weight LLMs (e.g., **Llama 3**) served locally via **Ollama**

### 🔒 Privacy & Local-First Justification

Intent-Store is intentionally architected to run **100% offline** with **zero external API costs** and **no data ever leaving the host machine**. Given that the daemon interacts with private, sensitive filesystem contents and personal documents, local-first open-source model execution is a deliberate design requirement.

---

## 📁 Project Structure

```
Intent-Store/
├── scanner.py        # Directory walker → SQLite indexing
├── profiler.py       # Semantic embedding generation
├── scorer.py         # Recency decay + recurring-pattern scoring
├── reasoner.py       # LLM / fallback recommendation engine
├── cli.py            # Click CLI (scan, report, accept, reject)
├── requirements.txt  # Python dependencies
├── setup.py          # Package installation
└── demo/             # Sample files for end-to-end testing
    ├── invoice_2024.txt           # Recurring pattern (financial, stale)
    ├── invoice_2025.txt           # Recurring pattern (financial, recent)
    ├── debug_crawler_2022.log     # Stale debug log → archive candidate
    └── project_alpha_notes_2021.md # Old meeting notes → archive candidate
```

---

## 🔬 Scoring Details

The importance score for each file is computed as:

```
importance_score = recency_decay × (1 + PATTERN_BONUS × is_recurring)
```

Where:
- `recency_decay = exp(-λ × days_since_last_access)`, with λ = ln(2) / 90 (90-day half-life)
- `is_recurring` = True if the file belongs to a family of ≥2 files sharing the same date-stripped stem in the same directory (e.g. `invoice_2024.txt`, `invoice_2025.txt`)
- `PATTERN_BONUS = 0.35` — recurring files get a 35% score lift to reflect periodic importance

Files with `importance_score < 0.45` are evaluated by the reasoning engine.

---

## 🤖 Reasoning Engine

The reasoner provides rich, multi-signal justifications by considering:

1. **Semantic similarity** to "important document" archetypes (legal contracts, tax records, medical reports, invoices) via cosine similarity on the file's embedding
2. **Recency decay signal** — how stale is the file?
3. **Recurring pattern membership** — is this part of a periodic series?
4. **File size** — compression impact analysis
5. **Content preview** — first 500 chars of text files fed to the LLM

This is fundamentally different from naive "file not opened in N days" tools.

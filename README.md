# Intent-Store — Predictive Semantic Archival Engine for Linux Storage

A Linux-native storage intelligence daemon that understands **why** a file matters — not just when it was last touched — and proactively recommends explainable archival actions.

---

## 🎯 Objective

To build a Linux-native storage intelligence daemon that understands why a file matters — not just when it was last touched — and proactively recommends (never silently executes) archival actions, closing the gap between purely reactive cleanup tools and purely low-level storage-tuning research.

---

## 📖 Description

**Intent-Store** watches filesystem activity via `fanotify`/`inotify`, builds a lightweight semantic profile of each file (content signature + access recency/frequency + inferred purpose), and scores predicted future access against semantic importance.

When a file's predicted future use drops while its inferred importance stays high (e.g., a tax document opened once a year), Intent-Store surfaces a plain-language archival recommendation that the user can accept, edit, or reject. Rejected/accepted decisions feed back into the importance model, allowing the system to improve with use instead of applying static age-based rules like existing cleanup tools.

---

## 🔬 Novelty

Prior work splits into two distinct camps:
1. **LLM-Based Semantic File Systems** (e.g., *AIOS-LSFS*, ICLR 2025): Focus primarily on retrieving files by meaning.
2. **Intent-Driven Storage Tuning Frameworks** (e.g., *IDSS*): Use LLMs to adjust low-level hardware/OS configurations (caching, I/O scheduling).

> **The Gap:** Neither approach decides which files should move to cold storage and explains *why*. 
> 
> **Intent-Store sits directly in that gap:** semantic understanding applied to proactive archival decisions, backed by a human-in-the-loop feedback signal, rather than either pure retrieval or pure infrastructure tuning.

---

## 💡 Key Innovations

* **Explainable Recommendations:** Delivers human-readable justifications instead of black-box deletion or silent tiering.
* **Human-in-the-Loop Feedback Loop:** Accept/reject decisions continuously recalibrate and fine-tune the importance model over time.
* **Storage-Policy Layer Focus:** Operates at the storage-policy layer, not the retrieval layer — a genuinely underexplored slice between LSFS-style retrieval systems and IDSS-style infrastructure tuning.

---

## 🛠️ Tech Stack

| Component | Technology | Description |
| :--- | :--- | :--- |
| **Core Runtime** | Python | Core daemon logic and orchestration |
| **Filesystem Monitoring** | `fanotify` / `inotify` | Kernel event tracking via `pyinotify` / `watchdog` |
| **Semantic Embeddings** | `sentence-transformers` | Lightweight local embedding model for content signatures |
| **Local Indexing** | SQLite | Fast, embedded local metadata and profile storage |
| **Reasoning Engine** | Open-Source LLM (via Ollama) | Offline LLM for generating explanations and archival justifications |
| **Demo Interface** | CLI / Flask | Interactive command-line interface and web dashboard |

---

## 🧠 Model Type & Privacy Justification

* **Model Architecture:** Fully Open-Source Model stack
  * **Local Embeddings:** `sentence-transformers`
  * **Inference Engine:** Open-weight LLMs (e.g., **Llama 3 8B**) served locally via **Ollama**

### 🔒 Privacy & Local-First Justification
Intent-Store is intentionally architected to run **100% offline** with **zero external API costs** and **no data ever leaving the host machine**. Given that the daemon interacts with private, sensitive filesystem contents and personal documents, a local-first open-source model execution is a deliberate design requirement.

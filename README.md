# Intent-Store

Intent-Store is a Linux storage intelligence CLI prototype. It scans a directory, understands which files matter semantically (not just by recency), and recommends archival actions with a human-readable justification. 
Crucially, it never auto-deletes — it always proposes and waits for an accept/reject decision.

## Features

1.  **Semantic Profiling**: Uses `sentence-transformers` (`all-MiniLM-L6-v2`) to generate semantic embeddings of files based on their filename and content.
2.  **Smart Scoring**: Combines Recency Decay (exponential decay on last access), Recurring Pattern Bonus (detects date-suffixed file families), and Semantic Similarity (cosine similarity against a high-importance reference centroid).
3.  **LLM Reasoner**: Calls a local LLM via Ollama (`qwen2.5:0.5b`) to provide a JSON recommendation and justification for archival candidates. 
    > **Note — Ollama is optional and the fallback is an intentional resilience feature.**
    > The default model is `qwen2.5:0.5b` (~400 MB, runs on CPU-only hardware such as a Ryzen 3 / integrated GPU).
    > A hard **7-second timeout** is enforced on every call; if Ollama is unavailable, slow, or exceeds that window,
    > Intent-Store automatically activates its built-in multi-signal fallback engine — which considers semantic
    > similarity, recurring file patterns, size, and recency — and produces a justified recommendation without
    > any LLM involvement. The tool **always** completes, even with Ollama stopped.

## Setup

1.  **Install dependencies:**
    ```bash
    pip install click rich requests sentence-transformers numpy scikit-learn
    # OR using the setup.py
    pip install -e .
    ```
2.  **Ensure Ollama is running (Optional):**
    ```bash
    # Have Ollama running locally with the qwen2.5:0.5b model pulled
    ollama run qwen2.5:0.5b
    ```

## How to run the demo

We have provided a set of sample files in the `demo/` directory.

1.  **Scan the directory:**
    ```bash
    python3 cli.py scan demo/
    ```
    *Note: The first time this runs, it may download the sentence-transformers model from HuggingFace if it's not cached. Internet access is required for the first run.*

2.  **Seed realistic timestamps:**
    By default, all demo files were just created. To simulate realistic aging (e.g., files that haven't been accessed in years), run the seeder:
    ```bash
    python3 demo_seed.py
    ```

3.  **Rescore files:**
    Since the timestamps changed, re-run scoring and reasoning:
    ```bash
    python3 cli.py rescore
    ```

4.  **View recommendations:**
    ```bash
    python3 cli.py report
    ```

5.  **Accept or Reject recommendations:**
    ```bash
    python3 cli.py accept demo/invoice_2024.txt
    python3 cli.py reject demo/debug_crawler_2022.log
    ```

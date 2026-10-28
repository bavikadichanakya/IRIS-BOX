# Heretic Directional Ablation & Model Integration Guide for IRIS-BOX

This guide explains how to abliterate (decensor) models using [**Heretic**](https://github.com/p-e-w/heretic), fine-tune with QLoRA on Google Colab, convert to **`Q4_K_M` GGUF format**, and register checkpoints into **Ollama** and **llama.cpp** for IRIS-BOX.

---

## 1. Dual-Model Architecture Overview

IRIS-BOX implements a specialized two-model routing architecture:
- **Primary Ambient/Conversational Model**: Low-latency model (e.g. `Qwen 3.5 0.8B`, `Qwen 2.5 7B`, or `heretic-iris`) dedicated to conversational queries, smart home ambient interactions, and real-time streaming speech.
- **Universal Computer Operator Model (`IRIS-Qwen3-4B-Operator`)**: Fine-tuned on `Qwen/Qwen3-4B-Instruct-2507` (non-thinking 4B, 256K context) dedicated to high-fidelity structured JSON tool calls, multi-turn application workflows, compound action chaining, and multi-device routing (`laptop1`, `laptop2`).

---

## 2. Master Training Pipeline in Google Colab

The complete, end-to-end training pipeline is preconfigured in:
- **Notebook**: [`scripts/train_iris_uncensored_master.ipynb`](../scripts/train_iris_uncensored_master.ipynb)
- **Standalone Script**: [`scripts/train_iris_uncensored_master.py`](../scripts/train_iris_uncensored_master.py)

### Execution Steps:
1. Open [Google Colab](https://colab.research.google.com/).
2. Upload `scripts/train_iris_uncensored_master.ipynb`.
3. Set runtime to GPU: **Runtime → Change runtime type → T4 GPU** (or A100 / L4).
4. Run all cells (**Runtime → Run all**).

The master pipeline executes 5 stages:
1. **Stage 1: Heretic Directional Ablation**: Optimizes refusal vector stripping via Optuna across 20 trials with `quantization="bnb_4bit"`. Fails closed if abliteration is unsuccessful (unless `ALLOW_UNTRAINED_BASE=1` is explicitly set).
2. **Stage 2: Universal Operator Dataset**: Generates 220+ compound, multi-turn, and device-routed training examples.
3. **Stage 3: 4-Bit QLoRA Fine-Tuning**: Efficient PEFT SFT using Hugging Face `transformers` + `bitsandbytes` (~4.2 GB VRAM on T4).
4. **Stage 4: Validation Benchmark Gate**: Strict schema and JSON validation across 8 multi-turn tasks. Scores syntax accuracy, tool selection fidelity, and device routing independently.
5. **Stage 5: LoRA Merge & GGUF Export**: Merges adapter weights and quantizes to `Q4_K_M` (~2.5 GB). If quantizer binary is missing, falls back to direct `Q8_0` with true `.Q8_0.gguf` naming and outputs `model_manifest.json` containing the SHA-256 hash.

---

## 3. Registering the Operator Model in Ollama

Once `IRIS-Qwen3-4B-Operator.Q4_K_M.gguf` (or `Q8_0`) is downloaded:

1. Copy the GGUF file to your `models/` directory:
   ```powershell
   Copy-Item -Path "$HOME\Downloads\IRIS-Qwen3-4B-Operator.Q4_K_M.gguf" -Destination "models\"
   ```

2. Register the operator model in Ollama using [`models/Modelfile.iris_qwen3_4b_operator`](../models/Modelfile.iris_qwen3_4b_operator):
   ```powershell
   cd models
   ollama create iris-qwen3-4b-operator -f Modelfile.iris_qwen3_4b_operator
   ```

3. Update your `.env` configuration:
   ```env
   IRIS_LLM_MODEL=heretic-iris:latest
   IRIS_OPERATOR_MODEL=iris-qwen3-4b-operator
   IRIS_FALLBACK_MODEL=qwen2.5:7b-instruct
   ```

4. Verify with the test suite:
   ```powershell
   uv run pytest tests/test_orchestrator.py -v
   ```

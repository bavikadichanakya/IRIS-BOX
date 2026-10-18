#!/bin/bash
# ==============================================================================
# Project IRIS: Heretic 7B Model Abliteration & GGUF Pipeline
# Runs on Linux GPU VM (RunPod, Lambda, Vast.ai, Colab Terminal)
# ==============================================================================

set -e

MODEL_ID=${1:-"Qwen/Qwen2.5-Coder-7B-Instruct"}
OUTPUT_DIR=${2:-"./heretic_7b_output"}
N_TRIALS=${3:-35}
QUANTIZATION=${4:-"bnb_4bit"}

echo "=== 1. Checking GPU Environment ==="
nvidia-smi

echo "=== 2. Installing Heretic & Dependencies ==="
pip install -U heretic-llm bitsandbytes accelerate optuna transformers huggingface_hub peft gguf sentencepiece

echo "=== 3. Running Heretic Optimization on 7B Model ==="
echo "Target Model: $MODEL_ID"
echo "Output Directory: $OUTPUT_DIR"
echo "Trials: $N_TRIALS"

heretic \
    --model "$MODEL_ID" \
    --quantization "$QUANTIZATION" \
    --n-trials "$N_TRIALS" \
    --export-strategy merge \
    --export-path "$OUTPUT_DIR"

echo "=== 4. Converting 7B Model to GGUF (Q4_K_M) ==="
if [ ! -d "llama.cpp" ]; then
    git clone --depth 1 https://github.com/ggerganov/llama.cpp.git
fi
cd llama.cpp
make -j llama-quantize || cmake -B build && cmake --build build --config Release -t llama-quantize
pip install -r requirements.txt

GGUF_F16="../iris-qwen2.5-coder-7b-heretic.f16.gguf"
GGUF_FINAL="../iris-qwen2.5-coder-7b-heretic.Q4_K_M.gguf"

python3 convert_hf_to_gguf.py "../$OUTPUT_DIR" --outfile "$GGUF_F16" --outtype f16

if [ -f "./build/bin/llama-quantize" ]; then
    ./build/bin/llama-quantize "$GGUF_F16" "$GGUF_FINAL" Q4_K_M
elif [ -f "./llama-quantize" ]; then
    ./llama-quantize "$GGUF_F16" "$GGUF_FINAL" Q4_K_M
else
    python3 convert_hf_to_gguf.py "../$OUTPUT_DIR" --outfile "$GGUF_FINAL" --outtype q8_0
fi

echo "=== 5. Pipeline Finished Successfully ==="
echo "Final 7B GGUF File created at: $GGUF_FINAL"

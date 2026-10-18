# Heretic 7B Abliteration & Model Integration Guide for IRIS

This guide explains how to abliterate (decensor) the **Qwen 2.5 Coder 7B** model using [**Heretic**](https://github.com/p-e-w/heretic) on Google Colab, convert it to **`Q4_K_M` GGUF format**, and import it into **Ollama** for Project IRIS.

---

## 1. Why Qwen 2.5 Coder 7B?
- **Superior Code & Tool Execution**: 7B models have much stronger instruction following and schema validation for IRIS's smart home, shell, and browser tool registries.
- **Zero False Refusals**: Heretic removes the refusal direction while preserving 7B's deep reasoning.
- **Fits 8GB RAM in `Q4_K_M`**: By quantizing to 4-bit (`Q4_K_M`), the model weights only occupy **~4.4 GB**, enabling local CPU execution without running out of memory.

---

## 2. Running in Google Colab (Step-by-Step)

The preconfigured notebook is located at: [run_heretic_colab.ipynb](file:///c:/Users/bavik/iris-backend/scripts/run_heretic_colab.ipynb).

1. Go to [Google Colab](https://colab.research.google.com/).
2. Click **Upload** and upload `scripts/run_heretic_colab.ipynb` from your project folder.
3. Switch runtime to GPU:
   - Go to **Runtime → Change runtime type**.
   - Select **T4 GPU** (free tier) or **A100 / L4** (Colab Pro).
   - Click **Save**.
4. Run all cells (**Runtime → Run all**).

The notebook will:
1. Verify the CUDA GPU.
2. Install `heretic-llm`, `bitsandbytes`, `transformers`, and `optuna`.
3. Run Heretic on `Qwen/Qwen2.5-Coder-7B-Instruct` with `quantization="bnb_4bit"`.
4. Merge and export the abliterated weights into safetensors.
5. Compile `llama.cpp` and quantize directly to **`iris-qwen2.5-coder-7b-heretic.Q4_K_M.gguf`** (~4.4 GB).
6. Save the file to your Google Drive or initiate a direct browser download.

---

## 3. Importing the 7B Model into Ollama for IRIS

Once `iris-qwen2.5-coder-7b-heretic.Q4_K_M.gguf` is downloaded:

1. Move the GGUF file to your `iris-backend/models/` folder:
   ```powershell
   Move-Item -Path "$HOME\Downloads\iris-qwen2.5-coder-7b-heretic.Q4_K_M.gguf" -Destination "c:\Users\bavik\iris-backend\models\"
   ```

2. Register the 7B model in Ollama using [Modelfile.heretic_iris](file:///c:/Users/bavik/iris-backend/models/Modelfile.heretic_iris):
   ```powershell
   cd c:\Users\bavik\iris-backend\models
   ollama create iris-qwen-7b-heretic -f Modelfile.heretic_iris
   ```

3. Update your [`.env`](file:///c:/Users/bavik/iris-backend/.env) file:
   ```env
   OPENAI_MODEL=iris-qwen-7b-heretic
   IRIS_LLM_MODEL=iris-qwen-7b-heretic
   ```

4. Verify your IRIS test suite:
   ```powershell
   uv run --python 3.12 pytest tests/test_permissions.py -v
   ```

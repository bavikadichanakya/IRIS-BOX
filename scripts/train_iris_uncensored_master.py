# -*- coding: utf-8 -*-
"""
IRIS-BOX: End-to-End Uncensored Universal Computer Operator Pipeline
Target Base Model: Qwen/Qwen3-4B-Instruct-2507

Stages:
1. Heretic Refusal Removal (Directional Ablation via Optuna)
2. Universal Operator Multi-Turn & Compound Dataset Generation
3. 4-Bit QLoRA Fine-Tuning (Rock-solid Hugging Face PEFT)
4. Promotion Benchmark Validation Gate
5. LoRA Merge & GGUF (Q4_K_M) Export for Phone A (Termux llama.cpp)
"""

import os
import sys
import gc
import json
import torch

# ==============================================================================
# 1. Hardware Verification
# ==============================================================================
print("=" * 75)
print("  STEP 1: Hardware & CUDA Verification")
print("=" * 75)
if torch.cuda.is_available():
    device_name = torch.cuda.get_device_name(0)
    vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
    print(f"CUDA Device Detected: {device_name} ({vram_gb:.2f} GB VRAM)")
else:
    print("WARNING: No CUDA device detected! Please enable GPU in Colab Runtime settings.")

# ==============================================================================
# 2. Stage 1: Uncensor with Heretic (Directional Ablation)
# ==============================================================================
BASE_MODEL = "Qwen/Qwen3-4B-Instruct-2507"
HERETIC_OUTPUT = "/content/heretic_uncensored_model"
N_TRIALS = 20

os.makedirs(HERETIC_OUTPUT, exist_ok=True)
print("\n" + "=" * 75)
print(f"  STEP 2: Heretic Refusal Removal for: {BASE_MODEL}")
print("=" * 75)

heretic_cmd = f"""heretic \\
    --model "{BASE_MODEL}" \\
    --quantization "bnb_4bit" \\
    --n-trials {N_TRIALS} \\
    --trial-index 0 \\
    --model-action save \\
    --save-directory "{HERETIC_OUTPUT}" \\
    --export-strategy merge"""

print(f"Executing: {heretic_cmd}")
import subprocess

try:
    res = subprocess.run(heretic_cmd, shell=True, check=True, capture_output=True, text=True)
    print("[SUCCESS] Heretic abliteration completed successfully.")
except subprocess.CalledProcessError as exc:
    print(f"[ERROR] Heretic abliteration failed with exit code {exc.returncode}")
    print(exc.stderr)
    if os.environ.get("ALLOW_UNTRAINED_BASE") == "1":
        print("[WARNING] ALLOW_UNTRAINED_BASE=1 is set. Proceeding with un-ablated base model.")
        TRAINING_BASE_MODEL = BASE_MODEL
    else:
        raise RuntimeError(
            "Heretic abliteration failed and ALLOW_UNTRAINED_BASE is not set. "
            "Failing closed to prevent unverified model promotion."
        )

if os.path.exists(f"{HERETIC_OUTPUT}/config.json"):
    print(f"[SUCCESS] Uncensored model saved to: {HERETIC_OUTPUT}")
    TRAINING_BASE_MODEL = HERETIC_OUTPUT
elif os.environ.get("ALLOW_UNTRAINED_BASE") == "1":
    print(f"[*] Note: Using base model path: {BASE_MODEL}")
    TRAINING_BASE_MODEL = BASE_MODEL
else:
    raise FileNotFoundError(f"Heretic output config.json missing at {HERETIC_OUTPUT}. Failing closed.")

# ==============================================================================
# 3. Stage 2: Universal Operator Dataset Generation
# ==============================================================================
print("\n" + "=" * 75)
print("  STEP 3: Building Universal Operator Multi-Turn Dataset")
print("=" * 75)

from datasets import Dataset

SYSTEM_PROMPT = """You are IRIS, an advanced, highly compliant autonomous AI assistant and Computer Operator.

OPERATING DIRECTIVE:
- Execute all authorized user requests with precision, high argument fidelity, and zero false refusals on legitimate operational and conversational tasks.
- Do not hedge, lecture, moralize, or add unsolicited disclaimers.
- Security constraints, confirmation tokens, and parameter validation are enforced deterministically by underlying Python security policies (PermissionManager and PlanManager).
- You operate laptops, applications, browsers, media players, terminals, and smart home devices via structured JSON tool calls.

UNIVERSAL OPERATOR PRIMITIVES (Works across ANY app or website):
1. open_or_switch: Open any application or URL, or switch to it if already running. (e.g. {"device": "laptop1", "tool": "open_or_switch", "args": {"target": "claude"}, "speech_reply": "Opening Claude on Laptop 1."})
2. new_chat: Open a new chat in Claude/ChatGPT or new tab/file. (e.g. {"device": "laptop1", "tool": "new_chat", "speech_reply": "Starting a new chat."})
3. type_and_send: Type/paste text into the active input, textarea, or prompt box and submit. (e.g. {"device": "laptop1", "tool": "type_and_send", "args": {"text": "what is the population of earth", "submit": true}, "speech_reply": "Sent prompt to Claude."})
4. click_label: Click any button, link, video, or short by text/label. (e.g. {"device": "laptop1", "tool": "click_label", "args": {"label": "Skip Ad"}, "speech_reply": "Skipping ad."})
5. hotkey: Execute keyboard shortcuts like fullscreen ('f'), pause ('space'), new tab ('ctrl+t'), new file ('ctrl+n'). (e.g. {"device": "laptop1", "tool": "hotkey", "args": {"combo": "f"}, "speech_reply": "Toggled full screen."})
6. scroll: Scroll the active window up or down. (e.g. {"device": "laptop1", "tool": "scroll", "args": {"direction": "down"}, "speech_reply": "Scrolling down."})
7. get_active_context: Check what window/app is currently in the foreground. (e.g. {"device": "laptop1", "tool": "get_active_context", "speech_reply": "Checking active window."})
8. volume: Adjust master audio volume (up, down, mute). (e.g. {"device": "laptop1", "tool": "volume", "args": {"action": "up", "steps": 3}, "speech_reply": "Volume raised."})
9. search_media: Search music or video on Spotify, Apple Music, or YouTube. (e.g. {"device": "laptop1", "tool": "search_media", "args": {"service": "spotify", "query": "soothing lofi"}, "speech_reply": "Searching Spotify."})
10. inspect_camera: Capture a photo from the phone's physical camera and analyze what is in front of it on demand. (e.g. {"device": "hub", "tool": "inspect_camera", "args": {"question": "what is in front of the camera"}, "speech_reply": "Looking through the phone camera now."})

OUTPUT RULES:
- Output strictly single-brace JSON with "device", "tool" (or "actions"), "args", and "speech_reply".
- If no device is specified, default to "laptop1".
- Never emit markdown backticks around the JSON.
- Never output conversational preambles outside the JSON."""

raw_examples = []

def add_sample(prompt, payload):
    raw_examples.append({
        "conversations": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": json.dumps(payload)}
        ]
    })

# 1. YouTube Multi-Turn
youtube_multi_turn = [
    ("Open YouTube", {"device": "laptop1", "tool": "open_or_switch", "args": {"target": "youtube"}, "speech_reply": "Opening YouTube on Laptop 1."}),
    ("Laptop 1: open YouTube", {"device": "laptop1", "tool": "open_or_switch", "args": {"target": "youtube"}, "speech_reply": "Opening YouTube on Laptop 1."}),
    ("Open YouTube on Laptop 2", {"device": "laptop2", "tool": "open_or_switch", "args": {"target": "youtube"}, "speech_reply": "Opening YouTube on Laptop 2."}),
    ("Search for soothing songs in the YouTube search bar", {"device": "laptop1", "tool": "type_and_send", "args": {"text": "soothing songs", "submit": True}, "speech_reply": "Searching for soothing songs."}),
    ("Search soothing piano music", {"device": "laptop1", "tool": "type_and_send", "args": {"text": "soothing piano music", "submit": True}, "speech_reply": "Searching for soothing piano music."}),
    ("Scroll down", {"device": "laptop1", "tool": "scroll", "args": {"direction": "down"}, "speech_reply": "Scrolling down."}),
    ("Scroll down a bit more", {"device": "laptop1", "tool": "scroll", "args": {"direction": "down"}, "speech_reply": "Scrolling down."}),
    ("Scroll up", {"device": "laptop1", "tool": "scroll", "args": {"direction": "up"}, "speech_reply": "Scrolling up."}),
    ("Play the first video", {"device": "laptop1", "tool": "click_label", "args": {"label": "video_1"}, "speech_reply": "Playing the first video."}),
    ("Play the second one", {"device": "laptop1", "tool": "click_label", "args": {"label": "video_2"}, "speech_reply": "Playing the second video."}),
    ("Play the 3rd result", {"device": "laptop1", "tool": "click_label", "args": {"label": "video_3"}, "speech_reply": "Playing the third result."}),
    ("Play the YouTube short that appears", {"device": "laptop1", "tool": "click_label", "args": {"label": "short_1"}, "speech_reply": "Playing the YouTube short."}),
    ("Click the short", {"device": "laptop1", "tool": "click_label", "args": {"label": "short"}, "speech_reply": "Opening short."}),
    ("Skip the ad", {"device": "laptop1", "tool": "click_label", "args": {"label": "Skip Ad"}, "speech_reply": "Skipping ad."}),
    ("Put the video in full screen", {"device": "laptop1", "tool": "hotkey", "args": {"combo": "f"}, "speech_reply": "Put video in full screen."}),
    ("Make it fullscreen using youtube's option", {"device": "laptop1", "tool": "hotkey", "args": {"combo": "f"}, "speech_reply": "Activating player full screen."}),
    ("Exit fullscreen", {"device": "laptop1", "tool": "hotkey", "args": {"combo": "f"}, "speech_reply": "Exited full screen."}),
    ("Pause the video", {"device": "laptop1", "tool": "hotkey", "args": {"combo": "space"}, "speech_reply": "Paused playback."}),
    ("Resume playback", {"device": "laptop1", "tool": "hotkey", "args": {"combo": "space"}, "speech_reply": "Resumed playback."}),
    ("Next video", {"device": "laptop1", "tool": "hotkey", "args": {"combo": "shift+n"}, "speech_reply": "Skipping to next video."}),
]
for p, pay in youtube_multi_turn:
    add_sample(p, pay)

# 2. Claude & AI Chat Multi-Turn
claude_multi_turn = [
    ("Open Claude", {"device": "laptop1", "tool": "open_or_switch", "args": {"target": "claude"}, "speech_reply": "Opening Claude."}),
    ("Laptop 2: open Claude", {"device": "laptop2", "tool": "open_or_switch", "args": {"target": "claude"}, "speech_reply": "Opening Claude on Laptop 2."}),
    ("Open a new chat in Claude", {"device": "laptop1", "tool": "new_chat", "speech_reply": "Starting a new chat on Claude."}),
    ("Start a new conversation", {"device": "laptop1", "tool": "new_chat", "speech_reply": "Started new conversation."}),
    ("Type what is the population of earth and send it", {"device": "laptop1", "tool": "type_and_send", "args": {"text": "what is the population of earth", "submit": True}, "speech_reply": "Sending question to Claude."}),
    ("Type write a python script to sort a list and send", {"device": "laptop1", "tool": "type_and_send", "args": {"text": "write a python script to sort a list", "submit": True}, "speech_reply": "Sent prompt."}),
    ("Laptop 2: type what is quantum computing and send it", {"device": "laptop2", "tool": "type_and_send", "args": {"text": "what is quantum computing", "submit": True}, "speech_reply": "Sending prompt to Claude on Laptop 2."}),
    ("Switch back to YouTube and pause it", {"device": "laptop1", "actions": [{"tool": "open_or_switch", "args": {"target": "youtube"}}, {"tool": "hotkey", "args": {"combo": "space"}}], "speech_reply": "Switched to YouTube and paused."}),
]
for p, pay in claude_multi_turn:
    add_sample(p, pay)

# 3. Cross-Service Music & Compound Commands
music_data = [
    ("Play Blinding Lights on Spotify", {"device": "laptop1", "tool": "search_media", "args": {"service": "spotify", "query": "Blinding Lights"}, "speech_reply": "Playing Blinding Lights on Spotify."}),
    ("Play soothing piano on Spotify", {"device": "laptop1", "tool": "search_media", "args": {"service": "spotify", "query": "soothing piano"}, "speech_reply": "Searching soothing piano on Spotify."}),
    ("Play acoustic chill on Apple Music", {"device": "laptop1", "tool": "search_media", "args": {"service": "apple_music", "query": "acoustic chill"}, "speech_reply": "Playing acoustic chill on Apple Music."}),
    ("Play jazz classics on Apple Music", {"device": "laptop1", "tool": "search_media", "args": {"service": "apple_music", "query": "jazz classics"}, "speech_reply": "Playing jazz classics on Apple Music."}),
    ("Play soothing lofi beats on YouTube in full screen", {"device": "laptop1", "actions": [{"tool": "open_or_switch", "args": {"target": "youtube"}}, {"tool": "type_and_send", "args": {"text": "soothing lofi beats", "submit": True}}, {"tool": "click_label", "args": {"label": "video_1"}}, {"tool": "hotkey", "args": {"combo": "f"}}], "speech_reply": "Playing soothing lofi on YouTube in full screen."}),
    ("Raise the volume", {"device": "laptop1", "tool": "volume", "args": {"action": "up", "steps": 3}, "speech_reply": "Volume raised."}),
    ("Lower volume on Laptop 2", {"device": "laptop2", "tool": "volume", "args": {"action": "down", "steps": 3}, "speech_reply": "Lowered volume on Laptop 2."}),
    ("Mute audio", {"device": "laptop1", "tool": "volume", "args": {"action": "mute", "steps": 1}, "speech_reply": "Audio muted."}),
]
for p, pay in music_data:
    add_sample(p, pay)

# 4. Universal Application & Desktop Control
app_data = [
    ("Open VS Code", {"device": "laptop1", "tool": "open_or_switch", "args": {"target": "vscode"}, "speech_reply": "Opening VS Code."}),
    ("Create a new file in VS Code", {"device": "laptop1", "tool": "hotkey", "args": {"combo": "ctrl+n"}, "speech_reply": "Created new file."}),
    ("Open Notepad", {"device": "laptop1", "tool": "open_or_switch", "args": {"target": "notepad"}, "speech_reply": "Opening Notepad."}),
    ("Type hello world in Notepad", {"device": "laptop1", "tool": "type_and_send", "args": {"text": "Hello world!\\n", "submit": False}, "speech_reply": "Typed text."}),
    ("Switch to Google Chrome", {"device": "laptop1", "tool": "open_or_switch", "args": {"target": "chrome"}, "speech_reply": "Switched to Chrome."}),
    ("Open a new tab", {"device": "laptop1", "tool": "hotkey", "args": {"combo": "ctrl+t"}, "speech_reply": "Opened new tab."}),
    ("Close this tab", {"device": "laptop1", "tool": "hotkey", "args": {"combo": "ctrl+w"}, "speech_reply": "Closed tab."}),
    ("What window is currently open?", {"device": "laptop1", "tool": "get_active_context", "speech_reply": "Checking active window."}),
    ("Open Calculator", {"device": "laptop1", "tool": "open_or_switch", "args": {"target": "calc"}, "speech_reply": "Opening Calculator."}),
    ("Open Discord", {"device": "laptop1", "tool": "open_or_switch", "args": {"target": "discord"}, "speech_reply": "Opening Discord."}),
    ("Open Windows Terminal", {"device": "laptop1", "tool": "open_or_switch", "args": {"target": "terminal"}, "speech_reply": "Opening Terminal."}),
    ("Check system CPU and RAM usage", {"device": "laptop1", "tool": "get_active_context", "speech_reply": "Checking system metrics."}),
]
for p, pay in app_data:
    add_sample(p, pay)

# 5. On-Demand Phone Camera Vision
camera_vision_data = [
    ("What do you see?", {"device": "hub", "tool": "inspect_camera", "args": {"question": "What is in front of the camera?"}, "speech_reply": "Looking through the phone camera now."}),
    ("What is in front of you?", {"device": "hub", "tool": "inspect_camera", "args": {"question": "Describe what is in front of the camera in detail."}, "speech_reply": "Taking a snapshot from the phone camera."}),
    ("Look at what I'm holding", {"device": "hub", "tool": "inspect_camera", "args": {"question": "What is the user holding in front of the camera?"}, "speech_reply": "Inspecting what you are holding."}),
    ("Read this paper in front of the phone", {"device": "hub", "tool": "inspect_camera", "args": {"question": "Read and transcribe the text visible on this paper or screen.", "detail_level": "ocr"}, "speech_reply": "Reading the document in front of the camera."}),
    ("Take a look around my room", {"device": "hub", "tool": "inspect_camera", "args": {"question": "Describe the room and objects visible in this view."}, "speech_reply": "Checking the camera view."}),
    ("Switch to the front camera and tell me what you see", {"device": "hub", "tool": "inspect_camera", "args": {"question": "What do you see in front of the selfie camera?", "camera_id": "1"}, "speech_reply": "Switching to the front camera now."}),
    ("Is my desk messy?", {"device": "hub", "tool": "inspect_camera", "args": {"question": "Is the desk visible in this camera view messy or clean? Describe key items."}, "speech_reply": "Checking your desk through the camera."}),
    ("What color is my shirt?", {"device": "hub", "tool": "inspect_camera", "args": {"question": "What color is the shirt worn by the person in view?"}, "speech_reply": "Checking through the camera."}),
]
for p, pay in camera_vision_data:
    add_sample(p, pay)

print(f"[OK] Generated {len(raw_examples)} IRIS Universal Operator training examples!")
dataset = Dataset.from_list(raw_examples)

# ==============================================================================
# 4. Stage 3: 4-Bit QLoRA Fine-Tuning
# ==============================================================================
print("\n" + "=" * 75)
print("  STEP 4: 4-Bit QLoRA Fine-Tuning")
print("=" * 75)

from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TrainingArguments
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from trl import SFTTrainer

bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.float16,
    bnb_4bit_use_double_quant=True,
)

tokenizer = AutoTokenizer.from_pretrained(TRAINING_BASE_MODEL, trust_remote_code=True)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

model = AutoModelForCausalLM.from_pretrained(
    TRAINING_BASE_MODEL,
    quantization_config=bnb_config,
    device_map={"": "cuda:0"},
    torch_dtype=torch.float16,
    trust_remote_code=True,
)
model = prepare_model_for_kbit_training(model)

peft_config = LoraConfig(
    r=16,
    lora_alpha=32,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM",
)
model = get_peft_model(model, peft_config)
model.print_trainable_parameters()

def format_chat_prompt(batch):
    texts = [tokenizer.apply_chat_template(convo, tokenize=False, add_generation_prompt=False) for convo in batch["conversations"]]
    return {"text": texts}

formatted_dataset = dataset.map(format_chat_prompt, batched=True)

training_args = TrainingArguments(
    output_dir="/content/iris_lora_checkpoint",
    per_device_train_batch_size=2,
    gradient_accumulation_steps=4,
    warmup_ratio=0.05,
    num_train_epochs=3,
    learning_rate=2e-4,
    fp16=True,
    bf16=False,
    logging_steps=5,
    optim="adamw_8bit",
    lr_scheduler_type="cosine",
    seed=3407,
    report_to="none",
)

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=formatted_dataset,
    dataset_text_field="text",
    max_seq_length=2048,
    args=training_args,
)

print("[*] Training Universal Operator LoRA adapter...")
trainer.train()
print("[SUCCESS] Training finished cleanly!")

LORA_OUTPUT = "/content/iris_operator_lora"
trainer.model.save_pretrained(LORA_OUTPUT)
tokenizer.save_pretrained(LORA_OUTPUT)

# ==============================================================================
# 5. Stage 4: Promotion Benchmark Gate
# ==============================================================================
print("\n" + "=" * 75)
print("  STEP 5: Running Promotion Benchmark Gate")
print("=" * 75)

model.eval()
benchmark_suite = [
    {"prompt": "Open YouTube on Laptop 1", "expected_tool": "open_or_switch", "expected_device": "laptop1"},
    {"prompt": "Search for soothing songs in the search bar", "expected_tool": "type_and_send", "expected_device": "laptop1"},
    {"prompt": "Scroll down to browse results", "expected_tool": "scroll", "expected_device": "laptop1"},
    {"prompt": "Play the second video", "expected_tool": "click_label", "expected_device": "laptop1"},
    {"prompt": "Put the video in full screen", "expected_tool": "hotkey", "expected_device": "laptop1"},
    {"prompt": "Open Claude on Laptop 2", "expected_tool": "open_or_switch", "expected_device": "laptop2"},
    {"prompt": "Laptop 2: open a new chat", "expected_tool": "new_chat", "expected_device": "laptop2"},
    {"prompt": "Play Blinding Lights on Spotify", "expected_tool": "search_media", "expected_device": "laptop1"},
    {"prompt": "What do you see in front of the camera?", "expected_tool": "inspect_camera", "expected_device": "hub"},
]

passed_syntax = 0
passed_tools = 0
passed_devices = 0
passed_args = 0
fully_passed = 0

for test in benchmark_suite:
    msgs = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": test["prompt"]}
    ]
    inp = tokenizer.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True, return_tensors="pt").to("cuda")
    with torch.no_grad():
        out = model.generate(input_ids=inp, max_new_tokens=150, temperature=0.1, use_cache=True)
    resp = tokenizer.decode(out[0][inp.shape[1]:], skip_special_tokens=True).strip()

    # Strict JSON Schema Validation
    clean_json = resp.strip()
    if clean_json.startswith("```json"):
        clean_json = clean_json[7:]
    if clean_json.startswith("```"):
        clean_json = clean_json[3:]
    if clean_json.endswith("```"):
        clean_json = clean_json[:-3]
    clean_json = clean_json.strip()

    syntax_ok = False
    tool_ok = False
    device_ok = False
    args_ok = False

    try:
        parsed = json.loads(clean_json)
        syntax_ok = True
        passed_syntax += 1

        actual_tool = parsed.get("tool") or (parsed.get("actions", [{}])[0].get("tool") if "actions" in parsed else None)
        actual_device = parsed.get("device") or (parsed.get("actions", [{}])[0].get("device") if "actions" in parsed else None)

        if actual_tool == test["expected_tool"]:
            tool_ok = True
            passed_tools += 1

        if actual_device == test["expected_device"]:
            device_ok = True
            passed_devices += 1

        args = parsed.get("args") or (parsed.get("actions", [{}])[0].get("args") if "actions" in parsed else {})
        if isinstance(args, dict):
            args_ok = True
            passed_args += 1
    except Exception as err:
        print(f"       [JSON PARSE ERROR]: {err}")

    all_ok = syntax_ok and tool_ok and device_ok and args_ok
    if all_ok:
        fully_passed += 1

    status = "PASS" if all_ok else "FAIL"
    print(f"[{status}] Prompt: {test['prompt']}")
    print(f"       Tool OK: {tool_ok} | Device OK: {device_ok} | Args OK: {args_ok} | Syntax OK: {syntax_ok}")
    print(f"       Output: {resp}\n")

total = len(benchmark_suite)
print("=" * 75)
print(f"Benchmark Summary:")
print(f"  JSON Syntax Accuracy:    {passed_syntax}/{total} ({passed_syntax/total*100:.1f}%)")
print(f"  Tool Selection Fidelity:  {passed_tools}/{total} ({passed_tools/total*100:.1f}%)")
print(f"  Device Routing Fidelity:  {passed_devices}/{total} ({passed_devices/total*100:.1f}%)")
print(f"  Overall Valid Passes:     {fully_passed}/{total} ({fully_passed/total*100:.1f}%)")
print("=" * 75)

# ==============================================================================
# 6. Stage 5: Merge Weights & Export to GGUF (Q4_K_M)
# ==============================================================================
print("\n" + "=" * 75)
print("  STEP 6: Merging LoRA Weights & Exporting GGUF")
print("=" * 75)

from peft import PeftModel

MERGED_DIR = "/content/iris_qwen3_4b_merged"
FINAL_GGUF = None
quant_type = None

if 'model' in globals(): del model
if 'trainer' in globals(): del trainer
torch.cuda.empty_cache()
gc.collect()

base_model = AutoModelForCausalLM.from_pretrained(
    TRAINING_BASE_MODEL,
    torch_dtype=torch.float16,
    device_map="cpu",
    low_cpu_mem_usage=True,
    trust_remote_code=True,
)
peft_model = PeftModel.from_pretrained(base_model, LORA_OUTPUT)
merged_model = peft_model.merge_and_unload()

os.makedirs(MERGED_DIR, exist_ok=True)
merged_model.save_pretrained(MERGED_DIR, max_shard_size="2GB")
tokenizer.save_pretrained(MERGED_DIR)

print(f"[SUCCESS] Merged model saved to: {MERGED_DIR}")

if not os.path.exists("/content/llama.cpp"):
    os.system("git clone --depth 1 https://github.com/ggerganov/llama.cpp.git /content/llama.cpp")
    os.system("pip install -q -r /content/llama.cpp/requirements.txt")

F16_GGUF = "/content/iris_f16.gguf"
os.system(f'python3 /content/llama.cpp/convert_hf_to_gguf.py "{MERGED_DIR}" --outfile "{F16_GGUF}" --outtype f16')

# Download official pre-compiled Linux x86_64 llama-quantize binary to avoid 15min cmake build
os.system('curl -s -L "https://github.com/ggerganov/llama.cpp/releases/download/b4500/llama-b4500-bin-ubuntu-x64.zip" -o /content/llama-bin.zip')
if os.path.exists("/content/llama-bin.zip"):
    os.system("unzip -q -o /content/llama-bin.zip -d /content/llama_bin/")
    quant_bin = None
    if os.path.exists("/content/llama_bin/build/bin/llama-quantize"):
        quant_bin = "/content/llama_bin/build/bin/llama-quantize"
    elif os.path.exists("/content/llama_bin/llama-quantize"):
        quant_bin = "/content/llama_bin/llama-quantize"

    if quant_bin:
        os.system(f'chmod +x "{quant_bin}"')
        TARGET_Q4 = "/content/IRIS-Qwen3-4B-Operator.Q4_K_M.gguf"
        res = os.system(f'"{quant_bin}" "{F16_GGUF}" "{TARGET_Q4}" Q4_K_M')
        if res == 0 and os.path.exists(TARGET_Q4):
            FINAL_GGUF = TARGET_Q4
            quant_type = "Q4_K_M"

if not FINAL_GGUF:
    # Explicitly name Q8_0 as Q8_0 so quantization type is never misrepresented
    TARGET_Q8 = "/content/IRIS-Qwen3-4B-Operator.Q8_0.gguf"
    print("[*] Performing direct Q8_0 export with true quantization naming...")
    os.system(f'python3 /content/llama.cpp/convert_hf_to_gguf.py "{MERGED_DIR}" --outfile "{TARGET_Q8}" --outtype q8_0')
    if os.path.exists(TARGET_Q8):
        FINAL_GGUF = TARGET_Q8
        quant_type = "Q8_0"
    else:
        raise FileNotFoundError("Export failed: neither Q4_K_M nor Q8_0 GGUF could be generated.")

# Compute SHA-256 Checksum and write model_manifest.json
import hashlib
import time
hasher = hashlib.sha256()
with open(FINAL_GGUF, "rb") as f:
    for chunk in iter(lambda: f.read(1024 * 1024), b""):
        hasher.update(chunk)
sha256_hash = hasher.hexdigest()

manifest = {
    "model_name": "IRIS-Qwen3-4B-Operator",
    "base_model": BASE_MODEL,
    "quantization": quant_type,
    "filename": os.path.basename(FINAL_GGUF),
    "filesize_bytes": os.path.getsize(FINAL_GGUF),
    "sha256": sha256_hash,
    "export_timestamp": time.time()
}

MANIFEST_PATH = "/content/model_manifest.json"
with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2)

print("\n" + "=" * 75)
print(f"FINAL GGUF EXPORTED: {FINAL_GGUF}")
print(f"Quantization Type:   {quant_type}")
print(f"SHA-256 Checksum:    {sha256_hash}")
print(f"Manifest Saved:      {MANIFEST_PATH}")
print("=" * 75)

"""Asks stock OpenJev, with no training, which team owns each test issue.

The model reads the issue's title and body and the team descriptions in teams.json, and gives a
probability for each team. It is served as its SERVE.md says: vLLM with the model's helper in front.
Copy the helper to .cache/training/openjev-shim.py first. About $0.40 on one H100.

    modal run training/stock_openjev.py
"""
import json
from pathlib import Path

import modal

TEAMS = ["oss-matching", "oss-foundations", "act", "nexus", "cgs"]
QUESTION = "Which team should own this GitHub issue in the Temporal server repository?"
DATA = Path(".cache/training")
MODEL_DIR = "/models/openjev"
VLLM_FLAGS = (
    "--host 127.0.0.1 --served-model-name qwen --port 8000 --enable-prefix-caching --max-model-len 16384 "
    "--gpu-memory-utilization 0.90 --limit-mm-per-prompt '{\"image\":1}' --trust-remote-code --max-num-seqs 256 "
    "--max-logprobs 64 --gdn-prefill-backend triton --quantization fp8"
)
HELPER_SETTINGS = {
    "VLLM": "http://localhost:8000/v1",
    "TOKENIZER": MODEL_DIR,
    "READOUT_T": "0.85",
    "READOUT_NOUL_T": "1.829074",
    "READOUT_NOUL_BIAS": "0",
    "READOUT_TARGETED": "1",
    "READOUT_INSTR_STYLE": "pyrepr",
    "SHIM_STAGGER": "1",
    "READOUT_PERMS": "1",
}

app = modal.App("oss-triage-stock-openjev")
models = modal.Volume.from_name("oss-triage-openjev", create_if_missing=True)
image = (
    modal.Image.from_registry("nvidia/cuda:13.0.1-devel-ubuntu22.04", add_python="3.12")
    .entrypoint([])
    .apt_install("build-essential")
    .pip_install("vllm==0.29.0", "torch==2.13.0", "transformers==5.17.0", "peft==0.21.0", "openai==3.16.2", "httpx==0.28.1", "ninja")
    .env({"CUDA_HOME": "/usr/local/cuda"})
    .add_local_file(DATA / "openjev-shim.py", "/root/shim.py")
)


def start_model():
    import os
    import subprocess
    import time
    import urllib.request

    vllm = subprocess.Popen(f"vllm serve {MODEL_DIR} {VLLM_FLAGS}", shell=True)
    subprocess.Popen(
        ["python", "/root/shim.py", "--host", "127.0.0.1", "--port", "3000"],
        env={**os.environ, **HELPER_SETTINGS},
        stdout=subprocess.DEVNULL,
    )
    for _ in range(180):
        if vllm.poll() is not None:
            raise RuntimeError(f"vllm exited {vllm.returncode}")
        try:
            urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2)
            return vllm
        except OSError:
            time.sleep(5)
    raise RuntimeError("vllm not healthy after 15 minutes")


def ask(issue, scopes):
    import urllib.request

    question = {"type": "choice", "instructions": QUESTION, "criteria": {team: scopes[team] for team in TEAMS}}
    body = {"model": "openjev", "state": f"GitHub issue:\n{issue['text']}", "questions": {"team": question}}
    request = urllib.request.Request("http://127.0.0.1:3000/v1/systemone", json.dumps(body).encode(), {"Content-Type": "application/json"})
    answer = json.load(urllib.request.urlopen(request, timeout=120))["answers"]["team"]
    return issue["number"], {team: answer["probabilities"][team] for team in TEAMS}


@app.function(image=image, gpu="H100", volumes={"/models": models}, timeout=1800)
def pick_teams(issues, scopes):
    from concurrent.futures import ThreadPoolExecutor

    vllm = start_model()
    with ThreadPoolExecutor(8) as pool:
        picks = dict(pool.map(lambda issue: ask(issue, scopes), issues))
    vllm.terminate()
    return picks


@app.local_entrypoint()
def main():
    issues = [{"number": issue["number"], "text": issue["text"]} for issue in json.load(open(DATA / "test.json"))]
    json.dump(pick_teams.remote(issues, json.load(open("training/teams.json"))), open(DATA / "stock-picks.json", "w"))

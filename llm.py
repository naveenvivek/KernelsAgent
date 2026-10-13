"""Ask a local model (Ollama or LM Studio, both OpenAI-compatible) to write Python."""
import json, re, urllib.request

BACKENDS = {"ollama": ("http://localhost:11434/v1", "qwen3:14b"),
            "lmstudio": ("http://localhost:1234/v1", "openai/gpt-oss-20b")}

def write_code(prompt: str, backend="ollama") -> str:
    base, model = BACKENDS[backend]
    body = {"model": model, "temperature": 0.2, "messages": [
        {"role": "system", "content": "Reply with ONE python code block only. Print the answer. No network access."},
        {"role": "user", "content": prompt}]}
    req = urllib.request.Request(base + "/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    text = json.load(urllib.request.urlopen(req, timeout=300))["choices"][0]["message"]["content"]
    m = re.search(r"```(?:python)?\n(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip()

import sys
import urllib.request
import urllib.error
import json
import subprocess
import os

def get_gateway_ip():
    try:
        routes = subprocess.check_output(["ip", "route"]).decode("utf-8")
        for line in routes.splitlines():
            if line.startswith("default via"):
                return line.split()[2]
    except Exception:
        pass
    return "127.0.0.1"

def query_lm_studio(prompt: str, file_path: str = None, system_prompt: str = "You are a helpful assistant.", temperature: float = 0.3, max_tokens: int = 0):
    gateway = get_gateway_ip()
    port = int(os.environ.get("LM_STUDIO_PORT", "1234"))
    urls = [
        f"http://127.0.0.1:{port}/v1/chat/completions",
    ]
    if gateway != "127.0.0.1":
        urls.append(f"http://{gateway}:{port}/v1/chat/completions")
        
    file_content = ""
    if file_path:
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    file_content = f.read()
                prompt = f"Here is the content of the file '{os.path.basename(file_path)}':\n\n```\n{file_content}\n```\n\n{prompt}"
            except Exception as e:
                print(f"Warning: Could not read file {file_path}: {e}", file=sys.stderr)
        else:
            print(f"Warning: File {file_path} not found.", file=sys.stderr)

    payload = {
        "model": "local-model",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature": temperature,
        "stream": False
    }
    # max_tokens is optional — some local models reject it
    if max_tokens and max_tokens > 0:
        payload["max_tokens"] = max_tokens
    
    data = json.dumps(payload).encode("utf-8")
    
    last_error = None
    for url in urls:
        req = urllib.request.Request(
            url, 
            data=data, 
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                content = res_data["choices"][0]["message"]["content"]
                print(content)
                return
        except urllib.error.URLError as e:
            last_error = e.reason
            
    print(f"Error: Could not connect to LM Studio at {urls}. Details: {last_error}", file=sys.stderr)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python lm_studio_bridge.py <prompt> [file_path] [system_prompt] [temperature] [max_tokens]", file=sys.stderr)
        sys.exit(1)
        
    prompt_arg = sys.argv[1]
    file_path_arg = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2].strip() != "" else None
    
    # Load system prompt from local txt file if available
    default_system = "You are a helpful assistant."
    script_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_file_path = os.path.join(script_dir, "lm_studio_subagent_prompt.txt")
    
    if os.path.exists(prompt_file_path):
        try:
            with open(prompt_file_path, "r", encoding="utf-8") as f:
                default_system = f.read().strip()
        except Exception:
            pass
            
    system_arg = sys.argv[3] if len(sys.argv) > 3 else default_system
    
    # temperature=0.3 balances determinism with LM Studio compatibility (0.0 causes disconnect)
    try:
        temp_arg = float(sys.argv[4]) if len(sys.argv) > 4 else 0.3
    except ValueError:
        temp_arg = 0.3

    try:
        max_tok_arg = int(sys.argv[5]) if len(sys.argv) > 5 else 0  # 0 = don't send, let model decide
    except ValueError:
        max_tok_arg = 0

    if file_path_arg in ("-", "None", "none", ""):
        file_path_arg = None
        
    query_lm_studio(prompt_arg, file_path_arg, system_arg, temp_arg, max_tok_arg)

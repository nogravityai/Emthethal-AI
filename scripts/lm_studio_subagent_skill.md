# Skill: Local LM Studio Subagent Integration
This skill allows any AI Agent to delegate large code analysis tasks to a local LM Studio instance (such as Llama 3) to prevent context window flooding and conserve tokens.

## Prerequisites
- LM Studio running on Windows Host (port `1234`).
- Local Server started inside LM Studio.
- Network proxy/firewall configured (port `1234` open to WSL gateway `0.0.0.0`).

## Components
1. **Bridge Script**: `scripts/lm_studio_bridge.py` (executes the network request from WSL to the Windows host).
2. **System Prompt**: `scripts/lm_studio_subagent_prompt.txt` (defines the behavior of the local model).

## How to Invoke the Skill
Instead of reading the files yourself, run the bridge script from the terminal. 

### Syntax:
```bash
wsl python3 scripts/lm_studio_bridge.py "<instruction>" "<file_path>" "[system_prompt_path_or_text]"
```

### Examples:
1. **Code Review / Bug Hunting (Recommended)**:
   ```bash
   wsl python3 scripts/lm_studio_bridge.py "Find potential race conditions or resource leaks in this file." "backend/app/database.py"
   ```
2. **Writing Unit Tests**:
   ```bash
   wsl python3 scripts/lm_studio_bridge.py "Write comprehensive pytest unit tests for this file." "backend/app/core/llm_normalizer.py"
   ```

## Best Practices
- **Never Read Large Files Directly**: If a file is > 100 lines, default to using this skill.
- **Parse the Result**: Read only the output of this command, which is the summarized/structured feedback from the local model.

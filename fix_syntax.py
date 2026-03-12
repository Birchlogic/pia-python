import os
import re

agent_dirs = ["agent/", "test/agents/", "test/graph/"]
files_to_update = []
for d in agent_dirs:
    for root, _, files in os.walk(d):
        for f in files:
            if f.endswith(".py"):
                files_to_update.append(os.path.join(root, f))

for filepath in files_to_update:
    with open(filepath, "r") as f:
        content = f.read()

    new_content = content.replace("def __init__(self), ai_config: dict = None):", "def __init__(self, ai_config: dict = None):")
    # Also handle the case where there were existing arguments: 
    # def __init__(self, args), ai_config: dict = None):
    new_content = re.sub(r'def __init__\(([^)]*)\), ai_config: dict = None\):', r'def __init__(\1, ai_config: dict = None):', new_content)

    if new_content != content:
        with open(filepath, "w") as f:
            f.write(new_content)

print(f"Fixed files.")

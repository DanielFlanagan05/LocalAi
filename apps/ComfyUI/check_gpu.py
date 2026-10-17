import json
import sys

import torch


if not torch.cuda.is_available():
    sys.exit("GPU unavailable. Check the AMD driver and bundled ROCm PyTorch installation.")

device = max(range(torch.cuda.device_count()), key=lambda i: torch.cuda.get_device_properties(i).total_memory)
try:
    with torch.cuda.device(device):
        _, total = torch.cuda.mem_get_info()
        x = torch.arange(32, dtype=torch.float32, device=f"cuda:{device}").reshape(4, 8)
        result = x @ x.T
        torch.cuda.synchronize()
        if result[0, 0].item() != 140:
            sys.exit("GPU calculation returned an incorrect result.")
except RuntimeError as error:
    sys.exit(f"GPU check failed: {error}\nRun this launcher from a normal Windows session with the AMD driver installed.")

print(json.dumps({"device": device, "name": torch.cuda.get_device_name(device), "vram": total}))

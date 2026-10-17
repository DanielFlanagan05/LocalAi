# LocalAI

Local launchers, Pi configuration and extensions, the local resource-monitor plugin, ComfyUI helper scripts, and saved workflows.

Machine-local state is intentionally excluded from Git. This includes model weights, chat sessions and logs, authentication material, downloaded runtimes, installed dependencies, generated outputs, caches, and test artifacts. The actual model files remain shared from the local `models` directory.

Some launchers use a machine-specific LocalAI root path; adjust that path if this checkout lives elsewhere.

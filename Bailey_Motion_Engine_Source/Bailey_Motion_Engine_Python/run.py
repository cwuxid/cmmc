"""Run the Bailey port from any working directory, including an isolated interpreter."""
from pathlib import Path
import sys

# Unlike the older square-room engine, this is a separate Python package.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bailey_motion.cli import main

if __name__ == "__main__":
    # Running this file delegates all options and execution to the shared CLI.
    # Importing it does not automatically launch an experiment or desktop window.
    raise SystemExit(main())

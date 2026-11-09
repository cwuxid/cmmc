"""Run the optional placement search from any directory/interpreter setup."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
from bailey_motion.crowd_optimize import main

if __name__=='__main__':
    raise SystemExit(main())

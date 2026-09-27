#!/usr/bin/env python3
"""
Root entrypoint for magicpin AI Challenge — LLM-Powered Judge Simulator.
Delegates to details/judge_simulator.py while ensuring correct dataset paths.
"""
import os
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    import details.judge_simulator as js
    js.DATASET_DIR = ROOT / "expanded"
    js.main()

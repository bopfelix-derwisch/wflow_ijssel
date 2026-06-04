"""Top-level entry point voor de ensemble pipeline."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ensemble.main import main

if __name__ == "__main__":
    main()

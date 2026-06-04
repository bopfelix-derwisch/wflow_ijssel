"""Top-level CLI voor de multimodel pipeline."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from multimodel.main import main

if __name__ == "__main__":
    main()

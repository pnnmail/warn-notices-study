"""The whole of stage 2: SEC reference (incremental) -> names -> matching -> subsidiary check.
Manual labels (match/labels.csv) are applied at every step; re-running is safe."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from match import match, reference, sec_reference, sub_check  # noqa: E402

if __name__ == "__main__":
    if "--no-download" not in sys.argv:
        sec_reference.main()
    reference.main()
    match.main()
    sub_check.main()

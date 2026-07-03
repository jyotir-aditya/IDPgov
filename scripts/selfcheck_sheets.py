"""Self-check for the SL No. auto-increment logic.

Run: python -m scripts.selfcheck_sheets  (from backend/)
or:  python scripts/selfcheck_sheets.py

No Google credentials needed — tests the pure _compute_next_sl_no function.
"""
import sys
from pathlib import Path

# Make `app` importable when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.sheets import _compute_next_sl_no, HEADER_ROW


def main() -> int:
    # Empty sheet (only header) → first SL No.
    assert _compute_next_sl_no([HEADER_ROW[0]]) == "BEP/UP001", "empty sheet should start at 001"

    # A few existing rows → next sequential
    cells = ["SL No.", "BEP/UP001", "BEP/UP002", "BEP/UP003"]
    assert _compute_next_sl_no(cells) == "BEP/UP004", "should increment from 003 → 004"

    # Out-of-order / gaps → picks the max, not count
    cells = ["SL No.", "BEP/UP001", "BEP/UP005", "BEP/UP003"]
    assert _compute_next_sl_no(cells) == "BEP/UP006", "should use max existing (005) → 006"

    # Blank cells interspersed → ignored
    cells = ["", "BEP/UP001", "", "BEP/UP002", ""]
    assert _compute_next_sl_no(cells) == "BEP/UP003", "blanks should be ignored"

    # Roll over to 4 digits at 999
    cells = ["BEP/UP999"]
    assert _compute_next_sl_no(cells) == "BEP/UP1000", "should roll over to 4 digits"

    print("All SL No. auto-increment checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
"""Build data/rowsetta.sqlite from the UCI Online Retail workbook.

Owner: TBD
Usage: python scripts/import_uci.py [path/to/Online Retail.xlsx]

Rules (docs/architecture.md, "Aktarım kuralları"):
 1. Read with pandas.read_excel; convert prices with Decimal(str(x)), never Decimal(x).
 2. Invoice starting with "C" or negative quantity -> net_qty = -abs(quantity).
 3. Drop invoices starting with "A" (Adjust bad debt), including the positive one.
 4. Drop zero quantity, non-positive price, price not representable in 4 decimals,
    missing required fields; count each reason.
 5. List stock codes outside the usual pattern (5 digits + optional letters) so the
    owner can classify them into config/non_product_codes.json (is_product = 0).
 6. product_name = latest non-empty description among accepted lines.
 7. Do not import CustomerID.
 8. Write data/import_report.json: raw / accepted / rejected counts by reason,
    SHA-256 of the source file, rule version.
Build into a temporary file and replace the snapshot only after the checks pass.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT / "data" / "raw" / "Online Retail.xlsx"
DB_PATH = ROOT / "data" / "rowsetta.sqlite"
SCHEMA = ROOT / "db" / "schema.sql"
RULE_VERSION = "0.1"


def main(source: Path = DEFAULT_SOURCE) -> int:
    raise NotImplementedError("import_uci.main")


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE))

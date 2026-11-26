# Brokerage Positions CSV Preprocessor

A modular, standard-library Python CLI tool that validates and normalizes brokerage positions CSV exports into a unified format for portfolio tracking.

## Features

- **Provider-Driven Architecture:** Encapsulates brokerage rules in `PROVIDER_CONFIG` (currently supporting **Schwab**, designed for easy extension to **Fidelity**, **Interactive Brokers**, etc.).
- **Financial Precision:** Uses Python's `Decimal` with `ROUND_HALF_UP` for all currency, bond price normalization (`Price / 100`), and `Avg Cost` calculations.
- **Row & File Normalization:**
  - Enforces consistent leading output columns: `Date`, `Symbol`, `Quantity`, `Avg Cost`, followed by preserved source columns.
  - Maps cash balances (`Cash & Cash Investments`) to `$CASH` with `Price = 1`.
  - Filters out worthless equities (`Price == "N/A"`) and configurable excluded symbols.
- **Data Integrity & Atomic Writes:** Validates filename/header consistency and writes output atomically via temporary files and `os.link`—never overwriting existing outputs or leaving partial files.
- **Prompt-Driven Maintenance:** Co-locates modular AI generation/maintenance prompts and documentation under `prompts/`.

## Repository Structure

```text
.
├── preprocess_positions_statements.py          # Main executable preprocessing script
├── prompts/
│   ├── preprocess_positions_statements.md      # Master specification & generation prompt
│   └── preprocess_positions_statements_doc.md  # Architecture, decisions & test checklist
└── <Provider>/                                 # Input/output CSV directory (e.g., Schwab/)
```

## Usage

Place raw brokerage CSV exports inside `<WORK_DIR>/<Provider>/` (for example, `./Schwab/Individual-Positions-2026-11-18-123456.csv`) and run:

```bash
# Default execution (uses current directory as WORK_DIR, LOG verbosity)
python3 preprocess_positions_statements.py Schwab

# Specify a custom root working directory and DEBUG diagnostics
python3 preprocess_positions_statements.py Schwab /path/to/work_dir --verbosity DEBUG
```

Each valid file produces `<ORIGINAL_STEM>_<ACCOUNT_TYPE>_<LAST3>_preprocessed.csv` in the same provider directory without modifying the original export.

## Requirements

- **Python 3.10+** (uses only standard-library modules; zero third-party runtime dependencies).
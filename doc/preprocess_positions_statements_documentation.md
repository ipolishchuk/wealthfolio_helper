# Documentation & Deliverables: `preprocess_positions_statements.py`

Companion documentation for `prompts/preprocess_positions_statements.md` and `preprocess_positions_statements.py`, covering the Section 14 deliverables.

## 1. Architecture Overview

The script is organized as a single-file, functional-procedural pipeline (`preprocess_positions_statements.py`) built exclusively on Python's standard library (`argparse`, `csv`, `dataclasses`, `datetime`, `decimal`, `logging`, `os`, `pathlib`, `re`, `sys`, `tempfile`).

### Execution Pipeline

1. **CLI & Logging (`parse_args`, `setup_logger`, `run_pipeline`):**
   * Parses positional `provider`, optional `work_dir` (defaulting to `Path.cwd()`), and `--verbosity` (`LOG` or `DEBUG`).
   * Configures a dedicated `logging.Logger` (`preprocess_positions`) routed to `stdout` without altering control flow between `LOG` and `DEBUG`.
2. **Provider Initialization (`init_provider`, `PROVIDER_CONFIG`):**
   * Validates the requested provider name against `PROVIDER_CONFIG` and returns its read-only configuration dictionary without storing per-provider or per-file state in module globals.
3. **File Discovery & Filename Validation (`find_inputs`, `parse_fname`):**
   * Scans `work_dir / provider` for `.csv` files sorted lexicographically by filename.
   * Validates each filename against `cfg["fname_pattern"]`, extracts `acct_name`, `stmt_date`, and `stmt_time` into an immutable `FnameInfo` dataclass, and verifies calendar date and `HHMMSS` timestamp validity.
4. **Per-File Processing (`process_file`):**
   * Wraps each candidate file in an independent `try ... except FileValidationError` block so structural errors in one statement log an error and never abort subsequent files.
   * Dispatches provider-specific parsing and row normalization to `schwab_process`, constructs the destination filename via `build_out_path`, skips early if the destination already exists, validates output schema invariants (`validate_output`), and writes atomically (`write_atomic`).
5. **Schwab-Specific Stage (`schwab_*` procedures):**
   * `schwab_parse_hdr`: Reconstructs and validates the unquoted first physical line (`Positions for account ... as of HH:MM AM/PM ET, YYYY/MM/DD`) into a `HeaderInfo` dataclass.
   * `schwab_prepare_cols`: Maps source column headers, ignores trailing or empty filler columns that contain no real values, and verifies required source columns.
   * `schwab_build_output_cols`: Enforces leading column order (`Date`, `Symbol`, `Quantity`, `Avg Cost`) followed by remaining active columns in original relative order.
   * `schwab_transform_row` & `schwab_is_bond`: Applies row-level filtering (missing symbol, `excluded_symbols`, worthless equities where `Price == "N/A"`), `$CASH` conversion, bond price normalization (`Price / 100` in `Decimal`), and `Avg Cost` calculation.

## 2. Significant Implementation Decisions

* **Raw Line Read Before CSV Parsing (`read_raw_lines` + `schwab_parse_hdr`):**
  * Schwab's first line contains an unquoted comma after `ET` (`... as of 05:36 AM ET, 2026/11/18`). Reading physical lines via `splitlines()` first allows `schwab_parse_hdr` to parse line 1 directly with regex before passing all lines to `csv.reader` and slicing `rows[2:-1]`.
* **Exact `Decimal` Financial Arithmetic (`parse_decimal`, `format_decimal`, `calc_avg_cost`):**
  * All currency symbols (`$`) and thousands separators (`,`) are stripped prior to `Decimal` conversion.
  * `format_decimal` uses `normalize()` and fixed-point formatting (`format(normal, "f")`) with trailing zero stripping so numbers never render in scientific notation (e.g., `1E+3`) or `-0`.
  * `Avg Cost` uses `ROUND_HALF_UP` quantized to `Decimal("0.001")` (at most 3 decimal places without trailing zero padding), returning `""` on missing, invalid, or zero `Quantity` or `Cost Basis`.
* **Race-Safe Atomic File Creation (`write_atomic`):**
  * Writes CSV output to a hidden `NamedTemporaryFile` in the target directory, calls `flush()` and `os.fsync()`, and publishes the final file via `os.link(tmp_path, dest_path)`. Because `os.link` fails atomically with `FileExistsError` if another process creates `dest_path` concurrently, existing files cannot be overwritten, and the `finally` block always unlinks the temporary file.
* **Explicit Separation of File-Level vs. Row-Level Failures:**
  * Structural issues (empty files, bad headers, filename/header mismatches, duplicate/missing columns, extra non-empty trailing fields in a row) raise `FileValidationError` to abort only that file without producing partial output.
  * Recoverable data issues (missing `Symbol`, missing/invalid numeric fields, zero `Quantity`) emit warnings (identifying `Symbol` when available) and either skip the unidentifiable row or leave `Avg Cost` blank while preserving the row.
* **Extensible Dispatch Boundary:**
  * Adding Fidelity or Interactive Brokers requires only adding a new key to `PROVIDER_CONFIG`, implementing `<provider>_process` and helper routines, and registering the branch in `process_file` without modifying `find_inputs`, `validate_output`, `write_atomic`, or `run_pipeline`.

## 3. Assumptions Made Where Specification Was Ambiguous

1. **Account Name Matching Rule:**
   * The specification refers to account name/account type agreement between filename (`AAAAA-Positions-...`) and header (`Positions for account AAAAA ...NNN`). The implementation validates exact trimmed string equality (`hdr.acct_name == finfo.acct_name`) rather than restricting values to a closed enum, allowing account names such as `Individual` or `Join` (or custom account labels matching the regex) as long as filename and header agree.
2. **Row Numbering in Diagnostics:**
   * Because physical line 1 is the statement description, line 2 is blank, and line 3 is the CSV column header, position data rows begin at physical line 4 (`enumerate(body_rows[1:], start=4)`). Warning and debug logs report 1-based physical line numbers for easier cross-referencing against the raw CSV.
3. **Empty / Filler Header Columns:**
   * Trailing commas in Schwab exports create an empty-string header cell at the end of the header row. If all data cells in that column position are empty or match configured missing tokens (`--`, `N/A`, etc.), the column is ignored; if any row contains non-missing data under an empty header, it is rejected as a structural `FileValidationError`.
4. **Cash Row Market Value Clearing:**
   * When converting `"Cash & Cash Investments"` to `$CASH`, `Mkt Val (Market Value)` is moved into `Quantity`, `Price` is set to `"1"`, `Avg Cost` is left blank, and the original `Mkt Val (Market Value)` cell is cleared (`""`) to avoid duplicating the balance across columns.
5. **Output Line Endings & Encoding:**
   * Input files are decoded with `utf-8-sig` (handling optional UTF-8 BOMs from spreadsheet/broker exports), and normalized CSV outputs are written in standard `utf-8` with `\n` line terminators.

## 4. Test Verification Summary

> **Note:** In accordance with Section 12 (*"Do not claim tests have passed unless they have actually been executed"*), no automated test suite was executed during the generation of this documentation file.

To verify `preprocess_positions_statements.py` locally in your repository, run syntax compilation and a `pytest` suite covering the scenarios below:

### Quick Verification Command

```bash
python3 -m py_compile preprocess_positions_statements.py && pytest -v
```

### Verification Checklist (Section 12 Coverage)

* **CLI & Logging:** `LOG` vs. `DEBUG` output levels; default `work_dir` vs. explicit `work_dir`; unsupported provider exit code `1`.
* **Filename & Header Consistency:** Valid `Individual` and `Join` filenames; unquoted comma after `ET` in line 1; invalid calendar dates/timestamps; filename vs. header account name and date mismatches.
* **CSV Structure & Columns:** Insufficient rows (`< 5`); trailing empty filler column with blanks vs. non-missing data; missing required columns; duplicate column names; extra non-empty row fields; leading output column order (`Date, Symbol, Quantity, Avg Cost`).
* **Row Transformations:**
  * Missing `Symbol` skipped with warning.
  * `excluded_symbols` filtering (default `[]` and populated list).
  * Worthless equities (`Price == "N/A"`) excluded.
  * `"Cash & Cash Investments"` mapped to `$CASH` with `Quantity = Mkt Val`, `Price = 1`, blank `Avg Cost`, and blank `Mkt Val`.
  * Qualifying bonds (`Asset Type == "Fixed Income"` and `Description` containing `"US TREASURIES "`) keep `Quantity` unchanged and divide `Price` by `100` using `Decimal` (e.g., `$68.01` -> `0.6801`); non-matching `Fixed Income` and non-bond rows keep `Price` unchanged.
  * Numeric cleaning (`$`, `,`, `--`, blanks, negatives, `0`) and `Avg Cost` `ROUND_HALF_UP` rounding (`<= 3` decimals, no trailing zeros, blank on zero/missing `Quantity` or `Cost Basis`).
* **File Safety & Isolation:** Existing destination file skipped (`<INPUT_FILENAME> -- Output file already exists`); atomic `os.link` race-condition handling; temporary file cleanup on simulated write error; failure in one CSV does not block subsequent CSVs.
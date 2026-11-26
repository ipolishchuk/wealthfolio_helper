#!/usr/bin/env python3
"""Preprocess brokerage positions CSV statements into normalized output CSVs."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import logging
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any


OUT_SUFFIX = "preprocessed"

COL_DATE = "Date"
COL_SYMBOL = "Symbol"
COL_QTY = "Quantity"
COL_PRICE = "Price"
COL_AVG_COST = "Avg Cost"

CASH_SYMBOL = r"$CASH"

LEADING_OUT_COLS = [COL_DATE, COL_SYMBOL, COL_QTY, COL_AVG_COST]
MAX_AVG_COST_PLACES = Decimal("0.001")
MISSING_TOKENS = frozenset({"", "--", "N/A", "NA", "NONE", "NULL"})

PROVIDER_CONFIG: dict[str, dict[str, Any]] = {
    "Schwab": {
        "fname_pattern": (
            r"^(?P<acct_name>[a-zA-Z0-9_.$! -]+)-Positions-"
            r"(?P<date>\d{4}-\d{2}-\d{2})-(?P<time>\d{6})\.csv$"
        ),
        "header_pattern": (
            r"^Positions for account (?P<acct_name>.+?)\s+\.\.\.(?P<last3>\d{3})"
            r"\s+as of\s+(?P<time>\d{1,2}:\d{2}\s*(?:AM|PM))\s+ET,\s*"
            r"(?P<date>\d{4}/\d{2}/\d{2})$"
        ),
        "src_symbol": "Symbol",
        "src_qty": "Qty (Quantity)",
        "src_price": "Price",
        "src_mkt_val": "Mkt Val (Market Value)",
        "src_cost_basis": "Cost Basis",
        "excluded_symbols": [],
        "cash_label": "Cash & Cash Investments",
        "worthless_price_token": "N/A",
        "desc_col": "Description",
        "asset_type_col": "Asset Type",
        "bond_substrings": ["US TREASURIES "],
        "bond_asset_type": "Fixed Income",
        "bond_price_divisor": Decimal("100"),
        "bond_case_insensitive": False,
        "missing_tokens": ["--", "N/A"],
    }
}


@dataclass(frozen=True)
class FnameInfo:
    """Parsed metadata from a candidate input filename."""

    path: Path
    acct_name: str
    stmt_date: str
    stmt_time: str


@dataclass(frozen=True)
class HeaderInfo:
    """Parsed metadata from the statement header line."""

    acct_name: str
    last3: str
    stmt_date: str
    stmt_time: str


class FileValidationError(Exception):
    """Raised when a file-level structural or consistency check fails."""


def setup_logger(verbosity: str) -> logging.Logger:
    """Configure and return the application logger for LOG or DEBUG."""
    logger = logging.getLogger("preprocess_positions")
    logger.handlers.clear()
    logger.propagate = False
    level = logging.DEBUG if verbosity == "DEBUG" else logging.INFO
    logger.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    fmt = "%(levelname)s: %(message)s" if level == logging.DEBUG else "%(message)s"
    handler.setFormatter(logging.Formatter(fmt))
    logger.addHandler(handler)
    return logger


def init_provider(provider: str) -> dict[str, Any]:
    """Validate provider support and return its read-only configuration."""
    if not provider or provider not in PROVIDER_CONFIG:
        supported = ", ".join(sorted(PROVIDER_CONFIG.keys()))
        raise ValueError(
            f"Unsupported provider '{provider}'. Supported providers: {supported}"
        )
    return PROVIDER_CONFIG[provider]


def is_missing_token(raw_val: Any, extra_missing: set[str] | None = None) -> bool:
    """Return True if value is blank or matches configured missing-value tokens."""
    if raw_val is None:
        return True
    text = str(raw_val).strip()
    if not text:
        return True
    missing_upper = {m.upper() for m in (MISSING_TOKENS | (extra_missing or set()))}
    return text.upper() in missing_upper


def parse_decimal(
    raw_val: Any,
    extra_missing: set[str] | None = None,
) -> Decimal | None:
    """Parse currency/comma-formatted text into a Decimal, or None if missing/invalid."""
    if is_missing_token(raw_val, extra_missing):
        return None

    cleaned = str(raw_val).strip().replace(r"$", "").replace(",", "").strip()
    if is_missing_token(cleaned, extra_missing):
        return None

    try:
        dec = Decimal(cleaned)
    except InvalidOperation:
        return None

    return dec if dec.is_finite() else None


def format_decimal(value: Decimal | None) -> str:
    """Format a finite Decimal cleanly without scientific notation or trailing zeros."""
    if value is None or not value.is_finite():
        return ""
    normal = value.normalize()
    text = format(normal, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text if text and text != "-0" else "0"


def calc_avg_cost(
    cost_basis: Decimal | None,
    quantity: Decimal | None,
    fname: str,
    symbol: str,
    row_num: int,
    logger: logging.Logger,
) -> str:
    """Calculate Avg Cost = Cost Basis / Quantity rounded to <=3 decimals (ROUND_HALF_UP)."""
    if quantity is None:
        logger.warning(
            "%s [%s]: Row %d missing/invalid Quantity; Avg Cost left blank",
            fname,
            symbol,
            row_num,
        )
        return ""
    if quantity == 0:
        logger.warning(
            "%s [%s]: Row %d has zero Quantity; Avg Cost left blank",
            fname,
            symbol,
            row_num,
        )
        return ""
    if cost_basis is None:
        logger.warning(
            "%s [%s]: Row %d missing/invalid Cost Basis; Avg Cost left blank",
            fname,
            symbol,
            row_num,
        )
        return ""

    try:
        quotient = cost_basis / quantity
        if not quotient.is_finite():
            raise InvalidOperation("Non-finite quotient")
        rounded = quotient.quantize(MAX_AVG_COST_PLACES, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        logger.warning(
            "%s [%s]: Row %d failed Avg Cost calculation; Avg Cost left blank",
            fname,
            symbol,
            row_num,
        )
        return ""

    result = format_decimal(rounded)
    logger.debug(
        "%s [%s]: Row %d Avg Cost=(%s / %s) -> %s",
        fname,
        symbol,
        row_num,
        cost_basis,
        quantity,
        result,
    )
    return result


def parse_fname(path: Path, cfg: dict[str, Any], logger: logging.Logger) -> FnameInfo:
    """Validate filename pattern, timestamp, and calendar date."""
    match = re.match(cfg["fname_pattern"], path.name)
    if not match:
        raise FileValidationError(
            f"{path.name}: Filename does not match expected pattern"
        )

    acct_name = match.group("acct_name").strip()
    date_str = match.group("date")
    time_str = match.group("time")

    if not acct_name:
        raise FileValidationError(f"{path.name}: Missing account name in filename")

    try:
        parsed_date = date.fromisoformat(date_str)
    except ValueError as exc:
        raise FileValidationError(
            f"{path.name}: Invalid calendar date '{date_str}' in filename"
        ) from exc

    try:
        datetime.strptime(time_str, "%H%M%S")
    except ValueError as exc:
        raise FileValidationError(
            f"{path.name}: Invalid timestamp '{time_str}' in filename"
        ) from exc

    info = FnameInfo(
        path=path,
        acct_name=acct_name,
        stmt_date=parsed_date.isoformat(),
        stmt_time=time_str,
    )
    logger.debug("Filename validated: %s -> %s", path.name, info)
    return info


def find_inputs(
    in_dir: Path,
    cfg: dict[str, Any],
    logger: logging.Logger,
) -> list[FnameInfo]:
    """Discover candidate CSV files in in_dir, validate filenames, and sort by name."""
    if not in_dir.exists() or not in_dir.is_dir():
        raise FileValidationError(f"Input directory does not exist: {in_dir}")

    csv_paths = sorted(
        (p for p in in_dir.iterdir() if p.is_file() and p.suffix.lower() == ".csv"),
        key=lambda p: p.name,
    )
    logger.debug("Discovered %d CSV file(s) in %s", len(csv_paths), in_dir)

    valid_files: list[FnameInfo] = []
    for path in csv_paths:
        try:
            valid_files.append(parse_fname(path, cfg, logger))
        except FileValidationError as exc:
            logger.error("%s", exc)
    return valid_files


def read_raw_lines(path: Path) -> list[str]:
    """Read raw physical lines from a CSV file while preserving blank lines."""
    try:
        raw_text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise FileValidationError(f"{path.name}: Unable to read file ({exc})") from exc
    except UnicodeDecodeError as exc:
        raise FileValidationError(f"{path.name}: Invalid UTF-8 encoding ({exc})") from exc

    if not raw_text.strip():
        raise FileValidationError(f"{path.name}: Input file is empty")

    return raw_text.splitlines()


def schwab_parse_hdr(first_line: str, fname: str, cfg: dict[str, Any]) -> HeaderInfo:
    """Parse Schwab's first physical line despite an unquoted comma after ET."""
    cleaned = first_line.strip()
    if len(cleaned) >= 2 and cleaned.startswith('"') and cleaned.endswith('"'):
        cleaned = cleaned[1:-1].replace('""', '"').strip()

    match = re.match(cfg["header_pattern"], cleaned)
    if not match:
        raise FileValidationError(
            f"{fname}: Invalid statement header '{cleaned}'"
        )

    acct_name = match.group("acct_name").strip()
    last3 = match.group("last3")
    time_str = re.sub(r"\s+", " ", match.group("time").strip().upper())
    raw_date = match.group("date")

    if not acct_name:
        raise FileValidationError(f"{fname}: Empty account name in statement header")

    try:
        datetime.strptime(time_str, "%I:%M %p")
    except ValueError as exc:
        raise FileValidationError(
            f"{fname}: Invalid time '{time_str}' in statement header"
        ) from exc

    try:
        parsed_date = datetime.strptime(raw_date, "%Y/%m/%d").date()
    except ValueError as exc:
        raise FileValidationError(
            f"{fname}: Invalid date '{raw_date}' in statement header"
        ) from exc

    return HeaderInfo(
        acct_name=acct_name,
        last3=last3,
        stmt_date=parsed_date.isoformat(),
        stmt_time=time_str,
    )


def parse_csv_rows(lines: list[str], fname: str) -> list[list[str]]:
    """Parse physical lines into CSV rows while detecting malformed CSV structure."""
    reader = csv.reader(lines, delimiter=",", quotechar='"')
    try:
        rows = list(reader)
    except csv.Error as exc:
        raise FileValidationError(f"{fname}: Malformed CSV structure ({exc})") from exc

    if not rows:
        raise FileValidationError(f"{fname}: No CSV rows found")
    return rows


def schwab_prepare_cols(
    headers: list[str],
    data_rows: list[list[str]],
    required_cols: list[str],
    extra_missing: set[str],
    fname: str,
    logger: logging.Logger,
) -> tuple[dict[str, int], list[str]]:
    """Validate headers, ignore blank header columns without real data, and build map."""
    blank_header_positions: list[int] = [
        idx for idx, raw_name in enumerate(headers) if not raw_name.strip()
    ]
    ignored_indices: set[int] = set()

    for idx in blank_header_positions:
        has_non_missing = any(
            idx < len(row) and not is_missing_token(row[idx], extra_missing)
            for row in data_rows
        )
        if has_non_missing:
            raise FileValidationError(
                f"{fname}: Empty column header at position {idx + 1} contains data"
            )
        ignored_indices.add(idx)
        logger.debug(
            "%s: Ignoring empty column header at position %d (no non-missing data found)",
            fname,
            idx + 1,
        )

    col_map: dict[str, int] = {}
    active_headers: list[str] = []
    seen: set[str] = set()

    for idx, raw_name in enumerate(headers):
        if idx in ignored_indices:
            continue
        name = raw_name.strip()
        if name in seen:
            raise FileValidationError(
                f"{fname}: Duplicate source column '{name}'"
            )
        seen.add(name)
        col_map[name] = idx
        active_headers.append(name)

    missing = [c for c in required_cols if c not in col_map]
    if missing:
        raise FileValidationError(
            f"{fname}: Missing required source columns: {', '.join(missing)}"
        )

    logger.debug("%s: Source column mapping=%s", fname, col_map)
    return col_map, active_headers


def schwab_is_bond(
    desc_val: str,
    asset_type_val: str,
    cfg: dict[str, Any],
) -> bool:
    """Return True if row matches configured bond substrings and asset type."""
    bond_substrings: list[str] = cfg.get("bond_substrings", [])
    target_asset: str = cfg.get("bond_asset_type", "")
    case_insensitive: bool = bool(cfg.get("bond_case_insensitive", False))

    if asset_type_val.strip() != target_asset:
        return False

    desc_clean = desc_val.strip()
    if case_insensitive:
        desc_cmp = desc_clean.lower()
        return any(sub.lower() in desc_cmp for sub in bond_substrings if sub)
    return any(sub in desc_clean for sub in bond_substrings if sub)


def schwab_build_output_cols(active_headers: list[str]) -> list[str]:
    """Build output column order: Date, Symbol, Quantity, Avg Cost, then remaining."""
    ordered = list(LEADING_OUT_COLS)
    seen = set(ordered)

    for clean_col in active_headers:
        out_col = COL_QTY if clean_col == "Qty (Quantity)" else clean_col
        if out_col and out_col not in seen:
            ordered.append(out_col)
            seen.add(out_col)

    if COL_PRICE not in seen:
        ordered.append(COL_PRICE)

    return ordered


def schwab_transform_row(
    row: list[str],
    col_map: dict[str, int],
    out_cols: list[str],
    stmt_date: str,
    cfg: dict[str, Any],
    fname: str,
    row_num: int,
    logger: logging.Logger,
) -> dict[str, str] | None:
    """Transform a single Schwab position row into an output record or None."""
    max_header_idx = max(col_map.values(), default=-1)
    if len(row) > max_header_idx + 1:
        extra_nonempty = [c.strip() for c in row[max_header_idx + 1 :] if c.strip()]
        if extra_nonempty:
            raise FileValidationError(
                f"{fname}: Row {row_num} has unexpected extra nonempty fields"
            )

    def get_src(col_key: str) -> str:
        col_name = cfg[col_key]
        idx = col_map.get(col_name)
        if idx is None or idx >= len(row):
            return ""
        return row[idx].strip()

    sym_raw = get_src("src_symbol")
    if not sym_raw:
        logger.warning("%s: Row %d skipped due to missing Symbol", fname, row_num)
        return None

    excluded_syms = {s.strip() for s in cfg.get("excluded_symbols", []) if s.strip()}
    if sym_raw in excluded_syms:
        logger.debug("%s: Excluded symbol '%s' on row %d", fname, sym_raw, row_num)
        return None

    price_raw = get_src("src_price")
    worthless_token = str(cfg.get("worthless_price_token", "N/A")).strip()
    # Schwab uses "N/A" to mark worthless equities.
    # We exclude these positions from the Wealthfolio import.
    if price_raw == worthless_token:
        logger.debug(
            "%s: Excluded worthless equity '%s' (Price='%s') on row %d",
            fname,
            sym_raw,
            price_raw,
            row_num,
        )
        return None

    extra_missing = set(cfg.get("missing_tokens", []))
    cash_label = str(cfg.get("cash_label", "Cash & Cash Investments")).strip()

    base_record = {col: "" for col in out_cols}
    for clean_col, idx in col_map.items():
        out_col = COL_QTY if clean_col == "Qty (Quantity)" else clean_col
        if out_col in base_record and idx < len(row):
            base_record[out_col] = row[idx].strip()

    base_record[COL_DATE] = stmt_date
    base_record[COL_SYMBOL] = sym_raw

    if sym_raw == cash_label:
        mkt_val_dec = parse_decimal(get_src("src_mkt_val"), extra_missing)
        qty_str = format_decimal(mkt_val_dec)
        if mkt_val_dec is None:
            logger.warning(
                "%s [%s]: Cash position on row %d missing/invalid market value",
                fname,
                CASH_SYMBOL,
                row_num,
            )
        base_record[COL_SYMBOL] = CASH_SYMBOL
        base_record[COL_QTY] = qty_str
        base_record[COL_PRICE] = "1"
        base_record[COL_AVG_COST] = ""
        if cfg["src_mkt_val"] in base_record:
            base_record[cfg["src_mkt_val"]] = ""
        logger.debug(
            "%s: Cash conversion row %d '%s' -> %s (Quantity=%s, Price=1)",
            fname,
            row_num,
            sym_raw,
            CASH_SYMBOL,
            qty_str,
        )
        return base_record

    desc_val = get_src("desc_col")
    asset_val = get_src("asset_type_col")
    is_bond = schwab_is_bond(desc_val, asset_val, cfg)

    qty_dec = parse_decimal(get_src("src_qty"), extra_missing)
    cost_dec = parse_decimal(get_src("src_cost_basis"), extra_missing)

    if is_bond:
        divisor = Decimal(str(cfg["bond_price_divisor"]))
        price_dec = parse_decimal(price_raw, extra_missing)
        if price_dec is None or divisor == 0:
            logger.warning(
                "%s [%s]: Qualifying bond on row %d has invalid/missing Price '%s'",
                fname,
                sym_raw,
                row_num,
                price_raw,
            )
            norm_price_str = price_raw
        else:
            try:
                norm_price_dec = price_dec / divisor
                if not norm_price_dec.is_finite():
                    raise InvalidOperation("Non-finite normalized bond price")
                norm_price_str = format_decimal(norm_price_dec)
            except InvalidOperation:
                logger.warning(
                    "%s [%s]: Qualifying bond on row %d failed Price normalization",
                    fname,
                    sym_raw,
                    row_num,
                )
                norm_price_str = price_raw

        qty_str = format_decimal(qty_dec)
        avg_cost_str = calc_avg_cost(
            cost_basis=cost_dec,
            quantity=qty_dec,
            fname=fname,
            symbol=sym_raw,
            row_num=row_num,
            logger=logger,
        )
        base_record[COL_QTY] = qty_str
        base_record[COL_PRICE] = norm_price_str
        base_record[COL_AVG_COST] = avg_cost_str
        logger.debug(
            "%s [%s]: Bond normalized row %d (qty=%s, orig_price=%s, norm_price=%s, avg_cost=%s)",
            fname,
            sym_raw,
            row_num,
            qty_str,
            price_raw,
            norm_price_str,
            avg_cost_str,
        )
        return base_record

    qty_str = format_decimal(qty_dec)
    avg_cost_str = calc_avg_cost(
        cost_basis=cost_dec,
        quantity=qty_dec,
        fname=fname,
        symbol=sym_raw,
        row_num=row_num,
        logger=logger,
    )
    base_record[COL_QTY] = qty_str
    base_record[COL_PRICE] = price_raw
    base_record[COL_AVG_COST] = avg_cost_str
    logger.debug(
        "%s [%s]: Standard row %d (qty=%s, price=%s, avg_cost=%s)",
        fname,
        sym_raw,
        row_num,
        qty_str,
        price_raw,
        avg_cost_str,
    )
    return base_record


def schwab_process(
    finfo: FnameInfo,
    cfg: dict[str, Any],
    logger: logging.Logger,
) -> tuple[HeaderInfo, list[str], list[dict[str, str]]]:
    """Parse, validate, and transform a single Schwab positions CSV."""
    fname = finfo.path.name
    raw_lines = read_raw_lines(finfo.path)
    hdr = schwab_parse_hdr(raw_lines[0], fname, cfg)
    logger.debug("%s: Parsed statement header -> %s", fname, hdr)

    if hdr.acct_name != finfo.acct_name:
        raise FileValidationError(
            f"{fname}: Account name mismatch (filename '{finfo.acct_name}' "
            f"vs header '{hdr.acct_name}')"
        )
    if hdr.stmt_date != finfo.stmt_date:
        raise FileValidationError(
            f"{fname}: Statement date mismatch (filename '{finfo.stmt_date}' "
            f"vs header '{hdr.stmt_date}')"
        )

    rows = parse_csv_rows(raw_lines, fname)
    if len(rows) < 5:
        raise FileValidationError(
            f"{fname}: Insufficient CSV records ({len(rows)} rows found)"
        )

    body_rows = rows[2:-1]
    if len(body_rows) < 2:
        raise FileValidationError(
            f"{fname}: Missing column header or position rows after trimming"
        )

    required_cols = [
        cfg["src_symbol"],
        cfg["src_qty"],
        cfg["src_price"],
        cfg["src_mkt_val"],
        cfg["src_cost_basis"],
        cfg["desc_col"],
        cfg["asset_type_col"],
    ]
    extra_missing = set(cfg.get("missing_tokens", []))
    col_map, active_headers = schwab_prepare_cols(
        headers=body_rows[0],
        data_rows=body_rows[1:],
        required_cols=required_cols,
        extra_missing=extra_missing,
        fname=fname,
        logger=logger,
    )
    out_cols = schwab_build_output_cols(active_headers)
    logger.debug("%s: Output columns=%s", fname, out_cols)

    out_rows: list[dict[str, str]] = []
    for row_num, row in enumerate(body_rows[1:], start=4):
        transformed = schwab_transform_row(
            row=row,
            col_map=col_map,
            out_cols=out_cols,
            stmt_date=hdr.stmt_date,
            cfg=cfg,
            fname=fname,
            row_num=row_num,
            logger=logger,
        )
        if transformed is not None:
            out_rows.append(transformed)

    logger.debug(
        "%s: Source position rows=%d, output rows=%d",
        fname,
        len(body_rows) - 1,
        len(out_rows),
    )
    return hdr, out_cols, out_rows


def validate_output(
    out_cols: list[str],
    out_rows: list[dict[str, str]],
    fname: str,
    logger: logging.Logger,
) -> None:
    """Validate required output columns, ordering, uniqueness, and row conformance."""
    required_out = {COL_DATE, COL_SYMBOL, COL_QTY, COL_AVG_COST, COL_PRICE}
    missing = [c for c in required_out if c not in out_cols]
    if missing:
        raise FileValidationError(
            f"{fname}: Missing required output columns: {', '.join(missing)}"
        )
    if len(set(out_cols)) != len(out_cols):
        raise FileValidationError(f"{fname}: Duplicate output column names detected")
    if out_cols[:4] != LEADING_OUT_COLS:
        raise FileValidationError(
            f"{fname}: Invalid leading output column order {out_cols[:4]}"
        )

    expected_keys = set(out_cols)
    for idx, row in enumerate(out_rows, start=1):
        if set(row.keys()) != expected_keys or len(row) != len(out_cols):
            raise FileValidationError(
                f"{fname}: Output row {idx} does not conform to output header"
            )

    logger.debug(
        "%s: Output schema validated (%d columns, %d rows)",
        fname,
        len(out_cols),
        len(out_rows),
    )


def build_out_path(finfo: FnameInfo, hdr: HeaderInfo) -> Path:
    """Build destination path <stem>_<ACCT_TYPE>_<LAST3>_preprocessed.csv."""
    out_name = f"{finfo.path.stem}_{hdr.acct_name}_{hdr.last3}_{OUT_SUFFIX}.csv"
    return finfo.path.parent / out_name


def write_atomic(
    dest_path: Path,
    out_cols: list[str],
    out_rows: list[dict[str, str]],
    fname: str,
    logger: logging.Logger,
) -> bool:
    """Write CSV atomically via temp file + hard link; returns False if exists."""
    dest_dir = dest_path.parent
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=dest_dir,
            prefix=f".{dest_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp_file:
            tmp_path = Path(tmp_file.name)
            writer = csv.DictWriter(
                tmp_file,
                fieldnames=out_cols,
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(out_rows)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())

        os.link(tmp_path, dest_path)
        logger.debug("%s: Wrote output atomically to %s", fname, dest_path.name)
        return True
    except FileExistsError:
        logger.info("%s -- Output file already exists", fname)
        return False
    except OSError as exc:
        raise FileValidationError(
            f"{fname}: Failed writing output file '{dest_path.name}' ({exc})"
        ) from exc
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
                logger.debug("%s: Cleaned up temporary file %s", fname, tmp_path.name)
            except OSError as cleanup_exc:
                logger.warning(
                    "%s: Failed removing temporary file '%s' (%s)",
                    fname,
                    tmp_path.name,
                    cleanup_exc,
                )


def process_file(
    finfo: FnameInfo,
    provider: str,
    cfg: dict[str, Any],
    logger: logging.Logger,
) -> None:
    """Run the full per-file workflow for a candidate input file."""
    fname = finfo.path.name
    if provider == "Schwab":
        hdr, out_cols, out_rows = schwab_process(finfo, cfg, logger)
    else:
        raise FileValidationError(f"{fname}: Unsupported provider '{provider}'")

    dest_path = build_out_path(finfo, hdr)
    logger.debug("%s: Generated output filename -> %s", fname, dest_path.name)

    if dest_path.exists():
        logger.info("%s -- Output file already exists", fname)
        return

    validate_output(out_cols, out_rows, fname, logger)
    if write_atomic(dest_path, out_cols, out_rows, fname, logger):
        logger.info("%s", fname)


def run_pipeline(provider: str, work_dir: Path, verbosity: str) -> int:
    """Execute preprocessing across all matching CSV files in work_dir/provider."""
    logger = setup_logger(verbosity)
    try:
        cfg = init_provider(provider)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    in_dir = work_dir / provider
    logger.debug("Selected provider=%s, work_dir=%s, in_dir=%s", provider, work_dir, in_dir)
    logger.debug("Provider configuration=%s", cfg)

    try:
        candidates = find_inputs(in_dir, cfg, logger)
    except FileValidationError as exc:
        logger.error("%s", exc)
        return 1

    for finfo in candidates:
        try:
            process_file(finfo, provider, cfg, logger)
        except FileValidationError as exc:
            logger.error("%s", exc)

    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for provider, optional WORK_DIR, and --verbosity."""
    parser = argparse.ArgumentParser(
        description="Preprocess brokerage positions CSV files."
    )
    parser.add_argument(
        "provider",
        help="Brokerage provider name (currently supported: Schwab).",
    )
    parser.add_argument(
        "work_dir",
        nargs="?",
        default=None,
        help="Optional root working directory (defaults to current working directory).",
    )
    parser.add_argument(
        "--verbosity",
        choices=["LOG", "DEBUG"],
        default="LOG",
        help="Logging verbosity level (default: LOG).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = parse_args(argv)
    root_dir = Path(args.work_dir) if args.work_dir else Path.cwd()
    return run_pipeline(
        provider=args.provider,
        work_dir=root_dir,
        verbosity=args.verbosity,
    )


if __name__ == "__main__":
    raise SystemExit(main())

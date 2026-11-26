## Task: Develop a Brokerage Positions CSV Preprocessing Script You are an experienced Python

developer. Create a complete, executable Python script named
preprocess_positions_statements.py. The script must be reliable, easy to maintain, and
designed to support additional brokerage providers in the future.
Note: Please write the script carefully with all the details, as requirements have changed from
previous iterations. Provide the complete resulting script, not just a diff or partial changes.

## 1. Functional overview

The script processes one or multiple brokerage positions CSV files for a selected provider. For
each qualifying input file, it must:
- Validate the filename and file structure.
- Read and validate statement information.
- Apply provider-specific preprocessing rules.
- Generate a separate preprocessed CSV file.
- Continue to the next input file.
An error processing one file must not prevent processing other files. Currently, only Schwab is
supported. The architecture must allow adding providers such as Fidelity and Interactive
Brokers without rewriting generic processing procedures.

## 2. Input parameters and directory structure

The script accepts the following command-line parameters:
- Provider (required): The brokerage provider name. Currently supported: Schwab.
- WORK_DIR (optional): The root working directory. If omitted, default to the current
working directory. Input and output files are located in WORK_DIR/Provider.
- Verbosity (optional): Controls the amount of information printed during execution.
Supported levels:
  - LOG (default): Print the filename of each processed input file. Print concise,
descriptive error and warning messages when issues occur.
  - DEBUG: Print all LOG-level information plus detailed diagnostic information
about the processing workflow, including important configuration values, parsed
statement information, filenames, column mappings, intermediate calculations,
and validation results.
DEBUG output must not change processing behavior. Use Python's standard logging module or
an equivalent structured logging implementation.

## 3. Global constants and provider configuration

Declare global constants for application-wide values:
OUT_SUFFIX = "preprocessed"
COL_DATE = "Date"
COL_SYMBOL = "Symbol"
COL_QTY = "Quantity"
COL_PRICE = "Price"
COL_AVG_COST = "Avg Cost"
CASH_SYMBOL = "$CASH"
PROVIDER_CONFIG = {
# Provider-specific configuration.
# First-level key: Provider name.
# Second-level keys: descriptive configuration parameter names.
}
Add other global constants when appropriate.
Provider configuration structure Use a two-level dictionary:
- First-level key: provider name.
- Second-level keys: descriptive configuration parameter names.
- Values: provider-specific filename patterns, regular expressions, source column names,
account types, excluded symbols, cash labels, and other provider-specific settings.
All provider-specific configuration must reside in PROVIDER_CONFIG. Do not duplicate
application-wide constants in provider configurations. For example, $CASH is a common
application constant, not a provider-specific setting.
Initialization Implement:
def init_provider(provider):
The procedure must:
- Validate that the requested provider is supported.
- Return the corresponding provider-specific configuration dictionary.
- Raise a descriptive error for unsupported providers.
- Not assign configuration values to global variables.
Configuration usage and variable scope
- Generic and provider-specific processing procedures must receive the selected provider
configuration as a parameter.
- Each procedure extracts the configuration values it needs into local variables.
- Do not use global variables for provider-specific configuration values or per-file
processing data.
- Keep the provider configuration read-only during processing.

## 4. Naming conventions and code organization

- Use meaningful, descriptive, human-readable names for procedures, constants, and
variables.
- Prefer names up to 15 characters where practical. Do not sacrifice clarity merely to
shorten names.
- Use these naming rules:
  - Generic reusable procedures: descriptive generic names.
  - Schwab-specific procedures: prefix with schwab_.
  - Future provider-specific procedures: use the corresponding provider prefix.
- Keep generic procedures as generic as reasonably possible.
- Only Schwab-specific parsing and transformation rules should reside in Schwab-specific
procedures.
- Avoid unnecessary abstraction, duplication, and object-oriented complexity.
- The resulting code must be understandable and maintainable by an experienced Python
developer.

## 5. File discovery and filename validation

The script searches for matching CSV files in:WORK_DIR/Provider The filename pattern must
be provider-specific and defined in PROVIDER_CONFIG.
Current Schwab filename patternAAAAA-Positions-YYYY-MM-DD-HHMMSS.csv Where:
- AAAAA: Account name.
- YYYY-MM-DD: Statement date.
- HHMMSS: Six-digit statement timestamp.
Important: Validate the filename pattern and the calendar validity of its date. Only matching files are candidates for
processing. Sort matching input files by filename before processing.
Output filename For each input file, generate the output filename
using:INPUT_FILENAME_WITHOUT_EXTENSION_ACCOUNT_TYPE_LAST3_preprocessed.c
sv Where:
- INPUT_FILENAME_WITHOUT_EXTENSION: Original input filename without .csv.
- ACCOUNT_TYPE: Account type parsed from the statement header.
- LAST3: Last three digits of the account number parsed from the statement header.
Example:Individual-Positions-2026-11-18-123456.csv becomes:Individual-
Positions-2026-11-18-123456_Individual_358_preprocessed.csv

## 6. Processing workflow for each input file

Follow this sequence for each matching file:

## 1. Read the input CSV.

## 2. Parse and validate the statement header.

## 3. Extract account type, last three account-number digits, and statement date.

## 4. Validate that the account type and statement date in the filename agree with the

corresponding values in the statement header.

## 5. Generate the destination filename.

## 6. Check whether the destination file already exists.

## 7. If it exists, skip processing and print:INPUT_FILENAME -- Output file already exists

## 8. Validate the CSV structure and required columns.

## 9. Apply the provider-specific preprocessing rules.

## 10. Validate the resulting output structure.

## 11. Write the output atomically, without overwriting an existing file.

## 12. Print the processed input filename.

If a file fails validation, print a descriptive error and proceed to the next input file. The existence
of an output file must not be treated as an error.

## 7. Schwab-specific preprocessing rules

All rules in this section apply exclusively to Schwab. Other providers will have their own parsing,
column definitions, and transformation rules.

### 7.1 Schwab-specific configuration

Define the following values in the Schwab section of PROVIDER_CONFIG:
- Input filename pattern and regular expression.
- Statement header pattern and regular expression.
- Source CSV column names.
- Excluded security symbols.
- Cash row identification labels.
- Bond identification and normalization parameters.
The excluded security symbol list must initially be empty:
"excluded_symbols": []
Store it in the provider configuration so it can be easily modified.
For Bond normalization, include the following values in PROVIDER_CONFIG["Schwab"]:
- Description source column name: "Description"
- Asset Type source column name: "Asset Type"
- Bond description substrings list: ["US TREASURIES "] (a list of strings used to identify
bonds; initially containing "US TREASURIES ").
- Bond asset type: "Fixed Income"
- Bond Price divisor: 100
- Bond substring matching behavior (case-insensitive or exact substring matching, as
configured).
All these values must remain inside the Schwab configuration block. Do not hardcode them
inside generic processing procedures.

### 7.2 Parse the first CSV record

The first physical line of the Schwab input file contains a statement description similar
to:Positions for account Individual ...358 as of 05:36 AM ET, 2026/11/18 Expected
pattern:Positions for account AAAAA ...NNN as of HH:MM AM/PM ET, YYYY/MM/DD Extract:
- AAAAA: Account name ( alphanumeric string)
- NNN: Last three digits of the account number.
- YYYY/MM/DD: Statement date.
The comma following ET is unquoted in the source CSV. Consequently, a standard CSV reader
may split this physical line into multiple fields. Handle this situation robustly. Reconstruct and
parse the complete first physical line without accidentally treating the comma as a new record or
losing part of the date. Validate the time, account type, and calendar date. Convert the parsed
statement date to YYYY-MM-DD for output. Retain the parsed information locally for processing
the current file.

### 7.3 Remove header and footer records

Remove the first two CSV records. Remove the final CSV record. The first remaining record is
the actual positions column header. Validate that the file contains sufficient records before
performing these operations.
Empty / Blank Header Columns Brokerage CSV exports (including Schwab) can contain trailing
commas or blank/unnamed columns with no header text and no position values (or only
missing/blank values) across rows.
  - Identify columns whose header cell is empty or whitespace-only after trimming.
  - If such a column has no non-empty data values in any position row (or only whitespace/
missing tokens such as "--" or "N/A"), treat it as an empty/unlabelled filler column rather than
failing the file with an empty column header error.
  - Log a DEBUG message noting ignored empty columns (including their positions and whether
any non-empty values were found).
  - If an unnamed/empty column contains actual non-missing data values in position rows, either
treat it as a structural error
  - Ensure ignored empty columns are excluded from column mappings, output headers, and row-
length checks (after verifying no extra non-empty fields exist beyond the expected row width).

### 7.4 Validate and transform columns

Apply the following transformations:
Date
- Add a new leftmost column named Date.
- Populate every output position row with the statement date in YYYY-MM-DD format.
Quantity
- Rename Qty (Quantity) to Quantity.
Excluded securities
- Remove position rows whose Symbol is in the configured excluded-symbol list.
- The excluded-symbol list must initially be empty.
Worthless equities
- Remove all rows where Price has the value "N/A".
- Add the following explanatory comment in the code:
# Schwab uses "N/A" to mark worthless equities.
# We exclude these positions from the Wealthfolio import.
- 
Treat this as a separate filtering rule from excluded-symbol filtering.
- Handle whitespace around the value safely.
Cash position Identify the row whose original Symbol value is:Cash & Cash Investments Apply
these transformations:
- Change Symbol to $CASH.
- Move the value from Mkt Val (Market Value) into Quantity.
- Set Price to 1.
- Set Mkt Val (Market Value) to blank.
- Do not calculate Avg Cost for this row.
Bond position normalization Note: Bond normalization rules are provider-specific (other
providers may have their own rules). For Schwab, identify Bond rows satisfying BOTH
conditions:

## 1. Description contains any member of the configured bond substrings list (e.g., "US

TREASURIES ") verbatim (using configured case-insensitive or exact substring
matching).

## 2. Asset Type equals "Fixed Income".

Use the corresponding column names, substring list, asset type, price divisor, and matching
behavior from PROVIDER_CONFIG["Schwab"].
Apply the following transformations exclusively to qualifying Bond rows:
- Quantity: Leave Quantity unchanged (pass as-is, with no multiplier or divisor).
- Price: Schwab represents bond prices based on $100 face value, whereas we need to
express them as fractions of 1 (e.g., $68.01 becomes 0.6801). Divide Price by the
configured Bond Price divisor (100).
  - Requirements:
    - Use Python Decimal for arithmetic.
    - Use the configured Bond Price divisor (100).
    - Avoid binary floating-point arithmetic.
    - Preserve decimal precision without unnecessary rounding or truncation.
    - Use conventional numeric formatting suitable for CSV output.
- Average Cost: Add a column named Avg Cost.
  - For all positions other than $CASH (including qualifying Bond positions, since
there is no Quantity multiplier), calculate:
𝐶𝑜𝑠𝑡𝐵𝑎𝑠𝑖𝑠
  - 𝐴𝑣𝑔𝐶𝑜𝑠𝑡 =
𝑄𝑢𝑎𝑛𝑡𝑖𝑡𝑦
  - Requirements:
    - Use Python Decimal for calculations.
    - Round to up to 3 decimal places if any (i.e., round to at most 3 decimal
places using conventional financial rounding ROUND_HALF_UP, without
padding unnecessary trailing zeros).
    - If Cost Basis or Quantity is missing, invalid, or zero, leave Avg Cost blank.
    - Do not generate NaN or Infinity.
    - Do not allow division-by-zero errors.
    - Do not calculate Avg Cost for $CASH.
Column ordering Arrange the output columns so that the four leftmost columns appear in this
exact order:Date, Symbol, Quantity, Avg Cost Followed by all remaining columns (including
Price, etc.) in their preserved relative order.

### 7.5 Numeric data normalization

Brokerage CSV rows may contain values such as:
- $1,234.56
- 1,234.56
- --
- 0
For numeric fields:
- Remove $ currency symbols.
- Remove thousands-separator commas.
- Treat --, blank values, and other configured missing-value indicators as missing.
- Parse valid values numerically.
- Do not retain currency symbols or thousands separators in numeric output fields.
- Preserve negative values.
- Handle zero quantities and zero cost basis correctly.
- Do not silently convert invalid values into zero.
- For invalid or missing numeric values, preserve the distinction between zero and
missing.
- Use Decimal for financial calculations and Bond Price normalization.

### 7.6 Output column validation

Verify that the resulting output contains:
- Date
- Symbol
- Quantity
- Avg Cost
- Price
Also verify:
- No duplicate column names.
- No unexpected duplicate output fields.
- Correct column ordering, with the four leftmost columns in the exact sequence: Date,
Symbol, Quantity, Avg Cost, followed by the remaining columns.
- All output rows conform to the output header.

## 8. Validation and error handling

Implement both file-level and row-level validation.
File-level errors Examples:
- Empty input file.
- Invalid filename.
- Invalid statement header.
- Invalid statement date.
- Account type mismatch between filename and header.
- Statement date mismatch between filename and header.
- Insufficient CSV records.
- Duplicate source column names.
- Missing required source columns.
- Missing required output columns.
- Malformed CSV structure.
If a file-level validation error occurs:
- Do not generate an output file.
- Print a concise, descriptive error.
- Continue processing the next input file.
Row-level issues Some problems should not invalidate the entire statement. Examples:
- Missing numeric values.
- Invalid numeric values.
- Zero quantity when calculating average cost.
- Missing cost basis.
- Malformed data rows.
- Unexpected extra nonempty fields.
When a row-level issue occurs:
- Print a concise, descriptive warning.
- Include the relevant security Symbol whenever available.
- Identify the problem.
- Continue processing other rows.
- Do not generate misleading financial values to replace missing or invalid information.
- Distinguish between recoverable row-level issues and structural errors that make the
entire file unreliable.
Additional Bond validation
- For qualifying Bond rows, if Price cannot be converted or normalized reliably, issue a
row-level warning identifying the security whenever possible.
- If Cost Basis or Quantity is missing, invalid, or zero, retain the row when otherwise valid,
leave Avg Cost blank, and issue a warning.

## 9. Output file safety and integrity

These requirements are mandatory.
Existing destination protection
- Never overwrite an existing output file.
- If the destination already exists, skip processing and print:INPUT_FILENAME -- Output
file already exists
- Protection must also cover race conditions where another process creates the
destination after the initial existence check.
- The final destination must be created atomically using a method that fails if the
destination already exists.
Atomic output writing
- Do not write directly to the final destination.
- Instead:

## 1. Create a temporary file in the same directory as the destination.

## 2. Write the complete CSV output to the temporary file.

## 3. Flush and synchronize the file.

## 4. Atomically create the final destination without replacing an existing file.

## 5. Remove the temporary file after successful creation or failure.

- An interrupted or failed run must never leave a partially written final CSV.

## 10. Logging and diagnostic output

At LOG verbosity:
- Print the input filename after successful processing.
- Print the input filename with the existing-output suffix when skipped.
- Print concise, descriptive errors and warnings.
- Identify the affected security Symbol for row-level issues whenever possible.
At DEBUG verbosity, additionally print important diagnostic information, including:
- Selected provider and configuration.
- Input directory and discovered files.
- Filename validation results.
- Parsed statement information.
- Generated output filename.
- Source and output column mappings.
- Row counts.
- Excluded securities.
- Rows excluded because Price is "N/A".
- Cash position identification and conversion.
- Bond position identification and normalization, including unchanged Quantity, original
Price, normalized Price, and calculated Avg Cost.
- Numeric conversion and calculation diagnostics.
- Validation results.
- Output-writing status.
Do not print unnecessary details at LOG level.

## 11. Code quality and reliability requirements

- Use Python standard-library modules wherever practical.
- Use Decimal for financial calculations.
- Use descriptive procedure and variable names.
- Keep generic and provider-specific logic separate.
- Avoid unnecessary global variables.
- Do not store per-file processing information in global variables.
- Do not modify global provider configuration during processing.
- Pass the provider configuration explicitly to processing procedures.
- Each procedure should extract only the configuration values it needs into local variables.
- Handle errors independently for each input file.
- Clean up temporary files after failures.
- Do not silently ignore structural errors.
- Avoid unnecessary code duplication.
- Use clear docstrings for procedures.
- Make the script executable.
- The code should be functionally complete, not pseudocode or a partial implementation.

## 12. Testing requirements

Before delivering the script:
- Verify Python syntax and imports.
- Test successful processing of a representative Schwab statement.
- Test the unquoted comma in the first statement line.
- Test filename/header date and account-type mismatches.
- Test missing and duplicate columns.
- Test excluded symbols with the initially empty list and with explicitly configured symbols.
- Test exclusion of rows where Price is "N/A".
- Test cash conversion.
- Test Bond identification using both Description (substring match against configured bond
list) and Asset Type ("Fixed Income").
- Test case-insensitive or exact Bond substring matching according to configuration.
- Test that non-Bond Fixed Income positions are not normalized.
- Test that other asset classes are not normalized.
- Test that Bond Quantity remains unchanged.
- Test Bond Price division by 100 using Decimal (e.g., $68.01 -> 0.6801).
- Test Bond Avg Cost calculation using Cost Basis / Quantity.
- Test missing, invalid, and zero Bond Quantity, Price, and Cost Basis.
- Test $, commas, --, missing values, zero quantities, and zero cost basis.
- Test average-cost rounding (up to 3 decimal places if any) and negative quantities.
- Test column ordering (Date, Symbol, Quantity, Avg Cost as the leftmost columns).
- Test malformed data rows and extra fields.
- Test existing output protection, including a destination-creation race condition.
- Test atomic output cleanup after a simulated failure.
- Test that one bad input file does not stop processing subsequent files.
- Test LOG and DEBUG verbosity.
- Do not claim tests have passed unless they have actually been executed.

## 13. Future extensibility

The script will eventually support additional providers, including Fidelity and Interactive Brokers.
When adding a provider, the intended changes should be limited to:
- Adding its provider-specific configuration to PROVIDER_CONFIG.
- Adding provider-specific parsing and transformation procedures.
- Registering its processing procedure with the generic application workflow.
Do not introduce provider-specific constants or assumptions into generic procedures. The
existing generic file discovery, validation framework, logging, atomic writing, and error-handling
infrastructure should be reusable.

## 14. Final deliverables

Provide:
- The complete executable file preprocess_positions_statements.py.
- A concise explanation of the architecture.
- A list of significant implementation decisions.
- Any assumptions made where the specification is ambiguous.
- A summary of tests actually executed and their results.
Prioritize correctness, financial data integrity, readability, and maintainability over minimizing the
number of lines of code.

## 15. Extra design decisions

## 1. Malformed rows Suppose a row has an extra nonempty field or an invalid number in

Cost Basis.
  - Extra fields: reject the entire file if the CSV structure is inconsistent.
  - Invalid Cost Basis: retain the row, leave Avg Cost blank, and issue a warning.
This protects the integrity of the output without unnecessarily discarding valid
positions.

## 2. Missing Symbol Treat a missing Symbol as a row-level error and skip that row. Without

a symbol, the position cannot be reliably identified.

## 3. Code optimization If there are inefficiencies such as redundancies, unnecessary

repetitions, or complexities in the script, optimize the code. Remove the inefficiencies
without affecting functionality. It is very important that the functionality is not affected. If
no optimization is needed, state so explicitly.

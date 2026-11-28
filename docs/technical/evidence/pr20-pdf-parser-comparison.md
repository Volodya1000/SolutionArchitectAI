# PR 20 PDF parser comparison

Measured on 2026-11-28, Windows, Python 3.13.9. Both tools processed the same
original [example PDF](../../pdf/example.pdf) and [BRD](../../pdf/brd.pdf).
[Machine-readable measurements](pr20-pdf-parser-comparison.json) include original
SHA-256 values, exact cells, headers, page provenance, bounding boxes, versions,
and timing. This experiment does not change the application parser or lockfile.

## Actual runs

| Source | Current pypdf 6.21.4 | Isolated Docling 2.154.0 |
| --- | --- | --- |
| example.pdf, 13 pages | 0.389 s; 526 line fragments | 50.725 s; success; 16 tables |
| brd.pdf, 15 pages | 0.517 s; 701 line fragments | 30.495 s; success; 11 tables |

These are single local runs, not statistical performance claims. pypdf includes
current layout extraction and fragment construction. The first Docling conversion
includes model initialization; the second reuses loaded models. Cold Python
imports, installation, visual rendering, and report generation are outside the
conversion timings. Docling used CPU, four threads, OCR disabled, TableFormer
accurate with cell matching enabled, and a 120 s document timeout.
Electricity cost and hardware amortization were not measured; monetary cost
cannot be inferred from the absence of paid API calls.

Docling's process peak working set was 1,965,862,912 bytes (about 1.83 GiB), measured
with Windows `psutil.Process().memory_info().peak_wset`. The isolated environment
has 1,116,117,717 apparent file bytes; that is not a unique physical-disk allocation
measurement because uv may reuse cached package data. Installation resolved 108
packages, prepared 64 downloads in 44.00 s, and installed in 25.71 s. No paid API
calls, GPU inference, or new model downloads were used. Existing cached Heron
layout and TableFormer weights were reused with `HF_HUB_OFFLINE=1` and
`TRANSFORMERS_OFFLINE=1`. Nothing was moved or deleted from shared caches.

## R-04 and table quality

The rendered example page 2 was visually inspected. R-04 is one requirement cell
with four wrapped visual lines. The existing parser creates
`page/2/line/41` through `page/2/line/44`. Only the first carries the R-04 ID;
continuations have no row identity or column-header association. The final
out-of-window rejection sentence is present, split across lines 43 and 44.
This is a structural limitation, not loss of that sentence's characters.

Docling reconstructs a 10 by 2 table with `ID` and `Требование` marked as column
headers. R-04 occupies zero-based row 4: its ID is column 0 and its complete
requirement is column 1, including empty-summary behavior and out-of-window
rejection. Joining the four pypdf lines after removing the ID and trimming their
layout padding produces exactly the same text as the Docling requirement cell.
The Docling cell is not an exact substring of any one current pypdf fragment.

The requirement cell has page provenance 2 and bounding box
`l=180.317, t=497.489, r=536.289, b=540.131`, origin `TOPLEFT`, in PDF points.
The table's provenance box uses `BOTTOMLEFT`; an adapter must preserve or normalize
that origin explicitly. Current SourceLocator/SourceRef stores page and path,
without a coordinate field. It cannot claim to preserve these boxes today.

The rendered BRD page 8 was also visually inspected. pypdf interleaves the three
columns of the artifact-creation table into text lines, for example
`page/8/line/19` contains fragments from all three columns. Docling reconstructs
that 6 by 3 table with headers `Этап`, `Создаются`, and `Дополняются`, retaining
the full FR-04 stage cell and its separate output/update cells. This is a useful
improvement on these two inspected tables; the experiment does not establish
perfect extraction across every table, merged cell, scan, or future PDF.

## SourceRef compatibility and regression

The new `test_pdf_source_compatibility.py` regression passes with the current
parser. It verifies all four R-04 line quotes, original version/SHA, page 2,
source paths, and the saved first-fragment UUID
`fdaab787-9950-59ce-8885-3c68ba13daa9` for its fixed version namespace. A combined
multiline quote against only the first line stays `unverified` with
`quote_not_in_context`, preserving the exact-source contract.

Replacing current saved fragments with Docling cells would change text boundaries,
locators, and deterministic IDs and would invalidate existing exact quotes.
A future integration needs a separate parser version, retained legacy saved
parses/references, explicit page-plus-table/row/column identities, and typed box
coordinates with origin. Cell text can support new references after validation;
it must not silently replace an older line reference. No such migration was made.

Validation commands:

- `uv run --locked --project backend pytest backend/tests/unit/test_pdf_source_compatibility.py -q`:
  **1 passed**, 1.01 s.
- Ruff and strict Mypy on that new regression: **passed**.
- Both actual isolated Docling conversions: **success**.

## Environment issues and reproduction

The first PyPI request through inherited proxy variables failed after three
retries: `tunnel error: failed to create underlying connection`, TCP connection
refused (`os error 10061`). Retrying with `HTTP_PROXY`, `HTTPS_PROXY`, and
`ALL_PROXY` removed only in the child PowerShell process succeeded. Global proxy
settings were not changed. Initial imports were slow in Python's
`importlib._write_atomic` bytecode-cache writes (confirmed by faulthandler);
restarting this experiment with process-local `PYTHONDONTWRITEBYTECODE=1` completed.

The isolated setup was:

```powershell
uv venv --python 3.13 .build/pdf-experiment/.venv
Remove-Item Env:HTTP_PROXY,Env:HTTPS_PROXY,Env:ALL_PROXY -ErrorAction SilentlyContinue
uv pip install --python .build/pdf-experiment/.venv/Scripts/python.exe docling==2.154.0
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
```

The conversion uses `DocumentConverter` with a `PdfFormatOption` and
`PdfPipelineOptions(do_ocr=False, do_table_structure=True, document_timeout=120)`,
plus `AcceleratorOptions(num_threads=4, device=AcceleratorDevice.CPU)`, then
`converter.convert(source)` and `result.document.model_dump_json()` for each PDF.
This follows the [official pipeline options](https://docling-project.github.io/docling/reference/pipeline_options/).
The local `.build/pdf-experiment` directory retains the probe scripts, full
Docling JSON/Markdown, current pypdf text, measurements, and rendered inspected
pages. Docling remains outside application dependencies.

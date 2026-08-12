# IRIS â€” traceable spend leakage analysis

IRIS is a Streamlit app for analysing a CSV export in the current browser
session. It maps non-standard column names, scans the data immediately, and
shows the vendor, invoice/reference, source-row number, rule, and calculation
behind every result.

## Run it

Use Python 3.10 through 3.13 (3.12 is a good deployment default).

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
streamlit run app.py
```

Open the local URL printed by Streamlit, then upload a CSV. Select **Open
included demo** to verify the installed app before using company data.

## What the app accepts

The loader accepts UTF-8, UTF-8 with BOM, Windows-1252, and Latin-1 CSV text,
and automatically detects comma, tab, semicolon, and pipe delimiters. It does
not require a fixed template: use **Review column mapping** to select the
actual amount, vendor, invoice/reference, date, contract, quantity, PO, and
other fields in an export.

A file without a usable monetary column still loads and exposes its data
profile, but IRIS will not invent a currency leakage total. Stronger evidence
comes from an amount field plus vendor, invoice/reference, and contracted
price fields.

## What the totals mean

IRIS deliberately separates outcomes:

| Outcome | Included in confirmed leakage? | Evidence |
| --- | --- | --- |
| Redundant duplicate payment | Yes | Extra payment rows sharing an invoice/reference, vendor, and amount |
| Billed above a mapped contract amount/rate | Yes | Invoice amount minus the mapped contractual value (and quantity where applicable) |
| Unit-price outlier | No | Peer benchmark candidate; validate the service, units, and contract first |
| No PO, off-contract status, or inactive service | No | Control or waste-review exposure, not proof of financial loss |

Duplicate-copy value takes priority when an item also appears to be over
contract, so the confirmed headline avoids counting the same payment twice.
Download the evidence CSV before sharing results externally.

## Demo acceptance check

With `demo_portco_leakage.csv` and the auto-detected mappings, the expected
results are:

- Spend analysed: **$5,620,000**
- Confirmed, non-overlapping leakage: **$1,400,000**
  - $1,050,000 redundant duplicate payments
  - $350,000 billed above contracted amount

Every amount should link to its original CSV source row in the evidence table.

## “Live” behaviour and scope

The CSV scan is live within the app: it reruns as soon as the upload, mapping,
or thresholds change. A CSV is a point-in-time export; it is not an ERP
webhook or a continuous bank-feed connector. Production continuous monitoring
needs a separately authorised connector with tenant isolation, secure token
storage, refresh/retry logic, audit logs, and a stated polling/webhook cadence.

## Data handling and deployment

- Uploads are processed in memory for the current Streamlit session. The root
  app does **not** write uploaded finance data to SQLite.
- Do not commit or deploy `iris_data.db`; it is a legacy local artifact kept
  here untouched pending review of its contents.
- Do not commit Streamlit secrets or OAuth credentials. Use the deployment
  platform's secret manager, and rotate any credential that was previously
  committed.
- Put authentication, company-level authorization, encryption/retention
  controls, and logging in front of any public or multi-company deployment.

## Test

After installing the development requirements:

```powershell
pytest -q
```

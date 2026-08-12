"""Evidence-first spend leakage analysis for CSV exports.

The module is intentionally conservative.  A CSV can prove that the same
invoice was recorded more than once, or that a row exceeds an applicable
contract value.  It cannot, by itself, prove every operational concern is a
cash loss.  For that reason the result separates direct, non-overlapping
leakage from price estimates and control-risk spend.
"""

from __future__ import annotations

import csv
import io
import math
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd


CANONICAL_FIELDS = (
    "amount",
    "vendor",
    "invoice",
    "date",
    "contract_value",
    "quantity",
    "unit_price",
    "po",
    "contract_status",
    "last_activity",
    "description",
    "category",
)

_FINDING_COLUMNS = [
    "finding_id",
    "finding_type",
    "classification",
    "leakage_amount",
    "source_row",
    "source_index",
    "related_source_rows",
    "vendor",
    "invoice",
    "purchase_order",
    "transaction_date",
    "amount",
    "contract_value",
    "quantity",
    "unit_price",
    "reason",
    "evidence",
    "confidence",
]

_SOURCE_COLUMNS = [
    "finding_type",
    "classification",
    "leakage_amount",
    "finding_count",
    "evidence_source",
]

_MISSING_TEXT = {"", "-", "--", "n/a", "na", "none", "null", "nan", "unknown", "not available"}


@dataclass
class AnalysisResult(Mapping[str, Any]):
    """Result shape accepted directly by :mod:`ui` and by dict-based callers."""

    summary: dict[str, Any]
    findings: pd.DataFrame
    source_breakdown: pd.DataFrame
    schema: dict[str, Any]
    warnings: list[str]

    def as_dict(self) -> dict[str, Any]:
        result = {
            "summary": self.summary,
            "findings": self.findings,
            "source_breakdown": self.source_breakdown,
            "schema": self.schema,
            "warnings": self.warnings,
        }
        # This makes both result["confirmed_leakage"] and result.summary work.
        result.update(self.summary)
        return result

    def __getitem__(self, key: str) -> Any:
        return self.as_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.as_dict())

    def __len__(self) -> int:
        return len(self.as_dict())


def load_csv_bytes(payload: bytes) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load a CSV export despite common encoding and delimiter variations.

    Values remain in their original form so the column profiler can distinguish
    identifiers from money.  Monetary normalization happens only after a field
    has been selected as a monetary field.
    """

    if isinstance(payload, memoryview):
        payload = payload.tobytes()
    elif isinstance(payload, bytearray):
        payload = bytes(payload)
    if not isinstance(payload, bytes) or not payload.strip():
        raise ValueError("The uploaded CSV is empty or could not be read as bytes.")

    encodings: list[str] = ["utf-8-sig", "utf-8"]
    if payload.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in payload[:200]:
        encodings.extend(["utf-16", "utf-16-le", "utf-16-be"])
    encodings.extend(["cp1252", "latin-1"])

    decoded: Optional[str] = None
    encoding_used: Optional[str] = None
    for encoding in dict.fromkeys(encodings):
        try:
            candidate = payload.decode(encoding)
        except UnicodeDecodeError:
            continue
        # A wrong UTF-16 decoder can technically succeed while producing mostly
        # NUL characters.  Do not use that result.
        if candidate.count("\x00") > max(2, len(candidate) // 20):
            continue
        decoded, encoding_used = candidate, encoding
        break
    if decoded is None:
        raise ValueError("The file encoding could not be decoded as a CSV export.")

    sample = "\n".join(line for line in decoded.splitlines()[:30] if line.strip())
    delimiters = [",", ";", "\t", "|"]
    try:
        sniffed = csv.Sniffer().sniff(sample, delimiters="".join(delimiters)).delimiter
        delimiters = [sniffed] + [item for item in delimiters if item != sniffed]
    except (csv.Error, TypeError):
        pass

    parsed: list[tuple[float, str, pd.DataFrame]] = []
    for delimiter in delimiters:
        try:
            frame = pd.read_csv(
                io.StringIO(decoded),
                sep=delimiter,
                engine="python",
                dtype=object,
                skipinitialspace=True,
                on_bad_lines="skip",
            )
        except (pd.errors.ParserError, UnicodeError, ValueError):
            continue
        if frame.empty and len(frame.columns) == 0:
            continue
        header_text = " ".join(str(column).lower() for column in frame.columns)
        useful_headers = sum(
            token in header_text
            for token in ("amount", "vendor", "supplier", "invoice", "date", "price", "cost", "contract")
        )
        # A wrong delimiter nearly always yields one giant column.  Keep a
        # one-column export viable, but prefer a structured parse when present.
        score = float(len(frame.columns) * 10 + useful_headers * 4 + min(len(frame), 1_000) / 1_000)
        if len(frame.columns) == 1:
            score -= 20
        parsed.append((score, delimiter, frame))

    if not parsed:
        raise ValueError("No readable rows were found in the uploaded CSV.")
    _, delimiter_used, data = max(parsed, key=lambda item: item[0])
    data = data.copy()
    data.columns = _unique_clean_columns(data.columns)
    data = data.dropna(axis=1, how="all")

    warnings: list[str] = []
    if len(data.columns) == 1:
        warnings.append("The file appears to contain one column; structured leakage checks will be limited.")
    if encoding_used not in {"utf-8", "utf-8-sig"}:
        warnings.append(f"Imported using {encoding_used}; verify any unusual characters in the data preview.")
    metadata = {
        "encoding": encoding_used,
        "delimiter": "tab" if delimiter_used == "\t" else delimiter_used,
        "rows_loaded": int(len(data)),
        "columns_loaded": int(len(data.columns)),
        "warnings": warnings,
    }
    data.attrs["iris_import"] = metadata
    return data, metadata


def infer_schema(df: pd.DataFrame) -> dict[str, Any]:
    """Infer flexible field roles from headers and lightweight value checks."""

    if not isinstance(df, pd.DataFrame):
        raise TypeError("infer_schema expects a pandas DataFrame.")

    columns = [str(column) for column in df.columns]
    scores: dict[str, list[tuple[float, str]]] = {field: [] for field in CANONICAL_FIELDS}
    for column in columns:
        name = _normalise_name(column)
        series = df[column]
        for field in CANONICAL_FIELDS:
            score = _field_score(field, name, series)
            if score > 0:
                scores[field].append((score, column))

    inferred: dict[str, Optional[str]] = {field: None for field in CANONICAL_FIELDS}
    # Some names are naturally ambiguous (for example, a contracted rate is
    # also a rate).  This order keeps the more specific contractual role.
    assignment_order = (
        "amount",
        "vendor",
        "invoice",
        "date",
        "contract_value",
        "quantity",
        "unit_price",
        "po",
        "contract_status",
        "last_activity",
        "description",
        "category",
    )
    used: set[str] = set()
    confidence: dict[str, float] = {}
    for field in assignment_order:
        ranked = sorted(scores[field], key=lambda item: item[0], reverse=True)
        candidate = next(((score, column) for score, column in ranked if column not in used), None)
        if candidate is None:
            continue
        score, column = candidate
        # Weak generic matches such as a lone "total" should not silently
        # become financial fields.
        minimum = 42 if field in {"amount", "contract_value", "unit_price"} else 35
        if score < minimum:
            continue
        inferred[field] = column
        confidence[field] = round(float(score), 1)
        used.add(column)

    contract_column = inferred["contract_value"]
    contract_name = _normalise_name(contract_column or "")
    has_quantity = inferred["quantity"] is not None
    explicit_unit_rate = any(
        phrase in contract_name
        for phrase in ("unit rate", "unit price", "per unit", "price per", "rate per", "unit cost")
    )
    # "Contracted_Rate" without a quantity is commonly a per-invoice agreed
    # value.  Treat it as a unit rate only when the header says so or quantity
    # evidence makes that interpretation supportable.
    contract_is_unit_rate = bool(
        contract_column
        and (explicit_unit_rate or (has_quantity and any(word in contract_name for word in ("rate", "price", "cost"))))
    )

    field_roles = {column: field for field, column in inferred.items() if column}
    warnings: list[str] = []
    if inferred["amount"] is None:
        warnings.append("No dependable transaction amount field was identified.")
    if inferred["invoice"] is None:
        warnings.append("No invoice/reference field was identified; duplicate checks require exact full-row matches.")
    if contract_column and "rate" in contract_name and not has_quantity and not contract_is_unit_rate:
        warnings.append(
            f"{contract_column!r} is treated as a per-transaction contract value because no quantity field was found."
        )

    schema: dict[str, Any] = {
        **inferred,
        "contract_is_unit_rate": contract_is_unit_rate,
        "field_roles": field_roles,
        "field_confidence": confidence,
        "amount_column": inferred["amount"],
        "spend_column": inferred["amount"],
        "warnings": warnings,
    }
    return schema


def analyze_dataframe(
    df: pd.DataFrame,
    mapping: Optional[Mapping[str, Any]] = None,
    *,
    inactive_days: int = 90,
    price_threshold: float = 0.15,
    progress_callback: Optional[Callable[..., Any]] = None,
) -> AnalysisResult:
    """Analyse a dataframe and return evidence-backed, investor-safe results.

    ``confirmed_leakage`` contains only non-overlapping duplicate-payment excess
    and directly calculable contract overages.  Price comparisons are estimates;
    inactive or off-contract records are control-risk spend, not asserted loss.
    """

    if not isinstance(df, pd.DataFrame):
        raise TypeError("analyze_dataframe expects a pandas DataFrame.")
    data = df.copy(deep=False)
    _progress(progress_callback, "Profiling uploaded fields", 8)
    schema, schema_warnings = _apply_mapping(data, mapping)
    warnings = list(dict.fromkeys(schema_warnings))

    if data.empty:
        warnings.append("The uploaded file contains headers but no data rows.")
        schema["warnings"] = warnings
        return AnalysisResult(
            summary=_summary(None, 0.0, 0.0, 0.0, 0.0, 0, 0),
            findings=_empty_findings(),
            source_breakdown=_empty_sources(),
            schema=schema,
            warnings=warnings,
        )

    amount_column = schema.get("amount")
    amount = _money_series(data[amount_column]) if amount_column else pd.Series(np.nan, index=data.index, dtype=float)
    amount_is_derived = False
    if amount_column is None and schema.get("unit_price") and schema.get("quantity"):
        amount = _money_series(data[schema["unit_price"]]) * _number_series(data[schema["quantity"]])
        amount_is_derived = True
        warnings.append("Transaction amounts were derived from unit price × quantity; verify the selected fields.")

    valid_amount = amount.notna() & np.isfinite(amount)
    positive_amount = valid_amount & (amount > 0)
    if amount_column and valid_amount.mean() < 0.55:
        warnings.append(
            f"Only {valid_amount.mean():.0%} of values in {amount_column!r} parsed as money; review the import mapping."
        )
    if not valid_amount.any():
        warnings.append("No usable monetary values were available, so currency totals cannot be calculated.")

    row_positions = pd.Series(np.arange(len(data)) + 1, index=data.index, dtype="int64")
    source_indices = pd.Series([str(value) for value in data.index], index=data.index, dtype=object)
    dates = _date_series(data[schema["date"]]) if schema.get("date") else pd.Series(pd.NaT, index=data.index)
    vendor = _text_series(data[schema["vendor"]]) if schema.get("vendor") else pd.Series("", index=data.index, dtype=object)
    invoice = _text_series(data[schema["invoice"]]) if schema.get("invoice") else pd.Series("", index=data.index, dtype=object)
    po = _text_series(data[schema["po"]]) if schema.get("po") else pd.Series("", index=data.index, dtype=object)
    quantity = _number_series(data[schema["quantity"]]) if schema.get("quantity") else pd.Series(np.nan, index=data.index)
    unit_price = _money_series(data[schema["unit_price"]]) if schema.get("unit_price") else pd.Series(np.nan, index=data.index)
    contract_value = (
        _money_series(data[schema["contract_value"]]) if schema.get("contract_value") else pd.Series(np.nan, index=data.index)
    )

    findings: list[dict[str, Any]] = []
    duplicate_excess_rows: set[Any] = set()
    _progress(progress_callback, "Checking duplicate payments", 25)
    if positive_amount.any():
        if schema.get("invoice"):
            duplicate_excess_rows = _invoice_duplicate_findings(
                data,
                amount,
                positive_amount,
                invoice,
                vendor,
                dates,
                row_positions,
                source_indices,
                po,
                findings,
            )
        else:
            duplicate_excess_rows = _exact_row_duplicate_findings(
                data,
                amount,
                positive_amount,
                row_positions,
                source_indices,
                vendor,
                invoice,
                po,
                dates,
                findings,
            )

    _progress(progress_callback, "Comparing payments with contract terms", 48)
    direct_contract_rows: set[Any] = set()
    off_contract = _off_contract_mask(data, schema.get("contract_status"))
    if schema.get("contract_value") and valid_amount.any():
        direct_contract_rows = _contract_overage_findings(
            data,
            amount,
            contract_value,
            quantity,
            unit_price,
            bool(schema.get("contract_is_unit_rate")),
            duplicate_excess_rows,
            off_contract,
            row_positions,
            source_indices,
            vendor,
            invoice,
            po,
            dates,
            findings,
        )

    _progress(progress_callback, "Estimating comparable price variance", 67)
    price_rows: set[Any] = set()
    if valid_amount.any():
        price_rows = _price_variance_findings(
            data,
            schema,
            amount,
            quantity,
            unit_price,
            duplicate_excess_rows | direct_contract_rows,
            row_positions,
            source_indices,
            vendor,
            invoice,
            po,
            dates,
            findings,
            price_threshold,
        )

    _progress(progress_callback, "Checking inactive and off-contract spend", 83)
    control_rows: set[Any] = set()
    if positive_amount.any() and schema.get("contract_status"):
        control_rows |= _off_contract_findings(
            amount, off_contract, row_positions, source_indices, vendor, invoice, po, dates, findings
        )
    if positive_amount.any() and schema.get("last_activity"):
        control_rows |= _inactive_findings(
            data,
            schema["last_activity"],
            amount,
            row_positions,
            source_indices,
            vendor,
            invoice,
            po,
            dates,
            findings,
            inactive_days,
        )

    frame = pd.DataFrame(findings, columns=_FINDING_COLUMNS) if findings else _empty_findings()
    if not frame.empty:
        frame["leakage_amount"] = pd.to_numeric(frame["leakage_amount"], errors="coerce").round(2)
        frame = frame.sort_values(
            ["classification", "leakage_amount", "source_row"],
            ascending=[True, False, True],
            kind="stable",
        ).reset_index(drop=True)
        frame["finding_id"] = [f"IRIS-{number:04d}" for number in range(1, len(frame) + 1)]

    confirmed_mask = frame.get("classification", pd.Series(dtype=object)).eq("Confirmed leakage")
    estimated_mask = frame.get("classification", pd.Series(dtype=object)).eq("Estimated pricing exposure")
    duplicate_total = _frame_total(frame, frame.get("finding_type", pd.Series(dtype=object)).eq("Duplicate invoice payment") | frame.get("finding_type", pd.Series(dtype=object)).eq("Exact duplicate transaction record"))
    contract_total = _frame_total(frame, frame.get("finding_type", pd.Series(dtype=object)).eq("Contract overage"))
    confirmed_total = _frame_total(frame, confirmed_mask)
    estimated_total = _frame_total(frame, estimated_mask)
    # Control sources can overlap (for example, an inactive subscription may
    # also be off-contract).  Count each source row once in the headline metric.
    at_risk_total = float(amount.loc[list(control_rows)].clip(lower=0).sum()) if control_rows else 0.0
    total_spend: Optional[float] = float(amount.loc[positive_amount].sum()) if positive_amount.any() else None
    if amount_is_derived and total_spend is not None:
        warnings.append("Spend analysed is derived rather than read from an amount column.")

    source_breakdown = _make_source_breakdown(frame)
    summary = _summary(
        total_spend,
        confirmed_total,
        duplicate_total,
        contract_total,
        estimated_total,
        at_risk_total,
        len(frame),
        len(data),
    )
    summary["confirmed_findings"] = int(confirmed_mask.sum())
    summary["pricing_findings"] = int(estimated_mask.sum())
    summary["control_risk_findings"] = int(frame.get("classification", pd.Series(dtype=object)).eq("Control-risk spend").sum())
    summary["price_threshold"] = _normalise_threshold(price_threshold)
    summary["inactive_days"] = int(max(0, inactive_days))

    warnings = list(dict.fromkeys(str(item) for item in warnings if item))
    schema["warnings"] = warnings
    _progress(progress_callback, "Leakage scan complete", 100)
        # ENTERPRISE AR LEAKAGE: Overdue + Concentration
    # This runs after all the duplicate/contract logic
    if 'outstanding_balance' in data.columns and 'net_30_due_date' in data.columns:
        df_ar = data.copy()
        df_ar['net_30_due_date'] = _date_series(df_ar['net_30_due_date'])
        df_ar['outstanding_balance'] = _money_series(df_ar['outstanding_balance'])
        today = pd.Timestamp('2026-08-12')

        leaking_df = df_ar[(df_ar['net_30_due_date'] < today) & (df_ar['outstanding_balance'] > 0)]

        money_leaking = float(leaking_df['outstanding_balance'].sum())
        overdue_count = int(len(leaking_df))

        # Override confirmed_leakage for AR files
        summary['confirmed_leakage'] = money_leaking
        summary['money_leakage'] = money_leaking
        summary['overdue_count'] = overdue_count

        # Top 10% Concentration
        if 'arr' in df_ar.columns and 'customer_name' in df_ar.columns:
            df_ar['arr'] = _money_series(df_ar['arr'])
            top10_arr = df_ar.groupby('customer_name')['arr'].sum().nlargest(max(1, int(len(df_ar)*0.1)+1)).sum()
            total_arr = df_ar['arr'].sum()
            summary['top_10_concentration'] = f"{(top10_arr / total_arr * 100):.1f}%" if total_arr > 0 else "0%"

        # Biggest Risk
        if len(leaking_df) > 0 and 'customer_name' in leaking_df.columns:
            riskiest = leaking_df.sort_values('outstanding_balance', ascending=False).iloc[0]
            summary['biggest_risk_customer'] = str(riskiest['customer_name'])
            summary['biggest_risk_owner'] = str(riskiest.get('collection_owner', 'N/A'))

        if 'health_score' in df_ar.columns:
            summary['avg_health_score'] = float(_number_series(df_ar['health_score']).mean())

    _progress(progress_callback, "Leakage scan complete", 100)
    return AnalysisResult(summary, frame, source_breakdown, schema, warnings)
    return AnalysisResult(summary, frame, source_breakdown, schema, warnings)


def _summary(
    total_spend: Optional[float],
    confirmed_leakage: float,
    duplicate_leakage: float,
    contract_overage: float,
    estimated_pricing_exposure: float,
    at_risk_spend: float,
    finding_count: int,
    rows_analyzed: int,
) -> dict[str, Any]:
    return {
        "total_spend": _rounded_or_none(total_spend),
        "confirmed_leakage": round(float(confirmed_leakage), 2),
        "duplicate_leakage": round(float(duplicate_leakage), 2),
        "contract_overage": round(float(contract_overage), 2),
        "estimated_pricing_exposure": round(float(estimated_pricing_exposure), 2),
        "at_risk_spend": round(float(at_risk_spend), 2),
        "finding_count": int(finding_count),
        "rows_analyzed": int(rows_analyzed),
    }


def _apply_mapping(df: pd.DataFrame, mapping: Optional[Mapping[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    schema = infer_schema(df)
    warnings = list(schema.get("warnings", []))
    if not mapping:
        return schema, warnings

    candidates: list[Mapping[str, Any]] = [mapping]
    for nested_key in ("fields", "field_mapping", "mapping", "schema"):
        nested = mapping.get(nested_key) if isinstance(mapping, Mapping) else None
        if isinstance(nested, Mapping):
            candidates.append(nested)

    columns_by_lower = {str(column).strip().lower(): str(column) for column in df.columns}
    for field in CANONICAL_FIELDS:
        supplied = False
        value: Any = None
        for candidate in candidates:
            for key in (field, f"{field}_column"):
                if key in candidate:
                    supplied, value = True, candidate[key]
                    break
            if supplied:
                break
        if not supplied:
            # Also accept a UI-friendly reverse mapping: {"Amount": "amount"}.
            for candidate in candidates:
                for raw_column, role in candidate.items():
                    if str(role).strip().lower() == field and str(raw_column) in df.columns:
                        supplied, value = True, raw_column
                        break
                if supplied:
                    break
        if not supplied:
            continue
        if isinstance(value, Mapping):
            value = value.get("column", value.get("field", value.get("name")))
        if value is None or str(value).strip().lower() in {"", "none", "null", "not available"}:
            schema[field] = None
            continue
        actual = columns_by_lower.get(str(value).strip().lower())
        if actual is None:
            warnings.append(f"Mapping for {field!r} refers to missing column {value!r}; automatic choice was retained.")
            continue
        schema[field] = actual

    override = _first_mapping_value(candidates, "contract_is_unit_rate")
    if override is not _UNSET:
        parsed = _as_bool(override)
        if parsed is None and str(override).strip().lower() not in {"", "auto", "none"}:
            warnings.append("contract_is_unit_rate must be true or false; the inferred setting was retained.")
        elif parsed is not None:
            schema["contract_is_unit_rate"] = parsed

    schema["amount_column"] = schema.get("amount")
    schema["spend_column"] = schema.get("amount")
    schema["field_roles"] = {column: field for field, column in schema.items() if field in CANONICAL_FIELDS and column}
    return schema, warnings


_UNSET = object()


def _first_mapping_value(candidates: list[Mapping[str, Any]], key: str) -> Any:
    for candidate in candidates:
        if key in candidate:
            return candidate[key]
    return _UNSET


def _invoice_duplicate_findings(
    data: pd.DataFrame,
    amount: pd.Series,
    positive_amount: pd.Series,
    invoice: pd.Series,
    vendor: pd.Series,
    dates: pd.Series,
    row_positions: pd.Series,
    source_indices: pd.Series,
    po: pd.Series,
    findings: list[dict[str, Any]],
) -> set[Any]:
    normalized_invoice = invoice.map(_normalise_identifier)
    normalized_vendor = vendor.map(_normalise_identifier).replace("", "(vendor unavailable)")
    usable = normalized_invoice.ne("") & positive_amount
    if not usable.any():
        return set()
    work = pd.DataFrame(
        {
            "row_key": data.index,
            "invoice": normalized_invoice,
            "vendor": normalized_vendor,
            "amount": amount.round(2),
            "date": dates,
            "source_row": row_positions,
        },
        index=data.index,
    ).loc[usable]
    excess: set[Any] = set()
    for _, group in work.groupby(["invoice", "vendor", "amount"], dropna=False, sort=False):
        if len(group) < 2:
            continue
        ordered = group.assign(_date_sort=group["date"].fillna(pd.Timestamp.max)).sort_values(
            ["_date_sort", "source_row"], kind="stable"
        )
        related = [int(value) for value in ordered["source_row"].tolist()]
        first_row = ordered.iloc[0]
        for index in ordered.index[1:]:
            excess.add(index)
            findings.append(
                _finding(
                    finding_type="Duplicate invoice payment",
                    classification="Confirmed leakage",
                    leakage_amount=float(amount.loc[index]),
                    source_row=int(row_positions.loc[index]),
                    source_index=source_indices.loc[index],
                    related_source_rows=related,
                    vendor=vendor.loc[index],
                    invoice=invoice.loc[index],
                    po=po.loc[index],
                    date=dates.loc[index],
                    amount=amount.loc[index],
                    reason=(
                        f"Invoice {invoice.loc[index]!s} appears {len(ordered)} times for the same vendor "
                        f"at the same amount. This record is counted as an excess payment after source row "
                        f"{int(first_row['source_row'])}."
                    ),
                    evidence="Exact match on invoice/reference, vendor, and amount; only repeated records beyond the first are counted.",
                    confidence="High" if normalized_vendor.loc[index] != "(vendor unavailable)" else "Medium",
                )
            )
    return excess


def _exact_row_duplicate_findings(
    data: pd.DataFrame,
    amount: pd.Series,
    positive_amount: pd.Series,
    row_positions: pd.Series,
    source_indices: pd.Series,
    vendor: pd.Series,
    invoice: pd.Series,
    po: pd.Series,
    dates: pd.Series,
    findings: list[dict[str, Any]],
) -> set[Any]:
    """Fallback only when there is no invoice field: require exact full rows."""

    if not positive_amount.any():
        return set()
    normalized = data.copy()
    for column in normalized.columns:
        normalized[column] = normalized[column].map(lambda value: _normalise_identifier(value))
    # Hashing avoids constructing very large concatenated strings for exports
    # with many columns.  Equal hashes are checked by the normalized content in
    # normal pandas grouping semantics.
    hashes = pd.util.hash_pandas_object(normalized, index=False)
    work = pd.DataFrame({"hash": hashes, "source_row": row_positions, "amount": amount}, index=data.index).loc[positive_amount]
    excess: set[Any] = set()
    for _, group in work.groupby("hash", sort=False):
        if len(group) < 2:
            continue
        ordered = group.sort_values("source_row", kind="stable")
        related = [int(value) for value in ordered["source_row"].tolist()]
        for index in ordered.index[1:]:
            excess.add(index)
            findings.append(
                _finding(
                    finding_type="Exact duplicate transaction record",
                    classification="Confirmed leakage",
                    leakage_amount=float(amount.loc[index]),
                    source_row=int(row_positions.loc[index]),
                    source_index=source_indices.loc[index],
                    related_source_rows=related,
                    vendor=vendor.loc[index],
                    invoice=invoice.loc[index],
                    po=po.loc[index],
                    date=dates.loc[index],
                    amount=amount.loc[index],
                    reason=(
                        f"This full transaction record exactly repeats source row {related[0]}; "
                        "only the later occurrence is counted as excess."
                    ),
                    evidence="Exact match across all uploaded fields because no invoice/reference column was available.",
                    confidence="Medium",
                )
            )
    return excess


def _contract_overage_findings(
    data: pd.DataFrame,
    amount: pd.Series,
    contract_value: pd.Series,
    quantity: pd.Series,
    unit_price: pd.Series,
    contract_is_unit_rate: bool,
    duplicate_excess_rows: set[Any],
    off_contract: pd.Series,
    row_positions: pd.Series,
    source_indices: pd.Series,
    vendor: pd.Series,
    invoice: pd.Series,
    po: pd.Series,
    dates: pd.Series,
    findings: list[dict[str, Any]],
) -> set[Any]:
    if contract_is_unit_rate:
        expected = contract_value * quantity
        actual = amount.where(amount.notna(), unit_price * quantity)
        formula = "contracted unit rate × quantity"
    else:
        expected = contract_value
        actual = amount
        formula = "contracted per-transaction value"
    tolerance = np.maximum(0.01, expected.abs() * 1e-9)
    eligible = actual.notna() & expected.notna() & (actual > 0) & (expected >= 0) & ((actual - expected) > tolerance)
    if duplicate_excess_rows:
        eligible.loc[list(duplicate_excess_rows)] = False
    eligible &= ~off_contract
    rows: set[Any] = set()
    for index in data.index[eligible]:
        overage = float(actual.loc[index] - expected.loc[index])
        rows.add(index)
        findings.append(
            _finding(
                finding_type="Contract overage",
                classification="Confirmed leakage",
                leakage_amount=overage,
                source_row=int(row_positions.loc[index]),
                source_index=source_indices.loc[index],
                related_source_rows=[int(row_positions.loc[index])],
                vendor=vendor.loc[index],
                invoice=invoice.loc[index],
                po=po.loc[index],
                date=dates.loc[index],
                amount=actual.loc[index],
                contract_value=contract_value.loc[index],
                quantity=quantity.loc[index],
                unit_price=unit_price.loc[index],
                reason=(
                    f"Paid amount { _money_text(actual.loc[index]) } exceeds the {formula} "
                    f"of { _money_text(expected.loc[index]) } by { _money_text(overage) }."
                ),
                evidence="Payment amount and contract value are both present in the same source record.",
                confidence="High",
            )
        )
    return rows


def _price_variance_findings(
    data: pd.DataFrame,
    schema: Mapping[str, Any],
    amount: pd.Series,
    quantity: pd.Series,
    unit_price: pd.Series,
    excluded_rows: set[Any],
    row_positions: pd.Series,
    source_indices: pd.Series,
    vendor: pd.Series,
    invoice: pd.Series,
    po: pd.Series,
    dates: pd.Series,
    findings: list[dict[str, Any]],
    price_threshold: float,
) -> set[Any]:
    threshold = _normalise_threshold(price_threshold)
    price = unit_price.copy()
    derived_price = amount / quantity.where(quantity > 0)
    price = price.where(price.notna() & (price > 0), derived_price)
    if not (price.notna() & (price > 0)).any():
        return set()

    descriptor: Optional[pd.Series] = None
    descriptor_label = ""
    if schema.get("description"):
        descriptor = _text_series(data[schema["description"]]).map(_normalise_identifier)
        descriptor_label = "description"
    if descriptor is None or descriptor.eq("").all():
        if schema.get("category"):
            descriptor = _text_series(data[schema["category"]]).map(_normalise_identifier)
            descriptor_label = "category"
    if descriptor is None or descriptor.eq("").all():
        return set()

    vendor_key = vendor.map(_normalise_identifier)
    groups = vendor_key + "|" + descriptor
    usable = (price > 0) & vendor_key.ne("") & descriptor.ne("")
    if excluded_rows:
        usable.loc[list(excluded_rows)] = False
    work = pd.DataFrame({"group": groups, "price": price, "amount": amount, "quantity": quantity}, index=data.index).loc[usable]
    if work.empty:
        return set()
    counts = work.groupby("group")["price"].transform("size")
    # Three comparable records is deliberately conservative for a benchmark.
    work = work.loc[counts >= 3].copy()
    if work.empty:
        return set()
    work["median"] = work.groupby("group")["price"].transform("median")
    flagged = work[(work["price"] > work["median"] * (1 + threshold)) & (work["median"] > 0)]
    rows: set[Any] = set()
    for index, record in flagged.iterrows():
        current_price, median_price = float(record["price"]), float(record["median"])
        if pd.notna(record["quantity"]) and record["quantity"] > 0:
            estimate = (current_price - median_price) * float(record["quantity"])
        elif pd.notna(record["amount"]) and record["amount"] > 0:
            estimate = float(record["amount"]) * (1 - median_price / current_price)
        else:
            continue
        if not math.isfinite(estimate) or estimate <= 0:
            continue
        rows.add(index)
        peer_count = int((work["group"] == record["group"]).sum())
        increase = (current_price / median_price - 1) * 100
        findings.append(
            _finding(
                finding_type="Peer price variance",
                classification="Estimated pricing exposure",
                leakage_amount=estimate,
                source_row=int(row_positions.loc[index]),
                source_index=source_indices.loc[index],
                related_source_rows=[int(row_positions.loc[index])],
                vendor=vendor.loc[index],
                invoice=invoice.loc[index],
                po=po.loc[index],
                date=dates.loc[index],
                amount=amount.loc[index],
                quantity=quantity.loc[index],
                unit_price=current_price,
                reason=(
                    f"Unit price is {increase:.0f}% above the median of {peer_count} comparable records "
                    f"for the same vendor and {descriptor_label}."
                ),
                evidence=(
                    "Peer benchmark only; this is an estimate, not a confirmed overpayment. "
                    f"Observed unit price { _money_text(current_price) }; peer median { _money_text(median_price) }."
                ),
                confidence="Medium",
            )
        )
    return rows


def _off_contract_mask(data: pd.DataFrame, status_column: Optional[str]) -> pd.Series:
    if not status_column:
        return pd.Series(False, index=data.index)
    status = _text_series(data[status_column]).map(_normalise_identifier)
    patterns = (
        "no contract",
        "off contract",
        "without contract",
        "non contract",
        "uncontracted",
        "expired",
        "not covered",
        "not under contract",
        "no agreement",
        "unapproved",
    )
    return status.map(lambda value: any(pattern in value for pattern in patterns))


def _off_contract_findings(
    amount: pd.Series,
    off_contract: pd.Series,
    row_positions: pd.Series,
    source_indices: pd.Series,
    vendor: pd.Series,
    invoice: pd.Series,
    po: pd.Series,
    dates: pd.Series,
    findings: list[dict[str, Any]],
) -> set[Any]:
    rows: set[Any] = set()
    for index in amount.index[off_contract & (amount > 0)]:
        rows.add(index)
        findings.append(
            _finding(
                finding_type="Off-contract spend",
                classification="Control-risk spend",
                leakage_amount=float(amount.loc[index]),
                source_row=int(row_positions.loc[index]),
                source_index=source_indices.loc[index],
                related_source_rows=[int(row_positions.loc[index])],
                vendor=vendor.loc[index],
                invoice=invoice.loc[index],
                po=po.loc[index],
                date=dates.loc[index],
                amount=amount.loc[index],
                reason="The contract-status field indicates this spend is not covered by an active contract.",
                evidence="Control-risk flag from the uploaded contract-status field; this is not asserted as a loss.",
                confidence="Medium",
            )
        )
    return rows


def _inactive_findings(
    data: pd.DataFrame,
    activity_column: str,
    amount: pd.Series,
    row_positions: pd.Series,
    source_indices: pd.Series,
    vendor: pd.Series,
    invoice: pd.Series,
    po: pd.Series,
    dates: pd.Series,
    findings: list[dict[str, Any]],
    inactive_days: int,
) -> set[Any]:
    activity = _date_series(data[activity_column])
    days = max(0, int(inactive_days))
    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=days)
    inactive = activity.notna() & (activity < cutoff) & (amount > 0)
    rows: set[Any] = set()
    for index in amount.index[inactive]:
        rows.add(index)
        age = max(0, int((pd.Timestamp.now().normalize() - activity.loc[index]).days))
        findings.append(
            _finding(
                finding_type="Inactive subscription or service",
                classification="Control-risk spend",
                leakage_amount=float(amount.loc[index]),
                source_row=int(row_positions.loc[index]),
                source_index=source_indices.loc[index],
                related_source_rows=[int(row_positions.loc[index])],
                vendor=vendor.loc[index],
                invoice=invoice.loc[index],
                po=po.loc[index],
                date=dates.loc[index],
                amount=amount.loc[index],
                reason=f"Last activity was {age:,} days ago, exceeding the {days}-day review threshold.",
                evidence="Usage/activity date supports a review of this spend; it is not asserted as a loss.",
                confidence="Medium",
            )
        )
    return rows


def _finding(
    *,
    finding_type: str,
    classification: str,
    leakage_amount: Any,
    source_row: int,
    source_index: Any,
    related_source_rows: list[int],
    vendor: Any = "",
    invoice: Any = "",
    po: Any = "",
    date: Any = pd.NaT,
    amount: Any = np.nan,
    contract_value: Any = np.nan,
    quantity: Any = np.nan,
    unit_price: Any = np.nan,
    reason: str = "",
    evidence: str = "",
    confidence: str = "Medium",
) -> dict[str, Any]:
    return {
        "finding_id": "",
        "finding_type": finding_type,
        "classification": classification,
        "leakage_amount": _finite_or_nan(leakage_amount),
        "source_row": source_row,
        "source_index": source_index,
        "related_source_rows": ", ".join(str(value) for value in related_source_rows),
        "vendor": _display_text(vendor),
        "invoice": _display_text(invoice),
        "purchase_order": _display_text(po),
        "transaction_date": _date_text(date),
        "amount": _finite_or_nan(amount),
        "contract_value": _finite_or_nan(contract_value),
        "quantity": _finite_or_nan(quantity),
        "unit_price": _finite_or_nan(unit_price),
        "reason": reason,
        "evidence": evidence,
        "confidence": confidence,
    }


def _make_source_breakdown(findings: pd.DataFrame) -> pd.DataFrame:
    if findings.empty:
        return _empty_sources()
    evidence = {
        "Duplicate invoice payment": "invoice/reference + vendor + amount",
        "Exact duplicate transaction record": "exact full-row match",
        "Contract overage": "payment versus contract value",
        "Peer price variance": "peer price benchmark",
        "Off-contract spend": "contract-status field",
        "Inactive subscription or service": "last activity field",
    }
    grouped = (
        findings.groupby(["finding_type", "classification"], dropna=False, as_index=False)
        .agg(leakage_amount=("leakage_amount", "sum"), finding_count=("finding_type", "size"))
        .sort_values("leakage_amount", ascending=False, kind="stable")
        .reset_index(drop=True)
    )
    grouped["leakage_amount"] = grouped["leakage_amount"].round(2)
    grouped["evidence_source"] = grouped["finding_type"].map(evidence).fillna("uploaded source records")
    return grouped[_SOURCE_COLUMNS]


def _field_score(field: str, name: str, series: pd.Series) -> float:
    exact: dict[str, tuple[str, ...]] = {
        "amount": (
            "amount", "invoice amount", "invoice total", "total amount", "transaction amount", "payment amount",
            "paid amount", "line amount", "line total", "net amount", "gross amount", "spend", "expense", "expenses",
            "cost", "charge", "debit", "value",
        ),
        "vendor": ("vendor", "vendor name", "supplier", "supplier name", "merchant", "payee", "provider", "company name"),
        "invoice": ("invoice", "invoice number", "invoice no", "invoice id", "bill number", "bill no", "document number", "reference number", "transaction id"),
        "date": ("date", "invoice date", "transaction date", "payment date", "bill date", "posting date", "document date"),
        "contract_value": ("contract value", "contract amount", "contract price", "contracted rate", "contracted price", "agreed rate", "agreed price", "negotiated rate", "quoted price", "allowed amount"),
        "quantity": ("quantity", "qty", "units", "unit count", "number of units", "seats", "licenses", "licences"),
        "unit_price": ("unit price", "unit cost", "price per unit", "rate per unit", "price each", "unit rate"),
        "po": ("po", "po number", "po no", "purchase order", "purchase order number", "purchase order id"),
        "contract_status": ("contract status", "agreement status", "contract coverage", "coverage status"),
        "last_activity": ("last activity", "last active", "last login", "last used", "last usage", "last accessed", "usage date"),
        "description": ("description", "line description", "item description", "details", "memo", "narrative", "service description"),
        "category": ("category", "spend category", "expense category", "department", "cost center", "cost centre", "commodity"),
    }
    collapsed = name.replace(" ", "")
    if name in exact[field] or collapsed in {item.replace(" ", "") for item in exact[field]}:
        base = 100.0
    else:
        base = 0.0
        for phrase in exact[field]:
            if len(phrase) > 3 and phrase in name:
                base = max(base, 78.0)
        tokens = set(name.split())
        if field == "amount" and tokens & {"amount", "spend", "expense", "cost", "charge", "debit"}:
            base = max(base, 66.0)
        elif field == "vendor" and tokens & {"vendor", "supplier", "merchant", "payee", "provider"}:
            base = max(base, 70.0)
        elif field == "invoice" and tokens & {"invoice", "bill"}:
            base = max(base, 72.0)
        elif field == "date" and "date" in tokens:
            base = max(base, 60.0)
        elif field == "contract_value" and "contract" in tokens and tokens & {"amount", "value", "rate", "price", "cost"}:
            base = max(base, 82.0)
        elif field == "quantity" and tokens & {"quantity", "qty", "units", "seats", "licenses", "licences"}:
            base = max(base, 72.0)
        elif field == "unit_price" and ("unit" in tokens or "per" in tokens) and tokens & {"price", "rate", "cost"}:
            base = max(base, 78.0)
        elif field == "po" and ("purchase" in tokens and "order" in tokens or "po" in tokens):
            base = max(base, 80.0)
        elif field == "contract_status" and "contract" in tokens and "status" in tokens:
            base = max(base, 88.0)
        elif field == "last_activity" and tokens & {"activity", "login", "usage", "accessed", "active"} and "last" in tokens:
            base = max(base, 85.0)
        elif field == "description" and tokens & {"description", "memo", "details", "narrative"}:
            base = max(base, 78.0)
        elif field == "category" and tokens & {"category", "department", "commodity"}:
            base = max(base, 78.0)

    if not base:
        return 0.0
    if field in {"amount", "contract_value", "unit_price", "quantity"}:
        parsed = _money_series(series.head(200)) if field != "quantity" else _number_series(series.head(200))
        ratio = float(parsed.notna().mean()) if len(parsed) else 0.0
        base += min(12.0, ratio * 12.0)
    elif field in {"date", "last_activity"}:
        parsed_date = _date_series(series.head(100))
        base += min(10.0, float(parsed_date.notna().mean()) * 10.0) if len(parsed_date) else 0.0
    return base


def _money_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce").astype(float)
    return series.map(_parse_money).astype(float)


def _number_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce").astype(float)
    # Quantities are normally plain values, but accepting thousands separators
    # makes exports such as "1,000 seats" usable.
    return series.map(_parse_money).astype(float)


def _parse_money(value: Any) -> float:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return np.nan
    if isinstance(value, (int, float, np.number)) and not isinstance(value, bool):
        number = float(value)
        return number if math.isfinite(number) else np.nan
    text = str(value).strip().replace("\u00a0", " ")
    if text.lower() in _MISSING_TEXT:
        return np.nan
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("() ")
    # Accounting exports commonly use a trailing minus or CR to indicate a
    # credit.  We preserve the sign rather than discarding it.
    if text.endswith("-"):
        negative = True
        text = text[:-1]
    if re.search(r"\b(?:cr|credit)\b", text, flags=re.I):
        negative = True
    text = re.sub(r"(?i)\b(?:usd|eur|gbp|ngn|zar|cad|aud|cr|dr|credit|debit)\b", "", text)
    text = re.sub(r"[^0-9,\.\-+]", "", text).replace("+", "")
    if not text or text in {"-", ".", ","}:
        return np.nan
    # Preserve a leading minus even when parentheses were not used.
    if text.startswith("-"):
        negative = True
        text = text[1:]
    text = text.replace("-", "")
    comma, dot = text.rfind(","), text.rfind(".")
    if comma >= 0 and dot >= 0:
        # The final separator is the decimal separator in both 1,234.56 and
        # 1.234,56.
        decimal = "," if comma > dot else "."
        thousands = "." if decimal == "," else ","
        text = text.replace(thousands, "")
        if decimal == ",":
            text = text.replace(",", ".")
    elif comma >= 0:
        pieces = text.split(",")
        if len(pieces) == 2 and len(pieces[-1]) in {1, 2}:
            text = text.replace(",", ".")
        elif len(pieces) > 2 and len(pieces[-1]) in {1, 2}:
            text = "".join(pieces[:-1]) + "." + pieces[-1]
        else:
            text = text.replace(",", "")
    elif dot >= 0:
        pieces = text.split(".")
        # 1.234 is substantially more often a thousands-formatted money value
        # than a three-decimal price.  Values with one/two decimals remain so.
        if len(pieces) == 2 and len(pieces[-1]) == 3 and len(pieces[0]) <= 3:
            text = "".join(pieces)
        elif len(pieces) > 2 and len(pieces[-1]) == 3:
            text = "".join(pieces)
    try:
        parsed = float(text)
    except ValueError:
        return np.nan
    if not math.isfinite(parsed):
        return np.nan
    return -parsed if negative else parsed


def _date_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce")
    # format='mixed' is unavailable in older pandas releases.  The generic
    # parser is slower but robust for typical CSV-sized uploads.
    try:
        return pd.to_datetime(series, errors="coerce")
    except (TypeError, ValueError):
        return pd.Series(pd.NaT, index=series.index)


def _text_series(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


def _normalise_name(value: Any) -> str:
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(value))
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text).strip().lower()
    return re.sub(r"\s+", " ", text)


def _normalise_identifier(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value).strip().lower()
    if text in _MISSING_TEXT:
        return ""
    return re.sub(r"[^a-z0-9]+", "", text)


def _unique_clean_columns(columns: Any) -> list[str]:
    seen: dict[str, int] = {}
    clean: list[str] = []
    for position, value in enumerate(columns, start=1):
        base = str(value).replace("\ufeff", "").strip() or f"Unnamed column {position}"
        seen[base] = seen.get(base, 0) + 1
        clean.append(base if seen[base] == 1 else f"{base} ({seen[base]})")
    return clean


def _normalise_threshold(value: Any) -> float:
    try:
        threshold = float(value)
    except (TypeError, ValueError):
        threshold = 0.15
    if threshold > 1:
        threshold /= 100
    return max(0.0, min(threshold, 10.0))


def _as_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "yes", "y", "1", "unit", "unit rate"}:
        return True
    if text in {"false", "no", "n", "0", "total", "per transaction"}:
        return False
    return None


def _empty_findings() -> pd.DataFrame:
    return pd.DataFrame(columns=_FINDING_COLUMNS)


def _empty_sources() -> pd.DataFrame:
    return pd.DataFrame(columns=_SOURCE_COLUMNS)


def _frame_total(frame: pd.DataFrame, mask: pd.Series) -> float:
    if frame.empty or mask.empty:
        return 0.0
    values = pd.to_numeric(frame.loc[mask, "leakage_amount"], errors="coerce")
    return float(values.sum()) if values.notna().any() else 0.0


def _finite_or_nan(value: Any) -> float:
    try:
        converted = float(value)
        return converted if math.isfinite(converted) else np.nan
    except (TypeError, ValueError):
        return np.nan


def _rounded_or_none(value: Optional[float]) -> Optional[float]:
    return round(float(value), 2) if value is not None and math.isfinite(float(value)) else None


def _money_text(value: Any) -> str:
    numeric = _finite_or_nan(value)
    return f"${numeric:,.2f}" if not math.isnan(numeric) else "unavailable"


def _display_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def _date_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    try:
        return pd.Timestamp(value).date().isoformat()
    except (TypeError, ValueError):
        return str(value)


def _progress(callback: Optional[Callable[..., Any]], message: str, percent: int) -> None:
    if callback is None:
        return
    payload = {"stage": message, "message": message, "percent": percent, "progress": percent}
    try:
        callback(payload)
    except TypeError:
        try:
            callback(message, percent)
        except Exception:
            return
    except Exception:
        # Reporting progress must never suppress an analysis result.
        return

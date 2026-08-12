"""IRIS â€” evidence-led spend leakage analysis.

Run with ``streamlit run app.py``.  The app deliberately keeps uploads in
memory: a CSV refreshes the analysis immediately and is not written to the
local SQLite database that the legacy prototype used.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from leakage_analysis import analyze_dataframe, infer_schema, load_csv_bytes
from ui import ScanProgress, apply_branding, render_dashboard, render_upload_state


st.set_page_config(
    page_title="IRIS | Spend leakage evidence",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)
apply_branding()


NO_FIELD = "â€” Not available in this file â€”"
FIELD_LABELS = {
    "amount": "Transaction amount *",
    "vendor": "Vendor / supplier",
    "invoice": "Invoice or transaction reference",
    "date": "Transaction / invoice date",
    "contract_value": "Contracted amount or rate",
    "quantity": "Quantity / units",
    "unit_price": "Unit price",
    "po": "Purchase-order reference",
    "contract_status": "Contract status",
    "last_activity": "Last login / activity date",
    "description": "Description / line item",
    "category": "Category / department",
}


@st.cache_data(show_spinner=False)
def _load_upload(payload: bytes) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Parse a file once per content hash; mapping changes do not re-read it."""

    return load_csv_bytes(payload)


def _safe_summary(results: Any) -> dict[str, Any]:
    summary = getattr(results, "summary", None)
    if isinstance(summary, dict):
        return summary
    if isinstance(results, dict):
        nested = results.get("summary")
        return nested if isinstance(nested, dict) else results
    return {}


def _as_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if pd.notna(number) else None


def _money(value: Any, currency: str) -> str:
    number = _as_number(value)
    if number is None:
        return "Not available"
    sign = "-" if number < 0 else ""
    return f"{sign}{currency}{abs(number):,.2f}"


def _source_hash(payload: bytes) -> str:
    return sha256(payload).hexdigest()[:12]


def _render_mapping(data: pd.DataFrame, inferred: dict[str, Any], file_key: str) -> dict[str, Any]:
    """Let an analyst correct inference before IRIS makes a monetary claim."""

    options = [NO_FIELD, *[str(column) for column in data.columns]]
    mapping: dict[str, Any] = {}

    with st.expander("Review column mapping", expanded=False):
        st.caption(
            "IRIS chose the best matches below. Correct any ambiguous field before "
            "sharing a result; the scan reruns immediately when a mapping changes."
        )
        left, right = st.columns(2)
        for position, (field, label) in enumerate(FIELD_LABELS.items()):
            default = inferred.get(field)
            default = default if default in data.columns else NO_FIELD
            target = left if position % 2 == 0 else right
            with target:
                choice = st.selectbox(
                    label,
                    options,
                    index=options.index(default),
                    key=f"mapping_{file_key}_{field}",
                )
            mapping[field] = None if choice == NO_FIELD else choice

        mapping["contract_is_unit_rate"] = st.checkbox(
            "The contracted value is a per-unit rate (multiply it by Quantity)",
            value=bool(inferred.get("contract_is_unit_rate", False)),
            key=f"mapping_{file_key}_contract_rate",
            help="Leave off when a contract field already contains the expected total invoice amount.",
        )
    return mapping


def _render_method_note() -> None:
    st.info(
        "**How IRIS reports dollars:** confirmed leakage contains only redundant "
        "duplicate-payment value and billed-over-contract value, with overlaps removed. "
        "Pricing anomalies and missing-control signals are shown separately as review "
        "queuesâ€”they are not added to the confirmed total."
    )


def _render_top_metrics(summary: dict[str, Any], currency: str) -> None:
    spend = summary.get("total_spend")
    confirmed = summary.get("confirmed_leakage", summary.get("total_leakage"))
    pricing = summary.get("estimated_pricing_exposure")
    at_risk = summary.get("at_risk_spend")
    first, second, third, fourth = st.columns(4)
    first.metric("Spend analysed", _money(spend, currency))
    second.metric("Confirmed / quantified leakage", _money(confirmed, currency))
    third.metric("Estimated pricing exposure", _money(pricing, currency))
    fourth.metric("Control-risk spend", _money(at_risk, currency))
    first.caption("Usable monetary rows in this upload")
    second.caption("Duplicates + contract variance; overlap removed")
    third.caption("Benchmark candidates; validate before recovery claim")
    fourth.caption("Policy / inactivity exceptions; not counted as loss")


def _normalize_for_dashboard(results: Any, summary: dict[str, Any]) -> Any:
    """Give the reusable renderer a truthful headline even if the engine evolves."""

    if isinstance(results, dict):
        display = dict(results)
    else:
        display = {
            "summary": summary,
            "findings": getattr(results, "findings", pd.DataFrame()),
            "source_breakdown": getattr(results, "source_breakdown", pd.DataFrame()),
            "schema": getattr(results, "schema", {}),
            "warnings": getattr(results, "warnings", []),
        }
    display["total_spend"] = summary.get("total_spend")
    # The dashboard renderer's generic candidate headline must never add review
    # exposure to the amount that is safe to describe as quantified leakage.
    display["total_leakage"] = summary.get("confirmed_leakage", summary.get("total_leakage", 0))
    return display


def _payload_from_sidebar() -> tuple[bytes | None, str | None]:
    with st.sidebar:
        st.header("Live CSV scan")
        uploaded = st.file_uploader(
            "Upload a CSV export",
            type=["csv", "txt"],
            help="Comma, tab, semicolon, and pipe-delimited CSV exports are supported.",
        )
        use_demo = st.button("Open included demo", use_container_width=True)
        st.divider()
        currency = st.text_input("Currency symbol", value="$", max_chars=6)
        inactive_days = st.slider("Inactive-service threshold (days)", 30, 365, 90, 15)
        price_threshold = st.slider("Pricing outlier threshold", 5, 100, 15, 5) / 100
        st.caption("The scan runs automatically when the upload or controls change.")

    if uploaded is not None:
        st.session_state["iris_use_demo"] = False
        return uploaded.getvalue(), uploaded.name
    if use_demo:
        st.session_state["iris_use_demo"] = True
    if st.session_state.get("iris_use_demo"):
        demo_path = Path(__file__).with_name("demo_portco_leakage.csv")
        if demo_path.exists():
            return demo_path.read_bytes(), demo_path.name
        st.error("The included demo file was not found beside app.py.")
    return None, None


payload, filename = _payload_from_sidebar()

if payload is None:
    render_upload_state()
    st.caption(
        "Uploads are processed in memory for the current session. IRIS does not save "
        "them to the legacy local database."
    )
    st.stop()

try:
    data, import_info = _load_upload(payload)
except Exception as exc:  # The parser provides the recoverable detail where possible.
    st.error(f"IRIS could not read this file: {exc}")
    st.stop()

if data.empty:
    st.warning("The file has headers but no data rows. Upload a CSV with at least one record.")
    st.stop()

st.markdown('<p class="iris-eyebrow">Live analysis</p>', unsafe_allow_html=True)
st.title("IRIS spend leakage evidence")
st.caption(f"Analysing **{filename}** â€¢ {len(data):,} rows â€¢ {len(data.columns):,} columns")

inferred = infer_schema(data)
file_key = _source_hash(payload)
mapping = _render_mapping(data, inferred, file_key)
_render_method_note()

# Controls are defined in the sidebar before parsing, so retrieve their values from
# session state only after Streamlit has registered them.
currency = st.session_state.get("Currency symbol", "$")
inactive_days = int(st.session_state.get("Inactive-service threshold (days)", 90))
price_threshold = float(st.session_state.get("Pricing outlier threshold", 0.15))

progress = ScanProgress("Reading mapped fieldsâ€¦")
try:
    results = analyze_dataframe(
        data,
        mapping,
        inactive_days=inactive_days,
        price_threshold=price_threshold,
        progress_callback=progress.callback,
    )
    progress.complete("Live leakage scan complete")
except Exception as exc:
    progress.fail("The file loaded, but the leakage scan could not finish.")
    st.exception(exc)
    st.stop()

summary = _safe_summary(results)
_render_top_metrics(summary, currency)

# NEW: ENTERPRISE METRICS ROW
if summary.get("money_leakage") is not None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Money Leaking", _money(summary.get("money_leakage"), currency))
    col2.metric("Overdue Invoices", f"{summary.get('overdue_count', 0):,}")
    col3.metric("Top 10% Concentration", summary.get("top_10_concentration", "0%"))
    col4.metric("Avg Health Score", f"{summary.get('avg_health_score', 0):.0f}")

    if summary.get("biggest_risk_customer"):
        st.warning(f"**Biggest Risk:** {summary['biggest_risk_customer']} - Owned by {summary.get('biggest_risk_owner', 'N/A')}")

st.divider()
render_dashboard(_normalize_for_dashboard(results, summary), data, show_profile=True)

st.caption(
    "Live scan complete. Download the source evidence before sharing a result; "
    "validate candidates against the payment system and governing contract."
)

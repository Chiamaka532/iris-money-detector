import pandas as pd
import numpy as np
from difflib import get_close_matches
from datetime import datetime, timedelta

def get_col(df, possible_names):
    for name in possible_names:
        for col in df.columns:
            if name.lower() in col.lower():
                return col
    return None

def safe_sum(df, col):
    if col is None or col not in df.columns: return 0
    return pd.to_numeric(df[col], errors='coerce').sum()

def find_leaks(df):
    results = {}

    # UPDATED: Added enterprise column names
    amount_col = get_col(df, ['amount', 'total', 'invoice_amount_usd', 'outstanding_balance_usd'])
    vendor_col = get_col(df, ['vendor', 'supplier', 'customer_name', 'customer'])
    po_col = get_col(df, ['po', 'po_number'])
    contract_col = get_col(df, ['contract', 'contract_id'])
    date_col = get_col(df, ['invoice_date', 'date', 'net_30_due_date'])
    due_date_col = get_col(df, ['due_date', 'net_30_due_date']) # NEW
    paid_col = get_col(df, ['amount_paid', 'amount_paid_usd']) # NEW
    dept_col = get_col(df, ['department', 'dept', 'region', 'industry'])

    if not amount_col or not vendor_col:
        return {"error": f"Missing critical columns. Found: {list(df.columns)}"}

    df[amount_col] = pd.to_numeric(df[amount_col], errors='coerce')
    if date_col: df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
    if due_date_col: df[due_date_col] = pd.to_datetime(df[due_date_col], errors='coerce')
    if paid_col: df[paid_col] = pd.to_numeric(df[paid_col], errors='coerce')

    today = pd.Timestamp('2026-08-12')

    # 1. SHADOW SPEND = No PO
    shadow_df = df[df[po_col].isna() | (df[po_col] == '')] if po_col else pd.DataFrame()
    
    # 2. CONTRACT LEAK = No Contract
    contract_df = df[df[contract_col].isna() | (df[contract_col] == '')] if contract_col else pd.DataFrame()
    
    # 3. REAL MONEY LEAKAGE = Overdue AND Unpaid - NEW LOGIC
    if due_date_col and paid_col and amount_col:
        df['leakage_amount'] = df[amount_col] - df[paid_col]
        overdue_df = df[(df[due_date_col] < today) & (df[paid_col] < df[amount_col])]
    else:
        overdue_df = pd.DataFrame()

    dup_cols = [c for c in ['Vendor_ID', vendor_col, 'Invoice_Number', 'Invoice', amount_col] if c in df.columns]
    dupes = df[df.duplicated(dup_cols, keep=False)] if len(dup_cols) >= 3 else pd.DataFrame()

    # RECURRING LEAK
    recurring_leak = pd.DataFrame()
    if date_col:
        df['Month'] = df[date_col].dt.to_period('M')
        recurring = df.groupby([vendor_col, amount_col, 'Month']).size().reset_index(name='Count')
        recurring_leak = recurring.groupby([vendor_col, amount_col]).size().reset_index(name='Months')
        recurring_leak = recurring_leak[recurring_leak['Months'] >= 2]

    maverick_by_dept = shadow_df.groupby(dept_col)[amount_col].sum().sort_values(ascending=False) if dept_col and not shadow_df.empty else pd.Series()

    # UPDATED RESULTS
    results['shadow_spend'] = safe_sum(shadow_df, amount_col)
    results['contract_leak'] = safe_sum(contract_df, amount_col)
    results['money_leakage'] = safe_sum(overdue_df, 'leakage_amount') # NEW KEY METRIC
    results['overdue_count'] = len(overdue_df) # NEW
    results['duplicate_payments'] = safe_sum(dupes, amount_col)
    results['recurring_leak'] = recurring_leak
    results['total_spend'] = safe_sum(df, amount_col)
    results['top_vendors'] = df.groupby(vendor_col)[amount_col].sum().sort_values(ascending=False).head(10) if vendor_col else pd.Series()
    results['maverick_by_dept'] = maverick_by_dept
    results['leak_df'] = pd.concat([shadow_df, contract_df, overdue_df, dupes]).drop_duplicates() # Added overdue_df

    return results
def find_duplicate_vendors(df):
    vendor_col = get_col(df, ['vendor', 'supplier'])
    amount_col = get_col(df, ['amount', 'total'])
    if not vendor_col or not amount_col: return pd.DataFrame()
    vendors = df[vendor_col].unique().tolist()
    dupes = []
    for vendor in vendors:
        matches = get_close_matches(vendor, vendors, n=3, cutoff=0.85)
        if len(matches) > 1:
            total_spend = df[df[vendor_col].isin(matches)][amount_col].sum()
            dupes.append({"Primary": vendor, "Possible Duplicates": ", ".join(matches), "Consolidation Opportunity": f"${total_spend:,.2f}"})
    return pd.DataFrame(dupes).drop_duplicates()

def price_benchmark(df): return pd.DataFrame()
def contract_renewal_risk(df): return pd.DataFrame()

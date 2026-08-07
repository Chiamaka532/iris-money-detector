import pandas as pd
import numpy as np
from difflib import get_close_matches
from datetime import datetime, timedelta

def get_col(df, possible_names, default=None):
    """Smart column finder. Finds 'Amount' even if it's 'amount' or 'Invoice Amount'"""
    for name in possible_names:
        for col in df.columns:
            if name.lower() in col.lower():
                return col
    return default

def find_leaks(df):
    results = {}
    
    # SMART COLUMN MAPPING - works with any CSV
    amount_col = get_col(df, ['amount', 'total', 'value'])
    vendor_col = get_col(df, ['vendor', 'supplier'])
    po_col = get_col(df, ['po', 'purchase order'])
    contract_col = get_col(df, ['contract', 'contract_id'])
    date_col = get_col(df, ['invoice_date', 'date'])
    dept_col = get_col(df, ['department', 'dept'])
    contract_end_col = get_col(df, ['contract_end', 'end_date'])

    # If critical columns missing, return empty
    if not amount_col or not vendor_col:
        return {"error": "CSV must have Vendor and Amount columns"}
    
    df[amount_col] = pd.to_numeric(df[amount_col], errors='coerce')
    
    if date_col:
        df[date_col] = pd.to_datetime(df[date_col], errors='coerce')

    # 1. SHADOW SPEND - only if PO column exists
    shadow_df = pd.DataFrame()
    if po_col:
        shadow_df = df[df[po_col].isna() | (df[po_col] == '')]

    # 2. CONTRACT LEAK - only if Contract column exists
    contract_df = pd.DataFrame()
    if contract_col:
        contract_df = df[df[contract_col].isna() | (df[contract_col] == '')]

    # 3. MAVERICK BY DEPT - only if dept exists
    maverick_by_dept = pd.Series()
    if dept_col and not shadow_df.empty:
        maverick_by_dept = shadow_df.groupby(dept_col)[amount_col].sum().sort_values(ascending=False)
    
    # 4. RECURRING LEAK - Same vendor + same amount 3+ times
    recurring_leak = pd.DataFrame()
    if date_col:
        df['Month'] = df[date_col].dt.to_period('M')
        recurring = df.groupby([vendor_col, amount_col, 'Month']).size().reset_index(name='Count')
        recurring_leak = recurring.groupby([vendor_col, amount_col]).size().reset_index(name='Months')
        recurring_leak = recurring_leak[recurring_leak['Months'] >= 3]

    # 5. DUPLICATE PAYMENTS - Same Vendor + Invoice + Amount
    dupes = df[df.duplicated(['Vendor_ID' if 'Vendor_ID' in df.columns else vendor_col, 'Invoice_Number' if 'Invoice_Number' in df.columns else 'Invoice', amount_col], keep=False)]
    
    results['shadow_spend'] = shadow_df[amount_col].sum() if not shadow_df.empty else 0
    results['contract_leak'] = contract_df[amount_col].sum() if not contract_df.empty else 0
    results['duplicate_payments'] = dupes[amount_col].sum() if not dupes.empty else 0
    results['total_spend'] = df[amount_col].sum()
    results['top_vendors'] = df.groupby(vendor_col)[amount_col].sum().sort_values(ascending=False).head(10)
    results['maverick_by_dept'] = maverick_by_dept
    results['recurring_leak'] = recurring_leak
    results['leak_df'] = pd.concat([shadow_df, contract_df, dupes]).drop_duplicates()
    
    return results

def find_duplicate_vendors(df):
    vendor_col = get_col(df, ['vendor', 'supplier'])
    amount_col = get_col(df, ['amount', 'total', 'value'])
    if not vendor_col: return pd.DataFrame()
    
    vendors = df[vendor_col].unique().tolist()
    dupes = []
    for vendor in vendors:
        matches = get_close_matches(vendor, vendors, n=3, cutoff=0.85)
        if len(matches) > 1:
            total_spend = df[df[vendor_col].isin(matches)][amount_col].sum()
            dupes.append({"Primary": vendor, "Possible Duplicates": ", ".join(matches), "Consolidation Opportunity": f"${total_spend:,.2f}"})
    return pd.DataFrame(dupes).drop_duplicates()

def price_benchmark(df):
    vendor_col = get_col(df, ['vendor', 'supplier'])
    amount_col = get_col(df, ['amount', 'total', 'value'])
    if not vendor_col: return pd.DataFrame()
    
    benchmarks = {'Microsoft Azure': 0.12, 'Amazon Web Services': 0.11, 'Salesforce': 150, 'Adobe Creative Cloud': 52.99, 'Zoom Video Communications': 14.99, 'Google Workspace': 6.00, 'Slack Technologies': 7.25, 'DocuSign': 40.00}
    df['Benchmark_Price'] = df[vendor_col].map(benchmarks)
    df['Variance_%'] = ((df[amount_col] / df['Benchmark_Price']) - 1) * 100
    overpriced = df[df['Variance_%'] > 15]
    return overpriced[[vendor_col, amount_col, 'Benchmark_Price', 'Variance_%']].dropna()

def contract_renewal_risk(df):
    contract_end_col = get_col(df, ['contract_end', 'end_date'])
    vendor_col = get_col(df, ['vendor', 'supplier'])
    contract_col = get_col(df, ['contract', 'contract_id'])
    amount_col = get_col(df, ['amount', 'total', 'value'])
    
    if not contract_end_col: return pd.DataFrame()
    
    df[contract_end_col] = pd.to_datetime(df[contract_end_col], errors='coerce')
    sixty_days = datetime.now() + timedelta(days=60)
    at_risk = df[(df[contract_end_col] <= sixty_days) & (df[contract_end_col] >= datetime.now())]
    return at_risk[[vendor_col, contract_col, contract_end_col, amount_col]].dropna()

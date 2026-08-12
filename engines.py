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
    
    # HARDCODED FOR YOUR EXACT COLUMNS
    amount_col = 'invoice_amount'
    balance_col = 'outstanding_balance'
    due_col = 'net_30_due_date'
    vendor_col = 'customer_name'
    owner_col = 'collection_owner'
    arr_col = 'arr'
    health_col = 'health_score'

    # Convert
    df[balance_col] = pd.to_numeric(df[balance_col], errors='coerce')
    df[due_col] = pd.to_datetime(df[due_col], errors='coerce')
    today = pd.Timestamp('2026-08-12')

    # 1. MONEY LEAKAGE
    leaking_df = df[(df[due_col] < today) & (df[balance_col] > 0)]
    
    # 2. TOP 10% CONCENTRATION
    top_10_percent_customers = df.groupby(vendor_col)[arr_col].sum().nlargest(int(len(df)*0.1)+1)
    concentration = top_10_percent_customers.sum() / df[arr_col].sum() * 100

    # 3. PEOPLE GAP
    owner_risk = leaking_df.groupby(owner_col)[balance_col].sum().sort_values(ascending=False)

    results['money_leakage'] = leaking_df[balance_col].sum()
    results['overdue_count'] = len(leaking_df)
    results['top_10_concentration'] = f"{concentration:.1f}%"
    results['biggest_risk_customer'] = leaking_df.sort_values(balance_col, ascending=False).iloc[0][vendor_col] if len(leaking_df) > 0 else "None"
    results['biggest_risk_owner'] = owner_risk.index[0] if len(owner_risk) > 0 else "None"
    results['avg_health_score'] = df[health_col].mean()
    results['leak_df'] = leaking_df
    results['total_arr'] = df[arr_col].sum()

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

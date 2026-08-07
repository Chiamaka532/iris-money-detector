import pandas as pd
import numpy as np
from difflib import get_close_matches

def find_leaks(df):
    results = {}
    amount_col = 'Amount'
    po_col = 'PO_Number'
    vendor_col = 'Vendor'
    contract_col = 'Contract_ID'
    
    shadow_df = df[df[po_col].isna() | (df[po_col] == '')]
    contract_df = df[df[contract_col].isna() | (df[contract_col] == '')]
    
    results['shadow_spend'] = shadow_df[amount_col].sum()
    results['contract_leak'] = contract_df[amount_col].sum()
    results['total_spend'] = df[amount_col].sum()
    results['top_vendors'] = df.groupby(vendor_col)[amount_col].sum().sort_values(ascending=False)
    results['leak_df'] = pd.concat([shadow_df, contract_df]).drop_duplicates()
    return results

def find_duplicate_vendors(df):
    vendors = df['Vendor'].unique().tolist()
    dupes = []
    for vendor in vendors:
        matches = get_close_matches(vendor, vendors, n=3, cutoff=0.8)
        if len(matches) > 1:
            dupes.append({"Primary": vendor, "Possible Duplicates": ", ".join([m for m in matches if m != vendor])})
    return pd.DataFrame(dupes)

def price_benchmark(df):
    # FAKE MARKET BENCHMARKS - Replace with real data later
    benchmarks = {
        'Microsoft Azure': 0.12, # $ per unit
        'Amazon Web Services': 0.11,
        'Salesforce': 150, # $ per seat
        'Adobe Creative Cloud': 52.99, # $ per seat
        'Zoom Video Communications': 14.99,
        'Google Workspace': 6.00,
        'Slack Technologies': 7.25,
        'DocuSign': 40.00
    }
    
    df['Benchmark_Price'] = df['Vendor'].map(benchmarks)
    df['Variance_%'] = ((df['Amount'] / df['Benchmark_Price']) - 1) * 100
    overpriced = df[df['Variance_%'] > 15]
    return overpriced[['Vendor', 'Amount', 'Benchmark_Price', 'Variance_%']]

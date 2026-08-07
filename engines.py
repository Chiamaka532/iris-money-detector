import pandas as pd
import numpy as np
from difflib import get_close_matches
from datetime import datetime, timedelta

def find_leaks(df):
    results = {}
    amount_col = 'Amount'
    po_col = 'PO_Number'
    vendor_col = 'Vendor'
    contract_col = 'Contract_ID'
    date_col = 'Invoice_Date'
    dept_col = 'Department'
    
    df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
    
    shadow_df = df[df[po_col].isna() | (df[po_col] == '')]
    contract_df = df[df[contract_col].isna() | (df[contract_col] == '')]
    maverick_by_dept = shadow_df.groupby(dept_col)[amount_col].sum().sort_values(ascending=False)
    
    recurring = df.groupby([vendor_col, amount_col]).size().reset_index(name='Months')
    recurring_leak = recurring[recurring['Months'] >= 3]
    
    results['shadow_spend'] = shadow_df[amount_col].sum()
    results['contract_leak'] = contract_df[amount_col].sum()
    results['total_spend'] = df[amount_col].sum()
    results['top_vendors'] = df.groupby(vendor_col)[amount_col].sum().sort_values(ascending=False)
    results['maverick_by_dept'] = maverick_by_dept
    results['recurring_leak'] = recurring_leak
    results['leak_df'] = pd.concat([shadow_df, contract_df]).drop_duplicates()
    return results

def find_duplicate_vendors(df):
    vendors = df['Vendor'].unique().tolist()
    dupes = []
    for vendor in vendors:
        matches = get_close_matches(vendor, vendors, n=3, cutoff=0.85)
        if len(matches) > 1:
            total_spend = df[df['Vendor'].isin(matches)]['Amount'].sum()
            dupes.append({"Primary": vendor, "Possible Duplicates": ", ".join(matches), "Consolidation Opportunity": f"${total_spend:,.2f}"})
    return pd.DataFrame(dupes)

def price_benchmark(df):
    benchmarks = {'Microsoft Azure': 0.12, 'Amazon Web Services': 0.11, 'Salesforce': 150, 'Adobe Creative Cloud': 52.99, 'Zoom Video Communications': 14.99, 'Google Workspace': 6.00, 'Slack Technologies': 7.25, 'DocuSign': 40.00}
    df['Benchmark_Price'] = df['Vendor'].map(benchmarks)
    df['Variance_%'] = ((df['Amount'] / df['Benchmark_Price']) - 1) * 100
    overpriced = df[df['Variance_%'] > 15]
    return overpriced[['Vendor', 'Amount', 'Benchmark_Price', 'Variance_%']]

def contract_renewal_risk(df):
    # THIS IS THE FUNCTION THAT WAS MISSING
    df['Contract_End_Date'] = pd.to_datetime(df.get('Contract_End_Date'), errors='coerce')
    sixty_days = datetime.now() + timedelta(days=60)
    at_risk = df[(df['Contract_End_Date'] <= sixty_days) & (df['Contract_End_Date'] >= datetime.now())]
    return at_risk[['Vendor', 'Contract_ID', 'Contract_End_Date', 'Amount']]

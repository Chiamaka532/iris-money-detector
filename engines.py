import pandas as pd
import numpy as np

def find_leaks(df):
    results = {}
    
    # AUTO-DETECT COLUMNS - this is the fix
    amount_col = next((col for col in df.columns if 'amount' in col.lower()), 'Amount')
    date_col = next((col for col in df.columns if 'date' in col.lower()), None)
    po_col = next((col for col in df.columns if 'po' in col.lower()), 'PO_Number')
    vendor_col = next((col for col in df.columns if 'vendor' in col.lower()), 'Vendor')
    contract_col = next((col for col in df.columns if 'contract' in col.lower()), 'Contract_ID')
    
    df[amount_col] = pd.to_numeric(df[amount_col], errors='coerce')
    
    # 1. DUPLICATE/SHADOW SPEND: No PO Number
    shadow_spend = df[df[po_col].isna() | (df[po_col] == '')]
    results['shadow_spend'] = shadow_spend[amount_col].sum()
    results['shadow_count'] = len(shadow_spend)
    
    # 2. CONTRACT LEAKAGE: Has Amount but No Contract
    contract_leak = df[df[contract_col].isna() | (df[contract_col] == '')]
    results['contract_leak'] = contract_leak[amount_col].sum()
    
    # 3. TOTAL SPEND
    results['total_spend'] = df[amount_col].sum()
    
    # 4. TOP VENDORS
    results['top_vendors'] = df.groupby(vendor_col)[amount_col].sum().sort_values(ascending=False).head(5)
    
    results['df'] = df # return df for charts
    results['cols'] = {'amount': amount_col, 'date': date_col, 'vendor': vendor_col} # pass columns back
    
    return results

import pandas as pd
import numpy as np

def find_leaks(df):
    results = {}
    
    amount_col = next((col for col in df.columns if 'amount' in col.lower()), 'Amount')
    date_col = next((col for col in df.columns if 'date' in col.lower()), None)
    po_col = next((col for col in df.columns if 'po' in col.lower()), 'PO_Number')
    vendor_col = next((col for col in df.columns if 'vendor' in col.lower()), 'Vendor')
    contract_col = next((col for col in df.columns if 'contract' in col.lower()), 'Contract_ID')
    
    df[amount_col] = pd.to_numeric(df[amount_col], errors='coerce')
    
    # 1. SHADOW SPEND: No PO
    shadow_df = df[df[po_col].isna() | (df[po_col] == '')]
    results['shadow_spend'] = shadow_df[amount_col].sum()
    results['shadow_count'] = len(shadow_df)
    results['shadow_df'] = shadow_df
    
    # 2. CONTRACT LEAKAGE: No Contract
    contract_df = df[df[contract_col].isna() | (df[contract_col] == '')]
    results['contract_leak'] = contract_df[amount_col].sum()
    results['contract_df'] = contract_df
    
    results['total_spend'] = df[amount_col].sum()
    results['top_vendors'] = df.groupby(vendor_col)[amount_col].sum().sort_values(ascending=False)
    results['cols'] = {'amount': amount_col, 'date': date_col, 'vendor': vendor_col}
    
    return results

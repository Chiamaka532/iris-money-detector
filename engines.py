import pandas as pd
import numpy as np

def run_duplicate_engine(df):
    """Finds exact duplicate payments: Same Vendor + Same Amount + Same Date"""
    dup_mask = df.duplicated(subset=['Vendor_Name', 'Amount', 'Date'], keep=False)
    dupes = df[dup_mask].copy()
    
    # THE FIX: Calculate savings
    if len(dupes) > 0:
        dupes['savings'] = dupes['Amount']  # Assume 100% recovery on duplicates
        dupes['reason'] = 'Duplicate Payment'
    else:
        dupes['savings'] = 0
    
    return {'data': dupes, 'savings': dupes['savings']}

def run_price_engine(df):
    """Finds price spikes: >10% increase vs last payment to same vendor"""
    df = df.sort_values(['Vendor_Name', 'Date'])
    df['prev_amount'] = df.groupby('Vendor_Name')['Amount'].shift(1)
    df['pct_change'] = (df['Amount'] - df['prev_amount']) / df['prev_amount']
    
    spikes = df[df['pct_change'] > 0.10].copy()
    
    # THE FIX: Calculate savings
    if len(spikes) > 0:
        spikes['savings'] = spikes['Amount'] - spikes['prev_amount'] # The overpay amount
        spikes['reason'] = 'Price Spike >10%'
    else:
        spikes['savings'] = 0
    
    return {'data': spikes, 'savings': spikes['savings']}

def run_saas_engine(df):
    """Finds SaaS waste: Subscriptions that could be consolidated/cancelled"""
    saas_df = df[df['Category'].str.contains('SaaS|Software', case=False, na=False)].copy()
    
    # THE FIX: Assume 25% savings on SaaS
    if len(saas_df) > 0:
        saas_df['savings'] = saas_df['Amount'] * 0.25
        saas_df['reason'] = 'Potential SaaS Consolidation'
    else:
        saas_df['savings'] = 0
    
    return {'data': saas_df, 'savings': saas_df['savings']}

def run_offcontract_engine(df):
    """Finds off-contract spend: No Contract ID"""
    off_df = df[(df['Contract_ID'] == "") | (df['Contract_ID'].isna())].copy()
    
    # THE FIX: Assume 15% savings by putting on contract
    if len(off_df) > 0:
        off_df['savings'] = off_df['Amount'] * 0.15
        off_df['reason'] = 'Off-Contract Spend'
    else:
        off_df['savings'] = 0
    
    return {'data': off_df, 'savings': off_df['savings']}

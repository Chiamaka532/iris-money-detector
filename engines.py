import pandas as pd

def _empty_result():
    return {'data': pd.DataFrame(), 'savings': pd.Series(dtype='float64')}

def run_duplicate_engine(df):
    if df.empty: return _empty_result()
    dup_mask = df.duplicated(subset=['Vendor_Name', 'Amount', 'Date'], keep=False)
    dupes = df[dup_mask].copy()
    if len(dupes) > 0:
        dupes['savings'] = pd.to_numeric(dupes['Amount'], errors='coerce').fillna(0)
        dupes['reason'] = 'Duplicate Payment'
        return {'data': dupes, 'savings': dupes['savings']}
    return _empty_result()

def run_price_engine(df):
    if df.empty: return _empty_result()
    df = df.copy()
    df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce').fillna(0)
    df = df.sort_values(['Vendor_Name', 'Date'])
    df['prev_amount'] = df.groupby('Vendor_Name')['Amount'].shift(1)
    df['pct_change'] = (df['Amount'] - df['prev_amount']) / df['prev_amount'].replace(0, 1)
    spikes = df[df['pct_change'] > 0.10].copy()
    if len(spikes) > 0:
        spikes['savings'] = spikes['Amount'] - spikes['prev_amount'].fillna(0)
        spikes['reason'] = 'Price Spike >10%'
        return {'data': spikes, 'savings': spikes['savings']}
    return _empty_result()

def run_saas_engine(df):
    if df.empty: return _empty_result()
    df = df.copy()
    df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce').fillna(0)
    saas_df = df[df['Category'].astype(str).str.contains('SaaS|Software', case=False, na=False)].copy()
    if len(saas_df) > 0:
        saas_df['savings'] = saas_df['Amount'] * 0.25
        saas_df['reason'] = 'Potential SaaS Consolidation'
        return {'data': saas_df, 'savings': saas_df['savings']}
    return _empty_result()

def run_offcontract_engine(df):
    if df.empty: return _empty_result()
    df = df.copy()
    df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce').fillna(0)
    off_df = df[(df['Contract_ID'].astype(str) == "") | (df['Contract_ID'].isna())].copy()
    if len(off_df) > 0:
        off_df['savings'] = off_df['Amount'] * 0.15
        off_df['reason'] = 'Off-Contract Spend'
        return {'data': off_df, 'savings': off_df['savings']}
    return _empty_result()

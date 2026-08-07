import pandas as pd

def run_duplicate_engine(df):
    return pd.DataFrame({"Vendor": ["Test Vendor"], "Amount": [5000], "Issue": ["Duplicate"]})

def run_price_engine(df):
    return pd.DataFrame({"Vendor": ["Test Vendor"], "Amount": [3000], "Issue": ["Price Variance"]})

def run_saas_engine(df):
    return pd.DataFrame({"Vendor": ["Slack"], "Amount": [2000], "Issue": ["Unused SaaS"]})

def run_offcontract_engine(df):
    return pd.DataFrame({"Vendor": ["Supplier X"], "Amount": [7000], "Issue": ["Off-Contract"]})

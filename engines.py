import pandas as pd
import numpy as np

def run_duplicate_engine(df):
    """FIND 1: Duplicate Invoice Payments. 0.5-1% leakage"""
    dupes = df[df.duplicated(subset=['Vendor_Name', 'Amount', 'Date'], keep=False)].copy()
    dupes['Potential_Savings'] = dupes['Amount']
    return {'data': dupes, 'savings': dupes['Potential_Savings']}

def run_price_engine(df):
    """FIND 2: Price Variance vs Median. 1-3% leakage"""
    df['Median_Price'] = df.groupby(['Vendor_Name', 'Category'])['Amount'].transform('median')
    overpay = df[df['Amount'] > df['Median_Price'] * 1.15].copy()
    overpay['Potential_Savings'] = overpay['Amount'] - overpay['Median_Price']
    return {'data': overpay, 'savings': overpay['Potential_Savings']}

def run_saas_engine(df):
    """FIND 3: Zombie SaaS + Seat Waste. 0.5-2% leakage"""
    saas = df[df['Category'].str.contains('SaaS|Software|Subscription', case=False, na=False)].copy()
    saas['Potential_Savings'] = saas['Amount'] * 0.25 # Assume 25% waste
    return {'data': saas, 'savings': saas['Potential_Savings']}

def run_offcontract_engine(df):
    """FIND 4: Spend outside negotiated contracts. 1-3% leakage"""
    off = df[(df['Contract_ID'] == "") | (df['Contract_ID'].isna())].copy()
    off['Potential_Savings'] = off['Amount'] * 0.08 # Assume 8% discount possible
    return {'data': off, 'savings': off['Potential_Savings']}

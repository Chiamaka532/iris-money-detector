import streamlit as st
import pandas as pd
import sqlite3
import numpy as np
from datetime import datetime

st.set_page_config(page_title="IRIS Ultimate Detective", layout="wide")
st.title("🕵️ IRIS - Ultimate Money Detective Pro")
st.write("Finds: Fraud Spikes, Duplicates, Overpay, Zombie SaaS, Off-Contract, Money Leaks")

st.sidebar.header("Upload Data")
uploaded_file = st.sidebar.file_uploader("Upload AP/Procurement/Sales CSV or Excel", type=["csv", "xlsx", "xls"])

conn = sqlite3.connect("iris_data.db")

if uploaded_file is not None:
    if uploaded_file.name.endswith('.csv'):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)

    df.columns = [col.strip() for col in df.columns]
    for col in df.columns:
        if 'date' in col.lower():
            df[col] = pd.to_datetime(df[col], errors='coerce')

    df.to_sql("all_data", conn, if_exists='replace', index=False)
    st.success(f"Loaded: {len(df)} rows")

    numeric_cols = df.select_dtypes(include=['number']).columns.tolist()

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 Data",
        "🚨 Fraud & Spikes",
        "💸 Money Leaks",
        "1. Duplicate Invoices",
        "2. Over Contract",
        "3. Zombie + Off-Contract"
    ])

    with tab1:
        st.dataframe(df, use_container_width=True)

    # TAB 2: FRAUD & SPIKES - WE KEPT THIS
    with tab2:
        st.subheader("🚨 FRAUD & PRICE SPIKE DETECTION")
        if numeric_cols:
            for col in numeric_cols[:3]:
                mean = df[col].mean()
                std = df[col].std()
                if std > 0:
                    threshold = mean + 3*std
                    anomalies = df[df[col] > threshold]
                    if not anomalies.empty:
                        st.error(f"**{len(anomalies)} Suspicious Spikes in `{col}`** > 3x normal")
                        st.dataframe(anomalies, use_container_width=True)
                    else:
                        st.success(f"No major spikes in `{col}`")
        else:
            st.warning("No number columns found")

    # TAB 3: MONEY LEAKS - WE KEPT THIS
    with tab3:
        st.subheader("💸 WHERE IS MONEY DISAPPEARING?")
        if 'Sales' in df.columns and 'Expenses' in df.columns:
            df['Loss_Rate'] = (df['Expenses'] / df['Sales']) * 100
            worst = df.nlargest(5, 'Loss_Rate')
            st.warning("**Top 5 Worst Loss Rate Transactions:**")
            st.dataframe(worst, use_container_width=True)
            st.metric("Total Expenses", f"{df['Expenses'].sum():,.2f}")
        elif numeric_cols:
            st.info("Analyzing biggest expense column")
            st.dataframe(df.nlargest(5, numeric_cols[-1]), use_container_width=True)

    # TAB 4: DUPLICATES
    with tab4:
        st.subheader("🚨 1. DUPLICATE INVOICES")
        if all(col in df.columns for col in ['Invoice#', 'Vendor', 'Amount']):
            duplicates = df[df.duplicated(subset=['Invoice#', 'Vendor', 'Amount'], keep=False)]
            if not duplicates.empty:
                st.error(f"FOUND {len(duplicates)} DUPLICATE ROWS! Risk: ${duplicates['Amount'].sum():,.2f}")
                st.dataframe(duplicates, use_container_width=True)
            else:
                st.success("No duplicate invoices")
        else:
            st.warning("Need columns: Invoice#, Vendor, Amount")

    # TAB 5: OVER CONTRACT
    with tab5:
        st.subheader("💸 2. PAYING ABOVE CONTRACT PRICE")
        if 'Contract_Price' in df.columns and 'Amount' in df.columns:
            df['Overpay'] = df['Amount'] - df['Contract_Price']
            overpay = df[df['Overpay'] > 0]
            if not overpay.empty:
                st.error(f"OVERPAID ${overpay['Overpay'].sum():,.2f} TOTAL")
                st.dataframe(overpay, use_container_width=True)
            else:
                st.success("No over-contract payments")
        else:
            st.warning("Need columns: Contract_Price, Amount")

    # TAB 6: ZOMBIE + OFF CONTRACT
    with tab6:
        st.subheader("🧟 3. ZOMBIE SAAS")
        if 'Last_Login_Date' in df.columns:
            cutoff = datetime.now() - pd.DateOffset(days=90)
            zombies = df[df['Last_Login_Date'] < cutoff]
            if not zombies.empty:
                st.error(f"{len(zombies)} ZOMBIE TOOLS! Wasting: ${zombies['Amount'].sum():,.2f}")
                st.dataframe(zombies, use_container_width=True)

        st.subheader("📑 4. OFF-CONTRACT SPEND")
        if 'Contract_Status' in df.columns:
            off = df[df['Contract_Status'].str.contains('No Contract', case=False, na=False)]
            if not off.empty:
                st.error(f"OFF-CONTRACT SPEND: ${off['Amount'].sum():,.2f}")
                st.dataframe(off, use_container_width=True)

else:
    st.info("Upload file to start 👈")

conn.close()

import streamlit as st
import pandas as pd
import plotly.express as px
from engines import find_leaks

st.set_page_config(page_title="IRIS PRO", page_icon="💰", layout="wide")

st.title("💰 IRIS PRO: PE Spend Leakage Command Center")
st.caption("Private Equity Grade Spend Analysis. Find leakage in 60 seconds.")

with st.sidebar:
    st.header("⚙️ Controls")
    st.info("Upload your AP, P-Card, or Procurement CSV")
    uploaded_file = st.file_uploader("Upload Spend File", type=["csv"])
    
    if uploaded_file:
        st.success("File Loaded")

if uploaded_file is not None:
    try:
        df = pd.read_csv(uploaded_file)
        df.columns = df.columns.str.strip() # remove spaces
        
        # AUTO-DETECT COLUMNS
        amount_col = next((col for col in df.columns if 'amount' in col.lower()), None)
        date_col = next((col for col in df.columns if 'date' in col.lower()), None)
        po_col = next((col for col in df.columns if 'po' in col.lower()), None)
        vendor_col = next((col for col in df.columns if 'vendor' in col.lower()), None)
        contract_col = next((col for col in df.columns if 'contract' in col.lower()), None)
        dept_col = next((col for col in df.columns if 'dept' in col.lower() or 'department' in col.lower()), None)
        
        if amount_col is None:
            st.error("Could not find an 'Amount' column. Please rename one column to include 'Amount'")
            st.stop()
            
        df[amount_col] = pd.to_numeric(df[amount_col], errors='coerce')
        if date_col: df[date_col] = pd.to_datetime(df[date_col], errors='coerce')

        if st.button("🔍 RUN FULL LEAKAGE SCAN", type="primary", use_container_width=True):
            with st.spinner("IRIS AI is scanning 12 leakage patterns..."):
                results = find_leaks(df)
            
            cols = results['cols']
            
            # KPI ROW
            st.header("Executive Summary")
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Total Spend", f"${results['total_spend']:,.2f}")
            k2.metric("Shadow IT Spend", f"${results['shadow_spend']:,.2f}", f"{results['shadow_count']} Transactions")
            k3.metric("Contract Leakage", f"${results['contract_leak']:,.2f}")
            total_leak = results['shadow_spend'] + results['contract_leak']
            k4.metric("Total Leakage Found", f"${total_leak:,.2f}", f"{total_leak/results['total_spend']*100:.1f}% of Spend")
            
            st.divider()
            
            # CHARTS
            tab1, tab2, tab3 = st.tabs(["📊 Leakage Breakdown", "🏢 By Vendor", "📅 By Month"])
            
            with tab1:
                fig_pie = px.pie(names=['Clean Spend', 'Shadow IT', 'Contract Leakage'], 
                                 values=[results['total_spend']-total_leak, results['shadow_spend'], results['contract_leak']],
                                 title="Where is the leakage?")
                st.plotly_chart(fig_pie, use_container_width=True)
            
            with tab2:
                st.subheader("Top 10 Vendors by Spend")
                fig_bar = px.bar(results['top_vendors'].head(10), 
                                 x=results['top_vendors'].head(10).index, 
                                 y=results['top_vendors'].head(10).values,
                                 labels={'x': 'Vendor', 'y': 'Total Spend'})
                st.plotly_chart(fig_bar, use_container_width=True)
            
            with tab3:
                if date_col:
                    monthly = df.groupby(df[date_col].dt.to_period("M"))[amount_col].sum()
                    st.line_chart(monthly)
                else:
                    st.warning("No Date column found to show trends")
            
            st.divider()
            
            # DRILL DOWN TABLE
            st.header("🔎 Drill Down: Leakage Transactions")
            leak_df = pd.concat([results['shadow_df'], results['contract_df']]).drop_duplicates()
            st.dataframe(leak_df, use_container_width=True)
            
            csv = leak_df.to_csv(index=False).encode('utf-8')
            st.download_button("Download Leakage Report as CSV", csv, "IRIS_Leakage_Report.csv", "text/csv")
            
    except Exception as e:
        st.error(f"Engine error: {e}")
        st.write("**Columns found in your file:**", df.columns.tolist())
        st.write("Please ensure you have columns like: Amount, Vendor, Date, PO_Number")
else:
    st.info("👈 Upload the `iris_sample_data.csv` in the sidebar to start")
    st.markdown("### Welcome to IRIS PRO")
    st.markdown("Upload your AP data to instantly find Shadow IT, Contract Leakage, and Duplicate Spend.")

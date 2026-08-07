import streamlit as st
import pandas as pd
import plotly.express as px
from engines import find_leaks, find_duplicate_vendors, price_benchmark

# --- LOGIN PAGE ---
def check_password():
    def password_entered():
        if st.session_state["password"] == "IRIS2026": # CHANGE THIS PASSWORD
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.title("🔒 IRIS PRO Login")
        st.text_input("Password", type="password", on_change=password_entered, key="password")
        st.caption("Demo password: IRIS2026")
        return False
    elif not st.session_state["password_correct"]:
        st.title("🔒 IRIS PRO Login")
        st.text_input("Password", type="password", on_change=password_entered, key="password")
        st.error("😞 Password incorrect")
        return False
    else:
        return True

if not check_password():
    st.stop()

# --- MAIN APP ---
st.set_page_config(page_title="IRIS PRO", page_icon="💰", layout="wide")
st.title("💰 IRIS PRO: PE Spend Leakage Command Center")
st.caption("Private Equity Grade Spend Analysis")

with st.sidebar:
    st.header("⚙️ Controls")
    uploaded_file = st.file_uploader("Upload Spend File", type=["csv"])
    if st.button("Logout"):
        st.session_state["password_correct"] = False
        st.rerun()

if uploaded_file is not None:
    df = pd.read_csv(uploaded_file)
    df.columns = df.columns.str.strip()
    df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce')

    if st.button("🔍 RUN FULL LEAKAGE SCAN", type="primary", use_container_width=True):
        with st.spinner("IRIS AI is scanning..."):
            results = find_leaks(df)
            dupes = find_duplicate_vendors(df)
            benchmark = price_benchmark(df)
            renewals = contract_renewal_risk(df) # ADD THIS LINE
        
        # KPI ROW
        st.header("Executive Summary")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Total Spend", f"${results['total_spend']:,.2f}")
        k2.metric("Shadow IT", f"${results['shadow_spend']:,.2f}")
        k3.metric("Contract Leakage", f"${results['contract_leak']:,.2f}")
        k4.metric("Duplicate Vendors", f"{len(dupes)} Groups")
        
        st.divider()
        
        # TABS - NOW 7 TABS
        tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(["📊 Leakage", "🔁 Duplicates", "💲 Price Benchmark", "🏢 Vendors", "👤 Maverick", "🔄 Recurring", "📅 Renewals"])
        
        with tab1:
            fig_pie = px.pie(names=['Clean Spend', 'Shadow IT', 'Contract Leakage'], 
                             values=[results['total_spend']-results['shadow_spend']-results['contract_leak'], results['shadow_spend'], results['contract_leak']],
                             title="Where is the leakage?")
            st.plotly_chart(fig_pie, use_container_width=True)
            st.dataframe(results['leak_df'])
        
        with tab2:
            st.header("🔁 Duplicate Vendor Detection")
            st.warning("These look like the same vendor with different names. Potential consolidation savings.")
            st.dataframe(dupes)
        
        with tab3:
            st.header("💲 Price Benchmark vs Market")
            st.info("Flags transactions 15% above market benchmark")
            st.dataframe(benchmark)
            
        with tab4:
            st.subheader("Top 10 Vendors by Spend")
            fig_bar = px.bar(results['top_vendors'].head(10), x=results['top_vendors'].head(10).index, y=results['top_vendors'].head(10).values)
            st.plotly_chart(fig_bar, use_container_width=True)

        with tab5:
            st.header("👤 Maverick Spend by Department")
            st.warning("Who is bypassing procurement the most?")
            st.bar_chart(results['maverick_by_dept'])
            st.dataframe(results['maverick_by_dept'])

        with tab6:
            st.header("🔄 Recurring Subscription Leak")
            st.error("These are charged every month. Cancel candidates.")
            st.dataframe(results['recurring_leak'])
            
        with tab7:
            st.header("📅 Contract Renewal Risk - Next 60 Days")
            if len(renewals) > 0:
                st.dataframe(renewals)
            else:
                st.success("No contracts renewing in 60 days")
else:
    st.info("👈 Upload CSV in sidebar to start. Password: IRIS2026")

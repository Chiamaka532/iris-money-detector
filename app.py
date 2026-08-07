import streamlit as st
import pandas as pd
from engines import run_duplicate_engine, run_price_engine, run_saas_engine, run_offcontract_engine
from connectors import get_qb_auth_url, get_qb_tokens, fetch_qb_transactions
from utils import load_sample_data, generate_pdf_report

st.set_page_config(page_title="IRIS PRO", layout="wide", initial_sidebar_state="expanded")

st.title("IRIS PRO: PE Spend Leakage Command Center")
st.caption("Autonomous AI that finds 2-7% of portfolio company spend in 48 hours")

if 'df' not in st.session_state:
    st.session_state.df = load_sample_data()
if 'results' not in st.session_state:
    st.session_state.results = None

with st.sidebar:
    st.header("1. Data Intake")
    upload_method = st.selectbox("Upload Method", ["Demo Mode", "Upload Money Image", "Upload Excel/CSV/Zip", "Connect QuickBooks"])

    df = st.session_state.df

    if upload_method == "Demo Mode":
        st.info("Using sample data")
        df = load_sample_data()

    elif upload_method == "Upload Excel/CSV/Zip":
     file = st.file_uploader("Drop GL + Vendor + Contract Files", type=['csv', 'xlsx', 'zip'])
    if file: # <-- This MUST be indented under the line above
        try:
            if file.name.endswith('.csv'):
                df = pd.read_csv(file)
            else:
                df = pd.read_excel(file)

            # AUTO-FIX COLUMNS
            df.columns = df.columns.str.strip().str.lower()
            df = df.rename(columns={
                'date': 'Date', 'invoice date': 'Date',
                'vendor': 'Vendor_Name', 'vendor_name': 'Vendor_Name', 'supplier': 'Vendor_Name',
                'amount': 'Amount', 'total': 'Amount', 'total amount': 'Amount', 'cost': 'Amount',
                'category': 'Category', 'class': 'Category', 'department': 'Category',
                'contract id': 'Contract_ID', 'contract_id': 'Contract_ID'
            })

            # NUKE: FORCE TYPES. THIS IS THE FIX
            df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce').fillna(0)
            df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
            df['Vendor_Name'] = df['Vendor_Name'].astype(str).fillna("Unknown")
            df['Category'] = df['Category'].astype(str).fillna("Other")
            df['Contract_ID'] = df['Contract_ID'].astype(str).fillna("")

            # Add missing columns if they really dont exist
            for col in ['Date', 'Vendor_Name', 'Amount', 'Category', 'Contract_ID']:
                if col not in df.columns:
                    df[col] = 0 if col == 'Amount' else ""

            st.success(f"✅ Data Loaded: {len(df)} rows | Amount is now: {df['Amount'].dtype}")

        except Exception as e:
            st.error(f"❌ Error loading file: {e}")

    elif upload_method == "Connect QuickBooks":
        if "qb_token" not in st.session_state:
            auth_url = get_qb_auth_url()
            st.markdown(f"[Click to Connect QB]({auth_url})")
            auth_code = st.text_input("Paste Code from URL")
            if st.button("Authorize"):
                tokens = get_qb_tokens(auth_code)
                st.session_state["qb_token"] = tokens["access_token"]
                st.session_state["qb_company"] = tokens["realmId"]
                st.rerun()
        else:
            st.success("QB Connected")
            if st.button("Pull 12 Months Data"):
                df = fetch_qb_transactions(st.session_state["qb_token"], st.session_state["qb_company"])

    elif upload_method == "Upload Money Image":
        file = st.file_uploader("Upload Money Image", type=["jpg", "jpeg", "png"])
        if file:
            from PIL import Image
            image = Image.open(file)
            st.image(image, caption="Uploaded Image", width='stretch')

    st.session_state.df = df

    st.divider()
    if st.button("RUN FULL LEAKAGE SCAN", type="primary", width='stretch'):
        if df.empty:
            st.warning("Please upload data or select Demo Mode first")
        else:
            with st.spinner("Running 4 AI Engines..."):
                try:
                    dup = run_duplicate_engine(df)
                    price = run_price_engine(df)
                    saas = run_saas_engine(df)
                    off = run_offcontract_engine(df)
                    st.session_state.results = {"Duplicates": dup, "Price Variance": price, "SaaS Waste": saas, "Off-Contract": off}
                    st.rerun() # <-- THIS IS THE MAIN THING. Forces dashboard to reload
                except Exception as e:
                    st.error(f"Engine error: {e}")

# ========== THIS IS THE MAIN DASHBOARD SECTION ==========
if st.session_state.results is not None:
    st.header("2. Leakage Dashboard")
    
    try: # <-- YOU WERE MISSING THIS
        dup_sav = float(st.session_state.results['Duplicates']['savings'].sum())
        price_sav = float(st.session_state.results['Price Variance']['savings'].sum())
        saas_sav = float(st.session_state.results['SaaS Waste']['savings'].sum())
        off_sav = float(st.session_state.results['Off-Contract']['savings'].sum())
        total_leakage = dup_sav + price_sav + saas_sav + off_sav
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("TOTAL LEAKAGE FOUND", f"${total_leakage:,.0f}")
        c2.metric("Duplicate Payments", f"${dup_sav:,.0f}")
        c3.metric("Price Variance", f"${price_sav:,.0f}")
        c4.metric("SaaS + Off-Contract", f"${saas_sav + off_sav:,.0f}")

        for name, res in st.session_state.results.items():
            if len(res['data']) > 0:
                sav = float(res['savings'].sum())
                with st.expander(f"**{name}** - ${sav:,.0f} Found - {len(res['data'])} rows"):
                    st.dataframe(res['data'], width='stretch')
                    st.download_button(f"Download {name} CSV", res['data'].to_csv(index=False), f"{name}.csv")
            else:
                st.info(f"{name}: $0 found")

        st.divider()
        if st.button("Generate PE Board PDF Report", type="primary"):
            pdf_path = generate_pdf_report(total_leakage, st.session_state.results)
            with open(pdf_path, "rb") as f:
                st.download_button("Download Board Report", f, "IRIS_PRO_Report.pdf")
    
    except Exception as e: # <-- NOW THIS MATCHES THE TRY ABOVE
        st.error(f"Error displaying results: {e}")

else:
    st.info("Upload data and click 'RUN FULL LEAKAGE SCAN' to see results here")

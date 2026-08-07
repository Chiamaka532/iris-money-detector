import streamlit as st
import requests
from urllib.parse import urlencode
import pandas as pd

QB_AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
QB_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/Bearer"
QB_API_BASE = "https://quickbooks.api.intuit.com/v3/company"

def get_qb_auth_url():
    client_id = st.secrets["quickbooks"]["client_id"]
    redirect_uri = st.secrets["quickbooks"]["redirect_uri"]
    params = {"client_id": client_id, "response_type": "code", "scope": "com.intuit.quickbooks.accounting", "redirect_uri": redirect_uri}
    return f"{QB_AUTH_URL}?{urlencode(params)}"

def get_qb_tokens(auth_code):
    data = {"grant_type": "authorization_code", "code": auth_code, "redirect_uri": st.secrets["quickbooks"]["redirect_uri"],
            "client_id": st.secrets["quickbooks"]["client_id"], "client_secret": st.secrets["quickbooks"]["client_secret"]}
    r = requests.post(QB_TOKEN_URL, data=data)
    return r.json()

def fetch_qb_transactions(access_token, company_id):
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    query = "select Id, TxnDate, TotalAmt, VendorRef, AccountRef from Purchase"
    r = requests.get(f"{QB_API_BASE}/{company_id}/query", headers=headers, params={"query": query})
    data = r.json().get("QueryResponse", {}).get("Purchase", [])
    return pd.DataFrame([{"Vendor_Name": p.get("VendorRef", {}).get("name"), "Date": p.get("TxnDate"), 
                          "Amount": p.get("TotalAmt"), "Category": p.get("AccountRef", {}).get("name"), 
                          "Invoice_ID": p.get("Id"), "Contract_ID": ""} for p in data])

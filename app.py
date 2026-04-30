import streamlit as st
import pandas as pd
import requests
from icalendar import Calendar
from datetime import datetime, date, timedelta
from supabase import create_client, Client
from streamlit_calendar import calendar
import smtplib
from email.mime.text import MIMEText

# --- 1. APP LAYOUT & THEME ---
st.set_page_config(page_title="Meter2 Properties Command Center", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;700&display=swap');
html, body, [class*="css"]  { font-family: 'Roboto', sans-serif; }
.stApp { background-color: #F4F4F4; color: #333333; }
.fc-header-toolbar { background-color: #F65C78 !important; color: white !important; padding: 15px !important; border-radius: 5px 5px 0 0 !important; margin-bottom: 0 !important; }
.fc-toolbar-title { font-weight: 300 !important; font-size: 1.5rem !important; }
.fc-button-primary { background-color: transparent !important; border-color: white !important; }
.fc-view-harness { background-color: white !important; border-radius: 0 0 5px 5px !important; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
.event-card { background-color: white; padding: 15px; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); margin-bottom: 15px; border-left: 4px solid; }
</style>
""", unsafe_allow_html=True)

# --- 2. CONNECTIONS ---
@st.cache_resource
def init_connection() -> Client:
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except Exception as e:
        st.error(f"Failed to connect to Supabase. Check your Secrets. Error: {e}")
        return None

supabase = init_connection()

# --- 3. CONFIGURATION & EMAILS ---
COMPANY_NAME = "Meter2 Properties"
PROP_SWAKOP = "Starshine Guesthouse (Swakopmund)"
PROP_PLETT = "Melkweg Farmhouse (Plettenberg)"
PROPERTIES = [PROP_SWAKOP, PROP_PLETT]
NOTIFICATION_EMAILS = ["menradholm2@gmail.com"]

def send_email_notification(subject, message_body):
    try:
        sender = st.secrets["EMAIL_SENDER"]
        password = st.secrets["EMAIL_PASSWORD"]
        msg = MIMEText(message_body)
        msg['Subject'] = subject
        msg['From'] = sender
        msg['To'] = ", ".join(NOTIFICATION_EMAILS)
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender, password)
            server.send_message(msg)
    except Exception as e:
        st.error(f"Email failed to send. Check EMAIL_SENDER/PASSWORD in Secrets. Error: {e}")

# --- 4. DATABASE FUNCTIONS ---
def add_internal_booking(property_name, guest_name, start_date, end_date):
    data = {
        "property_name": property_name,
        "guest_name": guest_name,
        "start_date": start_date,
        "end_date": end_date,
        "status": "PENDING"
    }
    # Latest supabase-py returns the object directly; we use try/except for error catching
    try:
        return supabase.table("internal_bookings").insert(data).execute()
    except Exception as e:
        return e

def update_status(booking_id, new_status):
    try:
        supabase.table("internal_bookings").update({"status": new_status}).eq("id", booking_id).execute()
    except Exception as e:
        st.error(f"Update failed: {e}")

def get_internal_bookings(property_name=None, status=None):
    if not supabase: return pd.DataFrame()
    query = supabase.table("internal_bookings").select("*")
    if property_name:
        query = query.eq("property_name", property_name)
    if status:
        query = query.eq("status", status)
    try:
        response = query.execute()
        return pd.DataFrame(response.data) if response.data else pd.DataFrame(columns=['id', 'property_name', 'guest_name', 'start_date', 'end_date', 'status'])
    except Exception as e:
        st.error(f"Select failed: {e}")
        return pd.DataFrame()

# --- 5. AIRBNB ICAL FETCH ---
def fetch_airbnb_events(url, property_name, sub_label=""):
    events = []
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        cal = Calendar.from_ical(response.content)
        for component in cal.walk('vevent'):
            start, end = component.get('dtstart').dt, component.get('dtend').dt
            if isinstance(start, datetime): start = start.date()
            if isinstance(end, datetime): end = end.date()
            events.append({
                'property_name': property_name, 'guest_name': f"AirBnB ({sub_label})" if sub_label else "AirBnB Booking",
                'start_date': str(start), 'end_date': str(end), 'status': 'AIRBNB_CONFIRMED'
            })
    except: pass
    return events

@st.cache_data(ttl=300)
def get_all_airbnb_bookings():
    swakop = fetch_airbnb_events("https://www.airbnb.at/calendar/ical/1269982642892159382.ics?t=1d2c8992d5a847febc8bfa4d68c4dc1d", PROP_SWAKOP)
    plett_f = fetch_airbnb_events("https://www.airbnb.at/calendar/ical/1327289595267027214.ics?t=2fc0352915bf4d0aba96926db8f51aab", PROP_PLETT, "Full")
    plett_l = fetch_airbnb_events("https://www.airbnb.at/calendar/ical/1525842544711145278.ics?t=7e30a8982d984a0cb483dcd06a3276ca", PROP_PLETT, "Reduced")
    all_ev = swakop + plett_f + plett_l
    return pd.DataFrame(all_ev) if all_ev else pd.DataFrame(columns=['property_name', 'guest_name', 'start_date', 'end_date', 'status'])

# --- 6. CALENDAR UI ---
def draw_month_calendar(df):
    if df.empty:
        st.info("No bookings found to display on calendar.")
        return
    color_map = {"AIRBNB_CONFIRMED": "#E34C51", "APPROVED": "#1DB9A3", "PENDING": "#F5A623", "REJECTED": "#555555"}
    calendar_events = []
    for _, row in df.iterrows():
        end_date_ex = pd.to_datetime(row['end_date']) + timedelta(days=1)
        calendar_events.append({
            "title": f"{row['guest_name']} ({row['property_name'][:8]}...)",
            "start": row['start_date'], "end": end_date_ex.strftime('%Y-%m-%d'),
            "backgroundColor": color_map.get(row['status'], "#3788d8"), "borderColor": color_map.get(row['status'], "#3788d8"),
        })
    cal_col, list_col = st.columns([2.5, 1])
    with cal_col:
        calendar(events=calendar_events, options={"headerToolbar": {"left": "prev", "center": "title", "right": "next"}, "initialView": "dayGridMonth", "height": 650, "selectable": False, "editable": False})
    with list_col:
        st.markdown("<h4 style='color: #666;'>Upcoming Check-Ins</h4>", unsafe_allow_html=True)
        df['start_date'] = pd.to_datetime(df['start_date'])
        future = df[df['start_date'] >= pd.Timestamp.today()].sort_values('start_date').head(5)
        for _, r in future.iterrows():
            st.markdown(f'<div class="event-card" style="border-left-color: {color_map.get(r["status"], "#ccc")};"><b>{r["status"]}</b><br>{r["guest_name"]}<br><small>{r["property_name"]}</small><br><small>📅 {r["start_date"].strftime("%b %d, %Y")}</small></div>', unsafe_allow_html=True)

# --- 7. MAIN LOGIC ---
st.sidebar.title(f"🌍 {COMPANY_NAME}")
role = st.sidebar.radio("Switch View:", ["Manager (Team View)", f"Owner - {PROP_SWAKOP}", f"Owner - {PROP_PLETT}"])

if role == "Manager (Team View)":
    st.title("Event Calendar Dashboard")
    with st.expander("➕ Add New Internal Booking Request", expanded=True):
        with st.form("new_request"):
            c1, c2, c3, c4 = st.columns(4)
            p = c1.selectbox("Property", PROPERTIES)
            g = c2.text_input("Guest Name")
            s = c3.date_input("Check-In")
            e = c4.date_input("Check-Out")
            if st.form_submit_button("Submit Request"):
                if g:
                    res = add_internal_booking(p, g, str(s), str(e))
                    if isinstance(res, Exception):
                        st.error(f"❌ Database Error: {res}")
                    else:
                        send_email_notification(f"🔔 Request: {p}", f"New request for {g} at {p} ({s} to {e}).")
                        st.success("✅ Saved to database!")
                        st.rerun()
                else: st.error("Please enter a Guest Name.")
    
    i_df, a_df = get_internal_bookings(), get_all_airbnb_bookings()
    draw_month_calendar(pd.concat([i_df, a_df], ignore_index=True))

    st.markdown("---")
    st.subheader("🛠️ Database Diagnostic View")
    st.write("If requests aren't showing up, check if they appear in this table:")
    st.dataframe(i_df, use_container_width=True)

else:
    prop_name = role.split("Owner - ")[1]
    st.title(f"{prop_name} Portal")
    st.subheader("🔔 Pending Approvals")
    df_p = get_internal_bookings(property_name=prop_name, status='PENDING')
    if not df_p.empty:
        for idx, row in df_p.iterrows():
            col_t, col_b1, col_b2 = st.columns([3, 1, 1])
            col_t.write(f"**{row['guest_name']}** ({row['start_date']} to {row['end_date']})")
            if col_b1.button("✅ Approve", key=f"a{row['id']}"):
                update_status(row['id'], 'APPROVED')
                send_email_notification(f"✅ Approved: {row['guest_name']}", f"Booking for {row['guest_name']} at {prop_name} approved.")
                st.rerun()
            if col_b2.button("❌ Reject", key=f"r{row['id']}"):
                update_status(row['id'], 'REJECTED')
                send_email_notification(f"❌ Rejected: {row['guest_name']}", f"Booking for {row['guest_name']} at {prop_name} rejected.")
                st.rerun()
    else: st.info("✅ No pending requests for this property.")
    
    st.markdown("---")
    a_df, i_df = get_all_airbnb_bookings(), get_internal_bookings(property_name=prop_name, status='APPROVED')
    a_df = a_df[a_df['property_name'] == prop_name] if not a_df.empty else a_df
    draw_month_calendar(pd.concat([i_df, a_df], ignore_index=True))
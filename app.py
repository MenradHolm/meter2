import streamlit as st
import pandas as pd
import requests
from icalendar import Calendar
from datetime import datetime, date, timedelta
from supabase import create_client, Client
from streamlit_calendar import calendar
import smtplib
from email.mime.text import MIMEText

# --- APP LAYOUT & THEME OVERRIDE ---
st.set_page_config(page_title="Meter2 Properties Command Center", layout="wide", initial_sidebar_state="expanded")

# --- CUSTOM CSS FOR MOCKUP STYLING ---
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;700&display=swap');
html, body, [class*="css"]  {
    font-family: 'Roboto', sans-serif;
}
.stApp {
    background-color: #F4F4F4;
    color: #333333;
}
.fc-header-toolbar {
    background-color: #F65C78 !important; 
    color: white !important;
    padding: 15px !important;
    border-radius: 5px 5px 0 0 !important;
    margin-bottom: 0 !important;
}
.fc-toolbar-title {
    font-weight: 300 !important;
    font-size: 1.5rem !important;
}
.fc-button-primary {
    background-color: transparent !important;
    border-color: white !important;
    box-shadow: none !important;
}
.fc-button-primary:hover {
    background-color: rgba(255,255,255,0.2) !important;
}
.fc-view-harness {
    background-color: white !important;
    border-radius: 0 0 5px 5px !important;
    box-shadow: 0 4px 6px rgba(0,0,0,0.05);
}
.event-card {
    background-color: white;
    padding: 15px;
    border-radius: 5px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    margin-bottom: 15px;
    border-left: 4px solid;
}
</style>
""", unsafe_allow_html=True)

# --- SETUP SUPABASE CONNECTION ---
@st.cache_resource
def init_connection() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_connection()

# --- CUSTOMIZATION ---
COMPANY_NAME = "Meter2 Properties"
PROP_SWAKOP = "Starshine Guesthouse (Swakopmund)"
PROP_PLETT = "Melkweg Farmhouse (Plettenberg)"
PROPERTIES = [PROP_SWAKOP, PROP_PLETT]

# --- RECIPIENT EMAILS ---
NOTIFICATION_EMAILS = [
    "nita@holmlab.co.za", 
    "drholm@holmlab.co.za", 
    "info@meter2.co.za"
]

# --- AIRBNB ICAL LINKS ---
URL_SWAKOP = "https://www.airbnb.at/calendar/ical/1269982642892159382.ics?t=1d2c8992d5a847febc8bfa4d68c4dc1d"
URL_PLETT_FULL = "https://www.airbnb.at/calendar/ical/1327289595267027214.ics?t=2fc0352915bf4d0aba96926db8f51aab"
URL_PLETT_LESS = "https://www.airbnb.at/calendar/ical/1525842544711145278.ics?t=7e30a8982d984a0cb483dcd06a3276ca"

# --- EMAIL NOTIFICATION FUNCTION ---
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
        st.error(f"Email notification failed. Error: {e}")

# --- 1. CLOUD DATABASE FUNCTIONS ---
def add_internal_booking(property_name, guest_name, start_date, end_date):
    data = {
        "property_name": property_name,
        "guest_name": guest_name,
        "start_date": start_date,
        "end_date": end_date,
        "status": "PENDING"
    }
    supabase.table("internal_bookings").insert(data)

def update_status(booking_id, new_status):
    supabase.table("internal_bookings").update({"status": new_status}).eq("id", booking_id)

def get_internal_bookings(property_name=None, status=None):
    query = supabase.table("internal_bookings").select("*")
    if property_name:
        query = query.eq("property_name", property_name)
    if status:
        query = query.eq("status", status)
    response = query.execute()
    return pd.DataFrame(response.data) if response.data else pd.DataFrame(columns=['id', 'property_name', 'guest_name', 'start_date', 'end_date', 'status'])

# --- 2. FETCH AIRBNB CALENDARS ---
def fetch_airbnb_events(url, property_name, sub_label=""):
    events = []
    try:
        response = requests.get(url)
        response.raise_for_status()
        cal = Calendar.from_ical(response.content)
        for component in cal.walk('vevent'):
            start = component.get('dtstart').dt
            end = component.get('dtend').dt
            if isinstance(start, datetime): start = start.date()
            if isinstance(end, datetime): end = end.date()
            guest_label = f"AirBnB Booking{' ('+sub_label+')' if sub_label else ''}"
            events.append({
                'property_name': property_name, 'guest_name': guest_label,
                'start_date': str(start), 'end_date': str(end), 'status': 'AIRBNB_CONFIRMED'
            })
    except Exception as e:
        st.error(f"Sync error for {property_name}: {e}")
    return events

@st.cache_data(ttl=300)
def get_all_airbnb_bookings():
    all_events = (fetch_airbnb_events(URL_SWAKOP, PROP_SWAKOP) + 
                  fetch_airbnb_events(URL_PLETT_FULL, PROP_PLETT, "Full Capacity") + 
                  fetch_airbnb_events(URL_PLETT_LESS, PROP_PLETT, "Reduced Capacity"))
    return pd.DataFrame(all_events) if all_events else pd.DataFrame(columns=['property_name', 'guest_name', 'start_date', 'end_date', 'status'])

# --- 3. MONTH CALENDAR VIEW ---
def draw_month_calendar(df):
    if df.empty:
        st.info("No events to display.")
        return
    color_map = {"AIRBNB_CONFIRMED": "#E34C51", "APPROVED": "#1DB9A3", "PENDING": "#F5A623", "REJECTED": "#555555"}
    calendar_events = []
    for _, row in df.iterrows():
        end_date_exclusive = pd.to_datetime(row['end_date']) + timedelta(days=1)
        calendar_events.append({
            "title": f"{row['guest_name']} ({row['property_name'][:8]}...)",
            "start": row['start_date'],
            "end": end_date_exclusive.strftime('%Y-%m-%d'),
            "backgroundColor": color_map.get(row['status'], "#3788d8"),
            "borderColor": color_map.get(row['status'], "#3788d8"),
        })
    calendar_options = {
        "headerToolbar": {"left": "prev", "center": "title", "right": "next"},
        "initialView": "dayGridMonth", "height": 650,
        "selectable": False, "editable": False, "eventStartEditable": False, "eventDurationEditable": False
    }
    cal_col, list_col = st.columns([2.5, 1])
    with cal_col:
        calendar(events=calendar_events, options=calendar_options)
    with list_col:
        st.markdown("<h4 style='color: #666; font-weight: 400;'>Upcoming Check-Ins</h4>", unsafe_allow_html=True)
        df['start_date'] = pd.to_datetime(df['start_date'])
        future = df[df['start_date'] >= pd.Timestamp.today()].sort_values('start_date').head(5)
        for _, row in future.iterrows():
            st.markdown(f"""<div class="event-card" style="border-left-color: {color_map.get(row['status'], '#ccc')};">
                <div style="font-size: 0.8em; color: {color_map.get(row['status'], '#ccc')}; font-weight: bold;">{row['status']}</div>
                <div style="font-weight: bold;">{row['guest_name']}</div>
                <div style="font-size: 0.9em; color: #666;">{row['property_name']}</div>
                <div style="font-size: 0.8em; color: #999;">📅 {row['start_date'].strftime('%B %d, %Y')}</div>
            </div>""", unsafe_allow_html=True)

# --- 4. APP LAYOUT & LOGIC ---
st.sidebar.title(f"🌍 {COMPANY_NAME}")
role = st.sidebar.radio("Switch View:", ["Manager (Team View)", f"Owner - {PROP_SWAKOP}", f"Owner - {PROP_PLETT}"])

if role == "Manager (Team View)":
    st.title("Event Calendar Dashboard")
    with st.expander("➕ Add New Internal Booking Request"):
        with st.form("new_request"):
            c1, c2, c3, c4 = st.columns(4)
            p, g = c1.selectbox("Property", PROPERTIES), c2.text_input("Guest Name")
            s, e = c3.date_input("Check-In"), c4.date_input("Check-Out")
            if st.form_submit_button("Submit Request"):
                add_internal_booking(p, g, str(s), str(e))
                send_email_notification(f"🔔 New Booking Request: {p}", f"New request for {g} from {s} to {e} for {p}.\nLog in to approve.")
                st.success("Request saved & Emails sent!"); st.rerun()
    i_df, a_df = get_internal_bookings(), get_all_airbnb_bookings()
    draw_month_calendar(pd.concat([i_df, a_df], ignore_index=True))
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
                send_email_notification(f"✅ APPROVED: {row['guest_name']}", f"Booking for {row['guest_name']} at {prop_name} was APPROVED.")
                st.rerun()
            if col_b2.button("❌ Reject", key=f"r{row['id']}"):
                update_status(row['id'], 'REJECTED')
                send_email_notification(f"❌ REJECTED: {row['guest_name']}", f"Booking for {row['guest_name']} at {prop_name} was REJECTED.")
                st.rerun()
    else:
        st.info("✅ No pending requests for this property at the moment.")
    st.markdown("---")
    a_df, i_df = get_all_airbnb_bookings(), get_internal_bookings(property_name=prop_name)
    a_df = a_df[a_df['property_name'] == prop_name] if not a_df.empty else a_df
    i_df = i_df[i_df['status'] == 'APPROVED'] if not i_df.empty else i_df
    draw_month_calendar(pd.concat([i_df, a_df], ignore_index=True))
# app_streamlit_final_full.py
import streamlit as st
import googlemaps
from datetime import datetime
import logging
from fpdf import FPDF
from bs4 import BeautifulSoup
import polyline
import requests
from io import BytesIO
import textwrap
import os
import folium
from streamlit_folium import st_folium

# ---------------- Logging ----------------
logging.basicConfig(filename='app.log', level=logging.INFO,
                    format='%(asctime)s:%(levelname)s:%(message)s')

# ---------------- Google Maps ----------------
API_KEY = "AIzaSyAQ8W-wL05MEyzeEAPCTZNhjbRUYqF9e7g"
gmaps = googlemaps.Client(key=API_KEY)

st.set_page_config(page_title="Reisevergleich Schweiz", layout="wide")
st.title("Reisevergleich: Auto vs Öffentlicher Verkehr (OEV)")

# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("Reisedaten eingeben")
    start = st.text_input("Startort")
    destination = st.text_input("Zielort")
    date = st.date_input("Datum", datetime.today())
    time_input = st.time_input("Abfahrtszeit", datetime.now().time())
    hourly_wage = st.number_input("Stundenlohn (CHF)", min_value=0.0, value=30.0, step=1.0)
    avg_fuel_cost = st.number_input("Benzinkosten pro 100 km (CHF)", min_value=0.0, value=12.0, step=0.1)
    avg_car_consumption = st.number_input("Verbrauch Auto (l/100 km)", min_value=0.0, value=7.0, step=0.1)
    st.markdown("---")
    st.markdown("Hinweis: Karten werden über Folium (Web) und Google Static Maps (PDF) dargestellt.")

# ---------------- Helper ----------------
def timestamp_from_date_time(d, t):
    return int(datetime.combine(d, t).timestamp())

def clean_html(html_text):
    if not html_text: return ""
    return BeautifulSoup(html_text, "html.parser").get_text(separator=" ")

def safe_text(text, width=90):
    text = text.replace('\n',' ').replace('\r','')
    lines = textwrap.wrap(text, width=width)
    return lines

# ---------------- Google Directions ----------------
def get_route(start_loc, dest_loc, mode="driving"):
    try:
        ts = timestamp_from_date_time(date, time_input)
        directions = gmaps.directions(start_loc,dest_loc,mode=mode,departure_time=ts,language="de")
        return directions[0] if directions else None
    except Exception as e:
        logging.error(f"get_route Fehler: {e}")
        st.error(f"Google Maps Fehler: {e}")
        return None

def calculate_costs_auto(dist_km, dur_h):
    fuel=dist_km*avg_car_consumption/100*avg_fuel_cost
    wage=dur_h*hourly_wage
    return fuel+wage

def get_sbb_ticket_price(start_loc, dest_loc, date_obj, time_obj):
    try:
        r=requests.get("https://timetable.search.ch/api/route.json",
                       params={"from":start_loc,"to":dest_loc,"date":date_obj.strftime("%Y-%m-%d"),
                               "time":time_obj.strftime("%H:%M")}, timeout=8)
        data=r.json()
        return float(data.get("connections",[{}])[0].get("fare",30.0))
    except: return 30.0

def get_transit_transfers_full(route_transit):
    if not route_transit:
        return []
    transfers = []

    legs = route_transit['legs'][0]
    steps = legs.get('steps', [])
    for step in steps:
        if step.get('travel_mode') == 'TRANSIT':
            dep_stop = step['transit_details']['departure_stop']['name']
            dep_time = step['transit_details']['departure_time']['text']
            transfers.append(f"Start: {dep_stop} - {dep_time}")
            break

    prev_line = None
    prev_arr_stop = None
    for step in steps:
        if step.get('travel_mode') == 'TRANSIT':
            details = step['transit_details']
            line_name = details.get('line', {}).get('short_name') or details.get('line', {}).get('name')
            arr_stop = details['arrival_stop']['name']
            arr_time = details['arrival_time']['text']
            if prev_line and prev_line != line_name:
                transfers.append(f"Umstieg: {prev_arr_stop} - {arr_time}")
            prev_line = line_name
            prev_arr_stop = arr_stop
    last_transit = [s for s in steps if s.get('travel_mode')=='TRANSIT'][-1]
    arr_stop = last_transit['transit_details']['arrival_stop']['name']
    arr_time = last_transit['transit_details']['arrival_time']['text']
    transfers.append(f"Ziel: {arr_stop} - {arr_time}")
    return transfers

# ---------------- Folium Map (mit Fußwegen zu Haltestellen) ----------------
def create_map(route, start, destination):
    if not route:
        return None
    start_coords = [route['legs'][0]['start_location']['lat'], route['legs'][0]['start_location']['lng']]
    end_coords = [route['legs'][0]['end_location']['lat'], route['legs'][0]['end_location']['lng']]
    m = folium.Map(location=start_coords, zoom_start=12)
    folium.Marker(location=start_coords, popup=start, icon=folium.Icon(color='green')).add_to(m)
    folium.Marker(location=end_coords, popup=destination, icon=folium.Icon(color='red')).add_to(m)

    points = polyline.decode(route['overview_polyline']['points'])
    folium.PolyLine(points, color="blue", weight=5, opacity=0.7).add_to(m)

    # Fußwege zu Haltestellen
    for step in route['legs'][0].get('steps', []):
        if step['travel_mode']=='TRANSIT':
            dep = step['transit_details']['departure_stop']['location']
            arr = step['transit_details']['arrival_stop']['location']
            # Fußweg zum Start der Linie
            folium.PolyLine([[dep['lat'],dep['lng']],[dep['lat'],dep['lng']]], color="orange", dash_array="5,10", weight=3).add_to(m)
            # Fußweg vom Ziel der Linie
            folium.PolyLine([[arr['lat'],arr['lng']],[arr['lat'],arr['lng']]], color="orange", dash_array="5,10", weight=3).add_to(m)
    return m

# ---------------- Google Static Maps für PDF ----------------
def static_map_save(route, start, destination, filename):
    url = f"https://maps.googleapis.com/maps/api/staticmap?size=600x400&key={API_KEY}"
    url += f"&markers=color:green|label:S|{start}&markers=color:red|label:Z|{destination}"
    if route:
        poly = route.get('overview_polyline', {}).get('points')
        if poly:
            url += f"&path=enc:{poly}|color:blue|weight:5"
    r = requests.get(url)
    with open(filename, "wb") as f:
        f.write(r.content)
    return filename

# ---------------- PDF ----------------
def generate_pdf_final(route_auto, route_transit, start, destination, date, time_input, output_file="Reisevergleich.pdf"):
    pdf = FPDF('P','mm','A4')
    pdf.add_page()
    pdf.set_auto_page_break(True, margin=15)

    fonts_dir = "fonts"
    pdf.add_font("DejaVu","", os.path.join(fonts_dir,"DejaVuSans.ttf"), uni=True)
    pdf.add_font("DejaVu","B", os.path.join(fonts_dir,"DejaVuSans-Bold.ttf"), uni=True)
    pdf.add_font("DejaVu","I", os.path.join(fonts_dir,"DejaVuSans-Oblique.ttf"), uni=True)
    pdf.add_font("DejaVu","BI", os.path.join(fonts_dir,"DejaVuSans-BoldOblique.ttf"), uni=True)
    pdf.set_font("DejaVu","",12)
    content_width = 190

    # Titel
    pdf.set_font("DejaVu","B",16)
    pdf.cell(0,12,f"Reisevergleich: Auto vs Öffentlicher Verkehr", ln=True, align="C")
    pdf.ln(5)
    pdf.set_font("DejaVu","",12)
    pdf.multi_cell(content_width,6,f"Von {start} nach {destination} am {date} | Abfahrt: {time_input.strftime('%H:%M')}")
    pdf.ln(4)

    # Karten
    try:
        if route_auto:
            auto_img_file = static_map_save(route_auto, start, destination, "tmp_auto.png")
            pdf.image(auto_img_file, x=10, y=pdf.get_y(), w=90)
        if route_transit:
            ov_img_file = static_map_save(route_transit, start, destination, "tmp_ov.png")
            pdf.image(ov_img_file, x=105, y=pdf.get_y(), w=90)
        pdf.ln(80)
    except Exception as e:
        logging.error(f"Karten Fehler PDF: {e}")

    # Kosten Tabelle
    pdf.set_font("DejaVu","B",11)
    pdf.set_fill_color(200,230,255)
    pdf.set_xy(10, pdf.get_y())
    pdf.cell(90,8,"Auto", border=1, fill=True)
    pdf.set_fill_color(200,255,200)
    pdf.cell(90,8,"ÖV", border=1, fill=True, ln=True)
    pdf.set_font("DejaVu","",11)

    if route_auto:
        dist_auto = route_auto['legs'][0]['distance']['value']/1000
        dur_auto = route_auto['legs'][0]['duration']['value']/3600
        cost_auto = calculate_costs_auto(dist_auto,dur_auto)
        left_text = f"Distanz: {dist_auto:.1f} km\nDauer: {dur_auto*60:.0f} Min\nKosten inkl. Lohn: CHF {cost_auto:.2f}"
    else:
        left_text = "Keine Auto-Route verfügbar."
    pdf.multi_cell(90,5,"\n".join(safe_text(left_text)), border=1)

    if route_transit:
        dist_ov = route_transit['legs'][0]['distance']['value']/1000
        dur_ov = route_transit['legs'][0]['duration']['value']/3600
        ticket_price = get_sbb_ticket_price(start,destination,date,time_input)
        cost_ov = ticket_price + dur_ov*hourly_wage
        right_text = f"Distanz: {dist_ov:.1f} km\nDauer: {dur_ov*60:.0f} Min\nTicketpreis: CHF {ticket_price:.2f}\nKosten inkl. Lohn: CHF {cost_ov:.2f}"
    else:
        right_text = "Keine OEV-Route verfügbar."
    pdf.set_xy(105, pdf.get_y()-5*(left_text.count('\n')+1))
    pdf.multi_cell(90,5,"\n".join(safe_text(right_text)), border=1)
    pdf.ln(8)

    # Wegbeschreibungen
    def add_steps(title, route):
        if not route: return
        pdf.set_font("DejaVu","B",11)
        pdf.cell(0,6,title, ln=True)
        pdf.set_font("DejaVu","",11)
        for step in route['legs'][0].get('steps', []):
            instr = clean_html(step.get('html_instructions',''))
            for line in safe_text(instr, width=90):
                if pdf.get_y() > 270: pdf.add_page()
                pdf.multi_cell(content_width,5,line)
        pdf.ln(2)

    add_steps("Wegbeschreibung (Auto)", route_auto)
    add_steps("Wegbeschreibung (OEV)", route_transit)

    # Umsteigeorte
    transfers_full = get_transit_transfers_full(route_transit)
    if transfers_full:
        pdf.set_font("DejaVu","B",11)
        pdf.cell(0,6,"Haltestellen und Umstiege im OEV:", ln=True)
        pdf.set_font("DejaVu","",11)
        for t in transfers_full:
            if pdf.get_y() > 270: pdf.add_page()
            pdf.multi_cell(content_width,5,t)
        pdf.ln(2)

    pdf.set_font("DejaVu","I",8)
    pdf.multi_cell(content_width,5,"Hinweis: Routen und Preise stammen von Google Maps bzw. timetable.search.ch. Preise sind indikativ.")

    try:
        pdf.output("Reisevergleich.pdf")
        st.success(f"PDF erstellt: Reisevergleich.pdf")
        logging.info("PDF erstellt")
    except Exception as e:
        st.error(f"Fehler beim PDF speichern: {e}")
        logging.error(f"PDF Fehler: {e}")

# ---------------- Main ----------------
if start.strip()!="" and destination.strip()!="":
    route_auto=get_route(start,destination,"driving")
    route_transit=get_route(start,destination,"transit")

    col1,col2=st.columns(2)
    if route_auto:
        with col1:
            st.subheader("Auto")
            dist_auto=route_auto['legs'][0]['distance']['value']/1000
            dur_auto=route_auto['legs'][0]['duration']['value']/3600
            cost_auto=calculate_costs_auto(dist_auto,dur_auto)
            st.metric("Distanz",f"{dist_auto:.1f} km")
            st.metric("Dauer",f"{dur_auto*60:.0f} Min")
            st.metric("Kosten inkl. Lohn",f"CHF {cost_auto:.2f}")
            m_auto = create_map(route_auto, start, destination)
            st_folium(m_auto, width=700, height=400)

    if route_transit:
        with col2:
            st.subheader("ÖV")
            dist_ov=route_transit['legs'][0]['distance']['value']/1000
            dur_ov=route_transit['legs'][0]['duration']['value']/3600
            ticket_price=get_sbb_ticket_price(start,destination,date,time_input)
            cost_ov=ticket_price+dur_ov*hourly_wage
            st.metric("Distanz",f"{dist_ov:.1f} km")
            st.metric("Dauer",f"{dur_ov*60:.0f} Min")
            st.metric("Kosten inkl. Lohn",f"CHF {cost_ov:.2f}")
            m_ov = create_map(route_transit, start, destination)
            st_folium(m_ov, width=700, height=400)

        transfers_full = get_transit_transfers_full(route_transit)
        if transfers_full:
            st.subheader("Haltestellen und Umstiege im ÖV")
            for t in transfers_full:
                st.write(t)

    st.divider()
    if st.button("PDF erstellen"):
        generate_pdf_final(route_auto, route_transit, start, destination, date, time_input)
else:
    st.warning("Bitte Start- und Zielort eingeben.")

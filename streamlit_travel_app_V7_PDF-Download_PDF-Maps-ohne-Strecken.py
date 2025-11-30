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

st.set_page_config(page_title="Reisevergleich Schweiz", layout="wide")
st.title("Reisevergleich: Auto vs Öffentlicher Verkehr (OEV)")

# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("Reisedaten eingeben")
    
    # Hinweis für API-Key
    st.markdown("""
    <div style="background-color:#FFDDDD; padding:10px; border-radius:5px; margin-bottom:10px; text-align:center">
    ⚠️  Bitte Google Maps API Key eingeben!  ⚠️<br/>Ohne Key können Routen und PDF nicht erstellt werden.
    </div>
    """, unsafe_allow_html=True)
    
    # Google Maps API-Key Eingabe
    API_KEY = st.text_input("Google Maps API Key", type="password")
    
    st.markdown("---")
    start = st.text_input("Startort")
    destination = st.text_input("Zielort")
    date = st.date_input("Datum", datetime.today())
    time_input = st.time_input("Abfahrtszeit", datetime.now().time())
    st.markdown("---")
    hourly_wage = st.number_input("Stundenlohn (CHF)", min_value=0.0, value=30.0, step=1.0)

    car_comp_km = st.number_input("Auto-Kilometerentschädigung \n(0.70–0.80 CHF/km)", min_value=0.0, value=0.75, step=0.01)

    st.markdown("---")
    st.markdown("Hinweis: Karten werden über Folium (Web) und Google Static Maps (PDF) dargestellt.")

# ---------------- Google Maps Client ----------------
if API_KEY.strip():  
    gmaps = googlemaps.Client(key=API_KEY)
else:
    gmaps = None
    st.sidebar.warning("Bitte Google Maps API Key eingeben, um Routen abzufragen.")

# ---------------- Helper ----------------
def timestamp_from_date_time(d, t):
    return int(datetime.combine(d, t).timestamp())

def clean_html(html_text):
    if not html_text:
        return ""
    return BeautifulSoup(html_text, "html.parser").get_text(separator=" ")

def safe_text(text, width=90):
    text = text.replace('\n',' ').replace('\r','')
    lines = textwrap.wrap(text, width=width)
    return lines

# ---------------- Google Directions ----------------
def get_route(start_loc, dest_loc, mode="driving"):
    if not gmaps:
        st.error("Google Maps Client nicht initialisiert. API Key fehlt.")
        return None
    try:
        ts = timestamp_from_date_time(date, time_input)
        directions = gmaps.directions(start_loc, dest_loc, mode=mode, departure_time=ts, language="de")
        return directions[0] if directions else None
    except Exception as e:
        logging.error(f"get_route Fehler: {e}")
        st.error(f"Google Maps Fehler: {e}")
        return None

def calculate_costs_auto_old(dist_km, dur_h):
    comp = dist_km * car_comp_km
    wage = dur_h * hourly_wage
    return comp + wage

def calculate_costs_auto(dist_km, dur_h):
    comp = dist_km * car_comp_km
    wage = dur_h * hourly_wage
    total = comp + wage
    return {
        "comp": comp,
        "wage": wage,
        "total": total
    }

def calculate_costs_ov(dist_km, dur_h):
    base_price: float = 2.80
    price_per_km: float = 0.31

    ticket = base_price + (dist_km * price_per_km)
    wage = dur_h * hourly_wage
    total = ticket + wage
    return {
        "ticket": ticket,
        "wage": wage,
        "total": total
    }

def get_sbb_ticket_price(start_loc, dest_loc, date_obj, time_obj):
    try:
        r = requests.get(
            "https://timetable.search.ch/api/route.json",
            params={
                "from": start_loc,
                "to": dest_loc,
                "date": date_obj.strftime("%Y-%m-%d"),
                "time": time_obj.strftime("%H:%M")
            },
            timeout=8
        )
        data = r.json()
        return float(data.get("connections", [{}])[0].get("fare", 30.0))
    except:
        return 30.0

def get_ticket_price_opendata(start, dest, date_obj=None, time_obj=None, default_price=30.0):
    if date_obj is None:
        date_obj = datetime.now().date()
    if time_obj is None:
        time_obj = datetime.now().time()

    url = "https://transport.opendata.ch/v1/connections"
    params = {
        "from": start,
        "to": dest,
        "date": date_obj.strftime("%Y-%m-%d"),
        "time": time_obj.strftime("%H:%M"),
        "limit": 1
    }

    try:
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
        data = r.json()

        connections = data.get("connections")
        if not connections:
            return default_price

        conn0 = connections[0]
        fare = conn0.get("fare")
        if fare is None:
            return default_price

        return float(fare)

    except requests.RequestException as e:
        print(f"[WARN] HTTP-Fehler bei Anfrage: {e}")
        return default_price
    except (ValueError, KeyError) as e:
        print(f"[WARN] Fehler beim Auswerten der API-Antwort: {e}")
        return default_price
    except Exception as e:
        print(f"[WARN] Unbekannter Fehler: {e}")
        return default_price

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
    last_transit = [s for s in steps if s.get('travel_mode') == 'TRANSIT'][-1]
    arr_stop = last_transit['transit_details']['arrival_stop']['name']
    arr_time = last_transit['transit_details']['arrival_time']['text']
    transfers.append(f"Ziel: {arr_stop} - {arr_time}")
    return transfers

# ---------------- Folium Map ----------------
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

    for step in route['legs'][0].get('steps', []):
        if step['travel_mode'] == 'TRANSIT':
            dep = step['transit_details']['departure_stop']['location']
            arr = step['transit_details']['arrival_stop']['location']
            folium.PolyLine([[dep['lat'], dep['lng']], [dep['lat'], dep['lng']]], color="orange", dash_array="5,10", weight=3).add_to(m)
            folium.PolyLine([[arr['lat'], arr['lng']], [arr['lat'], arr['lng']]], color="orange", dash_array="5,10", weight=3).add_to(m)
    return m

# ---------------- Google Static Maps für PDF ----------------
def static_map_save(route, start, destination, filename):
    if not API_KEY.strip():
        st.error("API Key fehlt, Static Map kann nicht erstellt werden.")
        return None
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
def generate_pdf_final(route_auto, route_transit, start, destination, date, time_input):
    pdf = FPDF('P','mm','A4')
    pdf.add_page()
    pdf.set_auto_page_break(True, margin=15)

    # Fonts
    fonts_dir = "fonts"
    pdf.add_font("DejaVu","", os.path.join(fonts_dir,"DejaVuSans.ttf"), uni=True)
    pdf.add_font("DejaVu","B", os.path.join(fonts_dir,"DejaVuSans-Bold.ttf"), uni=True)
    pdf.add_font("DejaVu","I", os.path.join(fonts_dir,"DejaVuSans-Oblique.ttf"), uni=True)
    pdf.add_font("DejaVu","BI", os.path.join(fonts_dir,"DejaVuSans-BoldOblique.ttf"), uni=True)
    pdf.set_font("DejaVu","",12)

    content_width = 190

    # ---------------- HEADER ----------------
    pdf.set_fill_color(40, 80, 160)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("DejaVu", "B", 18)
    pdf.cell(0, 15, "Reisevergleich: Auto vs Öffentlicher Verkehr", ln=True, align="C", fill=True)

    pdf.ln(5)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("DejaVu","",12)
    pdf.multi_cell(content_width, 6,
        f"Von: {start}\nNach: {destination}\nDatum: {date} – Abfahrt: {time_input.strftime('%H:%M')}"
    )
    pdf.ln(4)

    # ---------------- KARTEN ----------------
    pdf.set_font("DejaVu","B",13)
    pdf.cell(0,8,"Routenübersicht",ln=True)
    pdf.ln(5)

    y_start_map = pdf.get_y()

    try:
        if route_auto:
            auto_file = static_map_save(route_auto, start, destination, "tmp_auto.png")
            pdf.image(auto_file, x=10, y=y_start_map, w=90)
            pdf.set_xy(10, y_start_map - 6)
            pdf.cell(90,6,"Auto-Route",border=0,align="C")

        if route_transit:
            ov_file = static_map_save(route_transit, start, destination, "tmp_ov.png")
            pdf.image(ov_file, x=110, y=y_start_map, w=90)
            pdf.set_xy(110, y_start_map - 6)
            pdf.cell(90,6,"ÖV-Route",border=0,align="C")

        pdf.ln(75)
    except:
        pdf.ln(5)

    # ---------------- VERGLEICHSTABELLE ----------------
    pdf.set_font("DejaVu","B",13)
    pdf.cell(0,8,"Vergleich Auto vs. ÖV", ln=True)
    pdf.ln(1)

    # Hintergrund
    pdf.set_fill_color(230, 240, 255)
    pdf.rect(10, pdf.get_y(), 190, 48, "F")

    start_y = pdf.get_y() + 3

    # Auto
    pdf.set_xy(12, start_y)
    pdf.set_font("DejaVu","B",12)
    pdf.cell(86,6,"Auto", ln=True)

    pdf.set_font("DejaVu","",11)
    dist_auto = route_auto['legs'][0]['distance']['value']/1000 if route_auto else 0
    dur_auto = route_auto['legs'][0]['duration']['value']/3600 if route_auto else 0
    cost_auto = calculate_costs_auto(dist_auto, dur_auto)

    auto_text = (
        f"Distanz: {dist_auto:.1f} km\n"
        f"Dauer: {dur_auto*60:.0f} Min\n"
        f"Kilometerentschädigung: CHF {cost_auto['comp']:.2f}\n"
        f"Lohnkosten: CHF {cost_auto['wage']:.2f}\n"
        f"Total: CHF {cost_auto['total']:.2f}"
    )

    pdf.set_xy(12, start_y + 8)
    pdf.multi_cell(86, 5, auto_text)

    # ÖV
    pdf.set_xy(110, start_y)
    pdf.set_font("DejaVu","B",12)
    pdf.cell(86,6,"ÖV", ln=True)

    pdf.set_font("DejaVu","",11)
    if route_transit:
        dist_ov = route_transit['legs'][0]['distance']['value']/1000
        dur_ov = route_transit['legs'][0]['duration']['value']/3600

        #ticket = get_sbb_ticket_price(start, destination, date, time_input)
        #wage = dur_ov * hourly_wage
        #tot = ticket + wage

        # eigene Berechnung
        cost_ov = calculate_costs_ov(dist_ov,dur_ov)
        ov_text = (
            f"Distanz: {dist_ov:.1f} km\n"
            f"Dauer: {dur_ov*60:.0f} Min\n"
            f"Billetpreis 2.Kl.: CHF {cost_ov['ticket']:.2f}\n"
            f"Lohnkosten: CHF {cost_ov['wage']:.2f}\n"
            f"Total: CHF {cost_ov['total']:.2f}"
        )
    else:
        ov_text = "Keine ÖV-Route verfügbar."

    pdf.set_xy(110, start_y + 8)
    pdf.multi_cell(86, 5, ov_text)

    pdf.ln(50)

    # ---------------- WEGBESCHREIBUNGEN ----------------
    def add_steps(title, route):
        if not route:
            return
        pdf.set_font("DejaVu","B",13)
        pdf.cell(0, 8, title, ln=True)
        pdf.set_font("DejaVu","",11)

        for step in route['legs'][0].get('steps', []):
            txt = clean_html(step.get('html_instructions',''))
            txt = "→ " + txt  # Bullet-Style

            for line in safe_text(txt, width=90):
                if pdf.get_y() > 270:
                    pdf.add_page()
                pdf.multi_cell(0, 5, line)
        pdf.ln(3)

    add_steps("Wegbeschreibung – Auto", route_auto)
    add_steps("Wegbeschreibung – ÖV", route_transit)

    # ---------------- HALTESTELLEN ----------------
    stops = get_transit_transfers_full(route_transit)
    if stops:
        pdf.set_font("DejaVu","B",13)
        pdf.cell(0,8,"Haltestellen & Umstiege", ln=True)
        pdf.set_font("DejaVu","",11)

        for s in stops:
            if pdf.get_y() > 270:
                pdf.add_page()
            pdf.multi_cell(0,5,"→ " + s)
        pdf.ln(3)

    # ---------------- FUSSZEILE ----------------
    pdf.set_y(-30)
    pdf.set_font("DejaVu","I",9)
    pdf.set_text_color(120)
    pdf.multi_cell(0,5,"Quelle: Google Maps\nPDF automatisch erstellt")

    # RETURN AS BYTES FOR STREAMLIT
    try:
        pdf_bytes = pdf.output(dest="S").encode("latin-1")
        return pdf_bytes
    except Exception as e:
        st.error(f"PDF Fehler: {e}")
        return None

# ---------------- Main ----------------
if start.strip() and destination.strip():
    if gmaps:
        route_auto = get_route(start, destination, "driving")
        route_transit = get_route(start, destination, "transit")
    else:
        route_auto = None
        route_transit = None
        st.warning("Google Maps API Key fehlt. Routen können nicht berechnet werden.")

    col1, col2 = st.columns(2)
    
    # Auto
    if route_auto:
        with col1:
            st.subheader("Auto")
            dist_auto = route_auto['legs'][0]['distance']['value']/1000
            dur_auto = route_auto['legs'][0]['duration']['value']/3600
            cost_auto = calculate_costs_auto(dist_auto,dur_auto)
            st.metric("Distanz", f"{dist_auto:.1f} km")
            st.metric("Dauer", f"{dur_auto*60:.0f} Min")
            st.markdown("---")
            st.metric("Kilometerentschädigung", f"CHF {cost_auto['comp']:.2f}")
            st.metric("Lohnkosten", f"CHF {cost_auto['wage']:.2f}")
            st.markdown("---")
            st.metric("Kosten inkl. Lohn 3", f"CHF {cost_auto['total']:.2f}")
            m_auto = create_map(route_auto, start, destination)
            st_folium(m_auto, width=700, height=400)
    else:
        with col1:
            st.subheader("Auto")
            st.info("Keine Auto-Route verfügbar oder API-Key fehlt.")

    # ÖV
    if route_transit:
        with col2:
            st.subheader("ÖV")
            dist_ov = route_transit['legs'][0]['distance']['value']/1000
            dur_ov = route_transit['legs'][0]['duration']['value']/3600

            # eigene Berechnung (Bildschirmanzeige)
            cost_ov = calculate_costs_ov(dist_ov,dur_ov)

            st.metric("Distanz", f"{dist_ov:.1f} km")
            st.metric("Dauer", f"{dur_ov*60:.0f} Min")
            st.markdown("---")
            st.metric("Billetpreis 2.Kl.", f"CHF {cost_ov['ticket']:.2f}")
            st.metric("Lohnkosten", f"CHF {cost_ov['wage']:.2f}")
            st.markdown("---")
            st.metric("Kosten inkl. Lohn 4", f"CHF {cost_ov['total']:.2f}")
            m_ov = create_map(route_transit, start, destination)
            st_folium(m_ov, width=700, height=400)

            transfers_full = get_transit_transfers_full(route_transit)
            if transfers_full:
                st.subheader("Haltestellen und Umstiege im ÖV")
                for t in transfers_full:
                    st.write(t)
    else:
        with col2:
            st.subheader("ÖV")
            st.info("Keine ÖV-Route verfügbar oder API-Key fehlt.")

    st.divider()

    # PDF erzeugen + Download
    if st.button("PDF erstellen"):
        if gmaps:
            pdf_bytes = generate_pdf_final(route_auto, route_transit, start, destination, date, time_input)
            if pdf_bytes:
                st.success("PDF wurde erfolgreich erstellt!")
                st.download_button(
                    label="PDF herunterladen",
                    data=pdf_bytes,
                    file_name="Reisevergleich.pdf",
                    mime="application/pdf"
                )
        else:
            st.warning("PDF kann nicht erstellt werden, da API-Key fehlt.")
else:
    st.warning("Bitte Start- und Zielort eingeben.")

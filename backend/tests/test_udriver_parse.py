from browser_agent.udriver import parse_trip, spoken_plate, trip_booked

TRIP_PAGE = """[185] main ''
\t[319] generic, live='polite', relevant='additions text'
\t\t[329] heading 'Heading to Pacific Cafe'
\t\t[330] button '8:12 PM'
\t\t\t[333] paragraph ''
\t\t\t\tStaticText '8:12 PM'
\t\t[342] image 'Udriver Car', url='https://evals-udriver.vercel.app/x.png'
\t\t[345] heading 'Alvaro'
\t\t[346] heading '9L13XK'
\t\t[347] heading 'Toyota Prius'
\t\t[350] heading '4.99'
\t\t[353] button ''
\t\tStaticText 'Security'
\t\t[370] image 'PickUp Location'
\t\t[373] heading 'Fitness Urbano'
\t\t[374] heading '80 Missouri Street, San Francisco'
\t\t[376] image 'search'
\t\t[379] heading 'Pacific Cafe'
\t\t[380] heading '7000 Geary Boulevard, San Francisco'
\t\t[383] image 'Payment Method Cash', url='https://evals-udriver.vercel.app/y.png'
\t\t[385] heading '$ 13.30'
\t\t[386] heading 'Udriver Cash'
\t\t[388] button 'Cancel'
"""

SEARCHING = """[185] main ''
\t[319] generic, live='polite', relevant='additions text'
\t\t[321] progressbar '', valuemin=0, valuemax=100, valuetext=''
\t\tStaticText 'Searching drivers, please wait...'
"""


def test_parse_trip_reads_driver_car_plate_and_price():
    trip = parse_trip(TRIP_PAGE)
    assert trip["driver"] == "Alvaro" and trip["plate"] == "9L13XK" and trip["car"] == "Toyota Prius" and trip["rating"] == "4.99"
    assert trip["pickup"] == "Fitness Urbano" and trip["pickup_address"] == "80 Missouri Street, San Francisco"
    assert trip["dropoff"] == "Pacific Cafe" and trip["dropoff_address"] == "7000 Geary Boulevard, San Francisco"
    assert trip["price"] == 13.30 and trip["eta_label"] == "8:12 PM"
    assert trip_booked(trip)


def test_parse_trip_before_a_driver_is_assigned():
    trip = parse_trip(SEARCHING)
    assert not trip_booked(trip) and trip["driver"] == "" and trip["price"] == 0.0
    assert not trip_booked(parse_trip(""))


def test_spoken_plate():
    assert spoken_plate("9L13XK") == "9 L 1 3 X K"
    assert spoken_plate("") == ""

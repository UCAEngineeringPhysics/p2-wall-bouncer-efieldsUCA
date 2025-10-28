# File: main.py
import network
import socket
import time
import json
import random

from dual_motor_driver import DualMotorDriver
from hri_controller import HRIController
from ultrasonic_ranger import UltrasonicRanger

# --- CONFIGURATION (Proven working pins) ---
WIFI_SSID = "BotSpot"
WIFI_PASSWORD = "physicsrules"
LEFT_MOTOR_PINS = (7, 9, 8)
RIGHT_MOTOR_PINS = (15, 13, 14)
MOTOR_STBY_PIN = 12

HRI_BUTTON_PIN = 4
HRI_LED_PINS = (16, 17, 18)
ULTRASONIC_TRIG_PIN = 3
ULTRASONIC_ECHO_PIN = 2
ULTRASONIC_LED_PINS = (19, 20, 21)

# Behavior Tuning
MAX_SPEED = 0.9
SLOW_SPEED = 0.4
STOP_DISTANCE_CM = 10.0
SLOW_DOWN_DISTANCE_CM = 20.0
TURN_SPEED = 0.8
TURN_90_DURATION_S = 0.6 
ESCAPE_CLEARANCE_CM = 40.0

# --- Hardware Initialization ---
dmd = DualMotorDriver(LEFT_MOTOR_PINS, RIGHT_MOTOR_PINS, MOTOR_STBY_PIN)
hri = HRIController(HRI_BUTTON_PIN, HRI_LED_PINS)
ranger = UltrasonicRanger(ULTRASONIC_TRIG_PIN, ULTRASONIC_ECHO_PIN, ULTRASONIC_LED_PINS)

# --- ASSIGNMENT-COMPLIANT STARTUP CHECK ---
print("Performing system check...")
ranger.update()
time.sleep(0.2)
ranger.update() # Give sensor time for a first reading

if hri.button.value() == 0 and ranger.get_distance_cm() > 0:
    print("System check PASSED. Initializing...")
    end_ms = time.ticks_add(time.ticks_ms(), 2000)
    while time.ticks_diff(end_ms, time.ticks_ms()) > 0:
        hri._set_color(65535, 65535, 65535)
        ranger._set_color(1,1,1)
        time.sleep(0.1) # 100ms on (5Hz)
        hri._set_color(0, 0, 0)
        ranger._set_color(0,0,0)
        time.sleep(0.1) # 100ms off
else:
    print("System check FAILED. (Button pressed or sensor error). Halting.")
    while True:
        hri._set_color(65535, 0, 0)
        time.sleep(0.5)
        hri._set_color(0, 0, 0)
        time.sleep(0.5)

# --- Wi-Fi Setup ---
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(WIFI_SSID, WIFI_PASSWORD)
print("Connecting to Wi-Fi...")
while not wlan.isconnected() and wlan.status() >= 0:
    time.sleep(1)

if not wlan.isconnected():
    print("WiFi connection failed, continuing offline.")
    IP_ADDRESS = "N/A"
else:
    IP_ADDRESS = wlan.ifconfig()[0]
    print(f"Connected! IP: {IP_ADDRESS}")

# --- Web Page (Built safely using string concatenation) ---
html =  '<!DOCTYPE html><html><head><title>Robot Dashboard</title>'
html += '<style>body{font-family:sans-serif;text-align:center;font-size:1.5em}'
html += '#status{margin-top:40px}.hri-btn{width:250px;height:90px;font-size:24px;margin:20px}'
html += '</style></head><body><h1>Robot Command Center</h1>'
html += '<div id="status"><p>Distance: <strong id="dist">--</strong> cm</p>'
html += '<p>Mode: <strong id="mode">--</strong></p></div>'
html += '<button class="hri-btn" onclick="fetch(\'/hri_toggle\')">Toggle Work/Pause</button>'
html += '<script>setInterval(async()=>{try{const r=await fetch(\'/status\');const d=await r.json();'
html += 'document.getElementById(\'dist\').innerText=d.distance_cm;'
html += 'document.getElementById(\'mode\').innerText=d.hri_mode}'
html += 'catch(e){console.error("Status fetch failed:",e)}},1000)</script>'
html += '</body></html>'

# --- Web Server Setup ---
addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(addr)
s.listen(1)
s.setblocking(False)
print(f"Server listening on http://{IP_ADDRESS}")

# --- Intelligent Behavior Function ---
def escape_and_decide():
    print("Obstacle detected! Finding escape route...")
    dmd.stop()
    
    dmd.move(-0.7, -0.7)
    time.sleep(0.75); ranger.update()
    dmd.stop()
    time.sleep(0.3); ranger.update()

    dmd.move(TURN_SPEED, -TURN_SPEED) # Pivot right
    time.sleep(TURN_90_DURATION_S); ranger.update()
    dmd.stop()
    time.sleep(0.5); ranger.update()
    dist_right = ranger.get_distance_cm()
    print(f"  - Checking right: {dist_right:.1f} cm")
    if dist_right > ESCAPE_CLEARANCE_CM or dist_right < 0:
        print("Decision: Path RIGHT is clear. Taking it.")
        return

    dmd.move(-TURN_SPEED, TURN_SPEED) # Pivot 180 degrees left
    time.sleep(TURN_90_DURATION_S * 2); ranger.update()
    dmd.stop()
    time.sleep(0.5); ranger.update()
    dist_left = ranger.get_distance_cm()
    print(f"  - Checking left: {dist_left:.1f} cm")
    if dist_left > ESCAPE_CLEARANCE_CM or dist_left < 0:
        print("Decision: Path LEFT is clear. Taking it.")
        return
        
    print("Decision: Trapped! Turning around.")
    dmd.move(TURN_SPEED, -TURN_SPEED) # Pivot right again
    time.sleep(TURN_90_DURATION_S) 
    dmd.stop()

# --- Main Intelligent Loop ---
while True:
    try:
        hri.update()
        ranger.update()

        if hri.mode == hri.MODE_WORK:
            # This is the 50% speed reduction logic
            current_max_speed = MAX_SPEED
            if hri.get_total_work_seconds() > 45: 
                current_max_speed = MAX_SPEED * 0.5
            
            distance = ranger.get_distance_cm()
            
            if 0 < distance < STOP_DISTANCE_CM:
                escape_and_decide()
            elif 0 < distance < SLOW_DOWN_DISTANCE_CM:
                dmd.move(SLOW_SPEED * (current_max_speed/MAX_SPEED), SLOW_SPEED * (current_max_speed/MAX_SPEED))
            else:
                dmd.move(current_max_speed, current_max_speed)
        else: # PAUSE MODE
            dmd.stop()

        # --- Web Request Handling ---
        cl = None
        try:
            cl, addr = s.accept()
            request = cl.recv(1024).decode('utf-8')
            path = request.split(' ')[1]
            if path == '/hri_toggle':
                hri.toggle_mode()
                if hri.mode == hri.MODE_PAUSE: dmd.stop()
                cl.send("HTTP/1.0 204 No Content\r\n\r\n")
            elif path == '/status':
                cl.send("HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n")
                status = {"distance_cm": f"{ranger.get_distance_cm():.1f}", "hri_mode": hri.get_mode_str()}
                cl.send(json.dumps(status))
            else:
                cl.send("HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n")
                cl.send(html)
        except OSError as e:
            if e.args[0] != 11: raise
        finally:
            if cl: cl.close()
            
    except Exception as e:
        print(f"Main loop error: {e}")
        dmd.stop()
        time.sleep(5)

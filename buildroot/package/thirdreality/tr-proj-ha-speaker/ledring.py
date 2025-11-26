import paho.mqtt.client as mqtt
import subprocess
import threading
import time
import json
import sys

DEVICE_CONF = "/data/conf/device.json"

# Read MQTT configuration from device.json
try:
    with open(DEVICE_CONF, 'r') as f:
        config = json.load(f)
    
    mqtt_config = config.get('mqtt', {})
    BROKER = mqtt_config.get('broker')
    PORT = mqtt_config.get('port')
    USERNAME = mqtt_config.get('user')
    PASSWORD = mqtt_config.get('password')
    
    # Validate all required fields are present and not empty
    if not all([BROKER, PORT, USERNAME, PASSWORD]):
        print("Error: Missing or empty MQTT configuration in device.json")
        sys.exit(1)
    
    # Convert port to integer
    PORT = int(PORT)
    
except FileNotFoundError:
    print(f"Error: Configuration file not found: {DEVICE_CONF}")
    sys.exit(1)
except json.JSONDecodeError as e:
    print(f"Error: Failed to parse JSON: {e}")
    sys.exit(1)
except ValueError as e:
    print(f"Error: Invalid port number: {e}")
    sys.exit(1)
except Exception as e:
    print(f"Error: Failed to read configuration: {e}")
    sys.exit(1)

TOPICS = {
    "speaker/listening": "/usr/share/thirdreality/animation/active-waking.animation",
    "speaker/thinking": "/usr/share/thirdreality/animation/active-thinking.animation",
    "speaker/speaking": "/usr/share/thirdreality/animation/active-talking.animation",
    "speaker/idle": "/usr/share/thirdreality/animation/active-ending.animation",
}

def run_dbus(animation):
    cmd = [
        "dbus-send",
        "--system",
        "--type=signal",
        "/com/3r/EventBus",
        "com._3reality.EventBus.LedShow",
        "boolean:false",
        f"array:string:'{animation}'"
    ]
    try:
        subprocess.run(" ".join(cmd), shell=True, check=True)
        print(f"Executed LED animation: {animation}")
    except subprocess.CalledProcessError as e:
        print(f"Failed to execute dbus-send: {e}")

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Connected to broker")
        for topic in TOPICS.keys():
            client.subscribe(topic)
            print(f"Subscribed to {topic}")
    else:
        print("Failed to connect, return code", rc)

def on_message(client, userdata, msg):
    print(f"Received {msg.topic}: {msg.payload.decode()}")
    if msg.topic in TOPICS:
        animation = TOPICS[msg.topic]

        if msg.topic == "speaker/idle":
            # 延迟2秒执行
            def delayed():
                time.sleep(2)
                run_dbus(animation)
            threading.Thread(target=delayed, daemon=True).start()
        else:
            run_dbus(animation)

client = mqtt.Client()
client.username_pw_set(USERNAME, PASSWORD)
client.on_connect = on_connect
client.on_message = on_message

client.connect(BROKER, PORT, 60)
client.loop_forever()
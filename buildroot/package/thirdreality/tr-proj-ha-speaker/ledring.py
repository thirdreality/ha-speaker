import paho.mqtt.client as mqtt
import subprocess
import threading
import time

BROKER = "10.1.0.58"
PORT = 1883
USERNAME = "r3"
PASSWORD = "shushi6688"

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
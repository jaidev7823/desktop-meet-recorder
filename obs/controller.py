import os
from dotenv import load_dotenv
from obswebsocket import obsws, requests

load_dotenv()

host = os.getenv("OBS_HOST")
port = int(os.getenv("OBS_PORT"))
password = os.getenv("OBS_PASSWORD")

ws = obsws(host, port, password)
ws.connect()


def start_recording():
    ws.call(requests.StartRecord())


def stop_recording():
    ws.call(requests.StopRecord())
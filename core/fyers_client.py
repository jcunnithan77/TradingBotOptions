import os
from fyers_apiv3 import fyersModel
from fyers_apiv3.FyersWebsocket import data_ws
from dotenv import load_dotenv
import json

load_dotenv()

CLIENT_ID = os.getenv("FYERS_CLIENT_ID")
SECRET_KEY = os.getenv("FYERS_SECRET_KEY")
REDIRECT_URI = os.getenv("FYERS_REDIRECT_URI")

# We will save the access token to a local file manually for now
DATA_DIR = os.getenv("DATA_DIR", "./data")
TOKEN_FILE = os.path.join(DATA_DIR, "fyers_token.txt")

def get_auth_link():
    session = fyersModel.SessionModel(
        client_id=CLIENT_ID,
        secret_key=SECRET_KEY,
        redirect_uri=REDIRECT_URI,
        response_type="code",
        grant_type="authorization_code"
    )
    return session.generate_authcode()

def generate_token_from_code(auth_code: str):
    session = fyersModel.SessionModel(
        client_id=CLIENT_ID,
        secret_key=SECRET_KEY,
        redirect_uri=REDIRECT_URI,
        response_type="code",
        grant_type="authorization_code"
    )
    session.set_token(auth_code)
    response = session.generate_token()
    if response.get("s") == "ok":
        access_token = response["access_token"]
        with open(TOKEN_FILE, "w") as f:
            f.write(access_token)
        return access_token
    raise Exception(f"Failed to generate token: {response}")

def get_fyers_client():
    if not os.path.exists(TOKEN_FILE):
        return None
    with open(TOKEN_FILE, "r") as f:
        access_token = f.read().strip()
    
    return fyersModel.FyersModel(client_id=CLIENT_ID, is_async=False, token=access_token, log_path="")

# Websocket client wrapper
class FyersSocketClient:
    def __init__(self, on_message_callback):
        self.access_token = None
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, "r") as f:
                self.access_token = f.read().strip()
        
        self.fyers_ws = None
        self.on_message_callback = on_message_callback

    def custom_message(self, msg):
        self.on_message_callback(msg)

    def on_error(self, message):
         print("WS Error:", message)

    def on_close(self, message):
         print("WS Connection closed:", message)

    def on_open(self):
         print("WS Connection opened")
         
    def connect(self):
        if not self.access_token:
            print("Access token not found. Cannot connect to WS.")
            return
            
        data_type = "SymbolUpdate"
        self.fyers_ws = data_ws.FyersDataSocket(
            access_token=f"{CLIENT_ID}:{self.access_token}",
            log_path="",
            litemode=False,
            write_to_file=False,
            reconnect=True,
            on_connect=self.on_open,
            on_close=self.on_close,
            on_error=self.on_error,
            on_message=self.custom_message
        )
        self.fyers_ws.connect()

    def subscribe(self, symbols: list):
        if self.fyers_ws:
            self.fyers_ws.subscribe(symbols=symbols, data_type="SymbolUpdate")

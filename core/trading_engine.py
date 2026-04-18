import asyncio
from sqlalchemy.orm import Session
from db.database import SessionLocal
from db.models import DailyStrike, TradingJournal
from core.fyers_client import FyersSocketClient, get_fyers_client
import threading

class TradingEngine:
    def __init__(self):
        self.ws_client = FyersSocketClient(on_message_callback=self.handle_price_update)
        self.active_symbols = {} # Map symbol string to strike id
        self.fyers = get_fyers_client()
        
    def start_engine(self):
        # Run websocket in a background thread
        ws_thread = threading.Thread(target=self.ws_client.connect, daemon=True)
        ws_thread.start()
        
        # Give it a second to connect, then subscribe to pending trades
        threading.Timer(2.0, self.refresh_subscriptions).start()

    def refresh_subscriptions(self):
        db = SessionLocal()
        pending_strikes = db.query(DailyStrike).filter(DailyStrike.status == "pending").all()
        symbols_to_subscribe = []
        for strike in pending_strikes:
            if strike.fyers_symbol:
                symbols_to_subscribe.append(strike.fyers_symbol)
                self.active_symbols[strike.fyers_symbol] = strike.id
        db.close()
        
        if symbols_to_subscribe:
            print(f"Subscribing to {symbols_to_subscribe}")
            self.ws_client.subscribe(symbols_to_subscribe)

    def handle_price_update(self, message):
         # Message format: {'ltp': 123.45, 'symbol': 'NSE:NIFTY...', ...}
         if not isinstance(message, dict):
            # It could be a list of dicts depending on litemode
            if isinstance(message, list):
                for msg in message:
                    self.process_tick(msg)
         else:
             self.process_tick(message)

    def process_tick(self, msg):
        symbol = msg.get('symbol')
        ltp = msg.get('ltp')
        
        if not symbol or not ltp:
            return
            
        strike_id = self.active_symbols.get(symbol)
        if not strike_id:
            return
            
        # Check against db
        db = SessionLocal()
        strike = db.query(DailyStrike).filter(DailyStrike.id == strike_id).first()
        
        if strike and strike.status == "pending":
            # If current price crosses or touches the entry price
            # Condition usually implies we are waiting for a pullback or breakout.
            # Simplified: If LTP crosses entry price 
            # Note: A robust system maintains history to detect crossover.
            # For this prototype, if we touch or gap past Entry, trigger.
            # Assuming Buy on breakout for Call/Put Options.
            
            # Using > for this example (can be adjusted to cross-over logic)
            if ltp >= strike.entry_price:
                print(f"TRIGGER: {symbol} crossed entry {strike.entry_price}. LTP: {ltp}")
                strike.status = "triggered"
                db.commit()
                self.place_entry_order(strike, ltp, db)
                
        db.close()

    def place_entry_order(self, strike: DailyStrike, ltp: float, db: Session):
        if not self.fyers:
            self.fyers = get_fyers_client()
        
        if not self.fyers:
            print("Cannot place order. Fyers client not initialized.")
            return

        # Place a Market Buy Order
        order_data = {
            "symbol": strike.fyers_symbol,
            "qty": strike.quantity,
            "type": 2, # 2 indicates Market Order
            "side": 1, # 1 implies Buy
            "productType": "MARGIN",
            "limitPrice": 0,
            "stopPrice": 0,
            "validity": "DAY",
            "disclosedQty": 0,
            "offlineOrder": False,
        }
        
        try:
             # In a real environment uncomment this:
             # response = self.fyers.place_order(data=order_data)
             # print("Order Response:", response)
             # fyers_order_id = response.get('id', 'dummy_id')
             
             # MOCK execution for safety
             fyers_order_id = "mock_fyers_id_123"
             
             # Log into Trading Journal
             journal = TradingJournal(
                 strike_id=strike.id,
                 action="BUY",
                 symbol=strike.fyers_symbol,
                 quantity=strike.quantity,
                 price=ltp,
                 order_type="ENTRY",
                 fyers_order_id=fyers_order_id,
                 message="Order placed successfully"
             )
             db.add(journal)
             db.commit()
             
             # After Entry is successful, calculate Stop Loss and Target
             sl_price = strike.entry_price - 20
             target_price = strike.target_1
             
             # Depending on broker, you might place an OCO/Bracket order or just independent orders right away
             self.place_sl_target_orders(strike, sl_price, target_price, db)
             
        except Exception as e:
             print(f"Failed to place order: {e}")

    def place_sl_target_orders(self, strike: DailyStrike, sl_price: float, target_price: float, db: Session):
        # We place a Stop Loss (Sell)
        sl_order_data = {
            "symbol": strike.fyers_symbol,
            "qty": strike.quantity,
            "type": 3, # Stop loss market
            "side": -1, # Sell
            "productType": "MARGIN",
            "limitPrice": 0,
            "stopPrice": sl_price,
            "validity": "DAY"
        }
        
        # We place a Target (Sell) Limit
        target_order_data = {
            "symbol": strike.fyers_symbol,
            "qty": strike.quantity,
            "type": 1, # Limit
            "side": -1, # Sell
            "productType": "MARGIN",
            "limitPrice": target_price,
            "stopPrice": 0,
            "validity": "DAY",
        }
        
        # In a real environment, you might link these or use Fyers BO/CO order types if allowed.
        # This is a mocked log for architecture completion.
        
        journal_sl = TradingJournal(
            strike_id=strike.id, action="SELL", symbol=strike.fyers_symbol, quantity=strike.quantity, 
            price=sl_price, order_type="STOP_LOSS", fyers_order_id="mock_sl_id", message="Pending Stop loss"
        )
        journal_tt = TradingJournal(
            strike_id=strike.id, action="SELL", symbol=strike.fyers_symbol, quantity=strike.quantity, 
            price=target_price, order_type="TARGET", fyers_order_id="mock_tt_id", message="Pending Target"
        )
        db.add_all([journal_sl, journal_tt])
        db.commit()
        print("Placed SL and Target tracking logic.")
        
engine = TradingEngine()

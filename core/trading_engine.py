import asyncio
from datetime import datetime, time
import pytz
from sqlalchemy.orm import Session
from db.database import SessionLocal
from db.models import DailyStrike, TradingJournal
from core.fyers_client import FyersSocketClient, get_fyers_client
import threading
import time as time_module

class TradingEngine:
    def __init__(self):
        self.ws_client = FyersSocketClient(on_message_callback=self.handle_price_update)
        self.active_symbols = {} # Map symbol string to strike id
        self.fyers = get_fyers_client()
        self.timezone = pytz.timezone('Asia/Kolkata')
        
    def get_ist_now(self):
        return datetime.now(self.timezone)

    def is_within_trading_hours(self):
        now = self.get_ist_now()
        start_time = time(9, 0)
        end_time = time(15, 30)
        return start_time <= now.time() <= end_time

    def is_past_cutoff(self):
        """Check if it's past 14:30 (2:30 PM)"""
        now = self.get_ist_now()
        cutoff_time = time(14, 30)
        return now.time() >= cutoff_time

    def start_engine(self):
        # Run websocket in a background thread
        ws_thread = threading.Thread(target=self.ws_client.connect, daemon=True)
        ws_thread.start()
        
        # Give it a second to connect, then subscribe to pending trades
        threading.Timer(2.0, self.refresh_subscriptions).start()
        
        # Start the 2:30 PM Cut-off Monitor
        monitor_thread = threading.Thread(target=self.bg_cutoff_monitor, daemon=True)
        monitor_thread.start()

    def refresh_subscriptions(self):
        today_date = self.get_ist_now().strftime("%Y-%m-%d")
        db = SessionLocal()
        pending_strikes = db.query(DailyStrike).filter(
            DailyStrike.status == "pending",
            DailyStrike.target_date == today_date
        ).all()
        
        # Clear current mapping and rebuild
        self.active_symbols = {}
        symbols_to_subscribe = []
        for strike in pending_strikes:
            if strike.fyers_symbol:
                symbols_to_subscribe.append(strike.fyers_symbol)
                self.active_symbols[strike.fyers_symbol] = strike.id
        db.close()
        
        if symbols_to_subscribe:
            print(f"Refreshing subscriptions for {today_date}: {symbols_to_subscribe}")
            self.ws_client.subscribe(symbols_to_subscribe)

    def bg_cutoff_monitor(self):
        """Background loop to check for 2:30 PM cut-off even if no ticks arrive."""
        while True:
            try:
                if self.is_past_cutoff() and self.is_within_trading_hours():
                    self.check_and_cancel_expired_trades()
            except Exception as e:
                print(f"Monitor Error: {e}")
            time_module.sleep(60) # Check every minute

    def check_and_cancel_expired_trades(self):
        """Cancel all pending trades if no trade has triggered by 14:30."""
        today_date = self.get_ist_now().strftime("%Y-%m-%d")
        db = SessionLocal()
        
        # Check if any trade was already triggered/completed today
        any_triggered = db.query(DailyStrike).filter(
            DailyStrike.target_date == today_date,
            DailyStrike.status.in_(["triggered", "completed", "stopped_out"])
        ).first()

        if not any_triggered:
            # If no trade active, cancel all remaining pendings for today
            pendings = db.query(DailyStrike).filter(
                DailyStrike.target_date == today_date,
                DailyStrike.status == "pending"
            ).all()
            
            if pendings:
                print(f"CUT-OFF REACHED (14:30): Cancelling {len(pendings)} pending trades.")
                for p in pendings:
                    p.status = "cancelled"
                db.commit()
                # Clean up local subscription mapping
                self.active_symbols = {}
        
        db.close()

    def cancel_others_for_today(self, triggered_strike_id):
        """Cancel all other pending trades for today once one executes."""
        today_date = self.get_ist_now().strftime("%Y-%m-%d")
        db = SessionLocal()
        others = db.query(DailyStrike).filter(
            DailyStrike.target_date == today_date,
            DailyStrike.status == "pending",
            DailyStrike.id != triggered_strike_id
        ).all()
        
        if others:
            print(f"MUTUAL EXCLUSION: Cancelling {len(others)} other pending setups.")
            for o in others:
                o.status = "cancelled"
            db.commit()
            # Resync active symbols
            self.refresh_subscriptions()
        db.close()

    def handle_price_update(self, message):
         if not self.is_within_trading_hours():
             return

         if not isinstance(message, dict):
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
            
        db = SessionLocal()
        strike = db.query(DailyStrike).filter(DailyStrike.id == strike_id).first()
        
        if strike and strike.status == "pending":
            # Extra check for cut-off hours within tick processing
            if self.is_past_cutoff():
                db.close()
                self.check_and_cancel_expired_trades()
                return

            if ltp >= strike.entry_price:
                print(f"TRIGGER: {symbol} crossed entry {strike.entry_price}. LTP: {ltp}")
                strike.status = "triggered"
                db.commit()
                # 1. Place the order
                self.place_entry_order(strike, ltp, db)
                # 2. Cancel all other pending trades for today
                self.cancel_others_for_today(strike.id)
                
        db.close()

    def place_entry_order(self, strike: DailyStrike, ltp: float, db: Session):
        if not self.fyers:
            self.fyers = get_fyers_client()
        
        if not self.fyers:
            print("Cannot place order. Fyers client not initialized.")
            return

        order_data = {
            "symbol": strike.fyers_symbol,
            "qty": strike.quantity,
            "type": 2, # Market
            "side": 1, # Buy
            "productType": "MARGIN",
            "limitPrice": 0,
            "stopPrice": 0,
            "validity": "DAY",
            "disclosedQty": 0,
            "offlineOrder": False,
        }
        
        try:
             fyers_order_id = "mock_fyers_id_123"
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
             
             sl_price = strike.entry_price - 20
             target_price = strike.target_1
             self.place_sl_target_orders(strike, sl_price, target_price, db)
             
        except Exception as e:
             print(f"Failed to place order: {e}")

    def place_sl_target_orders(self, strike: DailyStrike, sl_price: float, target_price: float, db: Session):
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

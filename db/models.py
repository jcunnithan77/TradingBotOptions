from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean
from db.database import Base
from datetime import datetime
import pytz

def get_ist_now():
    return datetime.now(pytz.timezone('Asia/Kolkata'))

class DailyStrike(Base):
    __tablename__ = "daily_strikes"

    id = Column(Integer, primary_key=True, index=True)
    instrument = Column(String, index=True)  # e.g., NIFTY, BNIFTY
    strike = Column(String)  # e.g., 24200 CE
    expiry = Column(String)  # e.g., 28 Apr 2026
    fyers_symbol = Column(String, unique=True, index=True) # E.g., NSE:NIFTY24APR24200CE
    
    entry_price = Column(Float)
    target_1 = Column(Float)
    target_2 = Column(Float, nullable=True)
    target_3 = Column(Float, nullable=True)
    stop_loss = Column(Float)

    # Status: pending, triggered, completed, stopped_out
    status = Column(String, default="pending")
    
    quantity = Column(Integer, default=50) # Assuming 1 lot of Nifty = 50, BNifty = 15
    created_at = Column(DateTime, default=get_ist_now)

class TradingJournal(Base):
    __tablename__ = "trading_journal"

    id = Column(Integer, primary_key=True, index=True)
    strike_id = Column(Integer) # Links to DailyStrike
    
    action = Column(String) # BUY, SELL
    symbol = Column(String)
    quantity = Column(Integer)
    price = Column(Float)
    
    order_type = Column(String) # ENTRY, TARGET, STOP_LOSS
    fyers_order_id = Column(String, nullable=True)
    message = Column(String, nullable=True)
    
    timestamp = Column(DateTime, default=get_ist_now)

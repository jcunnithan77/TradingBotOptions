from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import os

from db.database import engine, Base, get_db
from db.models import DailyStrike, TradingJournal
from core.fyers_client import get_auth_link, generate_token_from_code
from core.trading_engine import engine as trading_eng

# Create Database Tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Fyers Trading Bot")

# Ensure directories exist
os.makedirs("static/css", exist_ok=True)
os.makedirs("static/js", exist_ok=True)
os.makedirs("templates", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.on_event("startup")
def startup_event():
    # Start the background trading engine
    trading_eng.start_engine()

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, db: Session = Depends(get_db)):
    strikes = db.query(DailyStrike).order_by(DailyStrike.id.desc()).all()
    journal = db.query(TradingJournal).order_by(TradingJournal.id.desc()).all()
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "strikes": strikes,
        "journal": journal
    })

@app.post("/add_strike")
async def add_strike(
    request: Request,
    instrument: str = Form(...),
    strike: str = Form(...),
    expiry: str = Form(...),
    fyers_symbol: str = Form(...),
    entry_price: float = Form(...),
    target_1: float = Form(...),
    quantity: int = Form(50),
    db: Session = Depends(get_db)
):
    try:
        new_strike = DailyStrike(
            instrument=instrument,
            strike=strike,
            expiry=expiry,
            fyers_symbol=fyers_symbol,
            entry_price=entry_price,
            target_1=target_1,
            target_2=target_1 + 10, # Mock derived
            target_3=target_1 + 20, # Mock derived
            stop_loss=entry_price - 20, # Automatically calculated stop loss
            quantity=quantity,
            status="pending"
        )
        db.add(new_strike)
        db.commit()
        
        # notify engine to subscribe to new symbol
        trading_eng.refresh_subscriptions()
        
    except Exception as e:
        print(f"Error adding strike: {e}")
        
    return RedirectResponse(url="/", status_code=303)

@app.get("/auth_fyers")
async def auth_fyers():
    link = get_auth_link()
    return RedirectResponse(url=link)

@app.get("/auth/callback")
async def auth_callback(auth_code: str = None, s: str = None, message: str = None):
    if s == "ok" and auth_code:
        try:
            token = generate_token_from_code(auth_code)
            return {"status": "success", "message": "Token generated successfully. You can return to the dashboard."}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
    return {"status": "error", "message": message}

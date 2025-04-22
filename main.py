import os
import time
import logging
import threading
import pandas as pd
import numpy as np
import ccxt
from telegram import Bot, Update
from telegram.ext import Updater, CommandHandler, CallbackContext

CONFIG = {
    'TELEGRAM_TOKEN': os.getenv("TELEGRAM_TOKEN"),
    'CHAT_ID': os.getenv("CHAT_ID"),
    'SYMBOLS': ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'LTC/USDT', 'BNB/USDT'],
    'TIMEFRAME': '1m',
    'FETCH_LIMIT': 200,
    'CHECK_INTERVAL': 60,
}

bot = Bot(token=CONFIG['TELEGRAM_TOKEN'])
updater = Updater(token=CONFIG['TELEGRAM_TOKEN'], use_context=True)
dispatcher = updater.dispatcher
last_signals = {s: None for s in CONFIG['SYMBOLS']}
exchange = ccxt.mexc({'enableRateLimit': True})

def fetch_data(symbol):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=CONFIG['TIMEFRAME'], limit=CONFIG['FETCH_LIMIT'])
    df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
    df['ts'] = pd.to_datetime(df['ts'], unit='ms')
    return df

def compute_indicators(df):
    df['ema7'] = df['close'].ewm(span=7).mean()
    df['ema14'] = df['close'].ewm(span=14).mean()
    df['ema28'] = df['close'].ewm(span=28).mean()
    df['macd'] = df['close'].ewm(span=12).mean() - df['close'].ewm(span=26).mean()
    df['signal'] = df['macd'].ewm(span=9).mean()
    df['hist'] = df['macd'] - df['signal']
    df['rsi'] = compute_rsi(df['close'])
    return df

def compute_rsi(series, period=14):
    delta = series.diff()
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = pd.Series(gain).rolling(period).mean()
    avg_loss = pd.Series(loss).rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def analyze(symbol):
    global last_signals
    try:
        df = fetch_data(symbol)
        df = compute_indicators(df)
        latest = df.iloc[-1]

        bull = latest['ema7'] > latest['ema14'] > latest['ema28'] and latest['hist'] > 0 and latest['rsi'] > 50
        bear = latest['ema7'] < latest['ema14'] < latest['ema28'] and latest['hist'] < 0 and latest['rsi'] < 50

        signal = None
        if bull:
            signal = 'LONG'
        elif bear:
            signal = 'SHORT'

        if signal and signal != last_signals[symbol]:
            msg = (
                f"⚡️ <b>{symbol}</b>\n"
                f"Signal: <b>{signal}</b>\n"
                f"Price: {latest['close']:.2f}\n"
                f"RSI: {latest['rsi']:.2f}, MACD hist: {latest['hist']:.4f}"
            )
            bot.send_message(chat_id=CONFIG['CHAT_ID'], text=msg, parse_mode='HTML')
            last_signals[symbol] = signal
    except Exception as e:
        logging.error(f"Ошибка анализа {symbol}: {e}")

def get_best():
    best = None
    for symbol in CONFIG['SYMBOLS']:
        try:
            df = fetch_data(symbol)
            df = compute_indicators(df)
            latest = df.iloc[-1]

            bull = latest['ema7'] > latest['ema14'] > latest['ema28'] and latest['hist'] > 0 and latest['rsi'] > 50
            bear = latest['ema7'] < latest['ema14'] < latest['ema28'] and latest['hist'] < 0 and latest['rsi'] < 50

            if bull or bear:
                strength = abs(latest['rsi'] - 50) + abs(latest['hist'])
                if not best or strength > best['strength']:
                    best = {
                        'symbol': symbol,
                        'direction': 'LONG' if bull else 'SHORT',
                        'price': latest['close'],
                        'rsi': latest['rsi'],
                        'hist': latest['hist'],
                        'strength': strength
                    }
        except:
            continue
    return best

def cmd_post(update: Update, ctx: CallbackContext):
    update.message.reply_text("🔍 Анализирую рынок...")
    best = get_best()
    if best:
        text = (
            f"⚡️ <b>{best['symbol']}</b>\n"
            f"Signal: <b>{best['direction']}</b>\n"
            f"Price: {best['price']:.2f}\n"
            f"RSI: {best['rsi']:.2f}, MACD hist: {best['hist']:.4f}"
        )
        bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode='HTML')
    else:
        update.message.reply_text("⏳ Нет сильных сигналов. Лучше подождать.")

dispatcher.add_handler(CommandHandler("post", cmd_post))

def loop():
    while True:
        for symbol in CONFIG['SYMBOLS']:
            analyze(symbol)
        time.sleep(CONFIG['CHECK_INTERVAL'])

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    t = threading.Thread(target=loop, daemon=True)
    updater.start_polling()
    t.start()
    updater.idle()
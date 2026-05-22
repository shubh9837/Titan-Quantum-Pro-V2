"""
Titan Quantum Pro V2 - Smart Agent & Chatbot
Handles natural language commands and order screenshot OCR.
"""
import re
import pandas as pd
from PIL import Image
import pytesseract

def parse_trade_text(text):
    """
    Parse natural language trade commands.
    Examples:
    - "Bought 50 RELIANCE at 2450"
    - "sell 20 tcs @ 3500"
    - "Added 100 INFY 1450.50"
    - "exit all tcs"
    Returns dict or None.
    """
    text = text.upper().strip()

    # BUY patterns
    buy_patterns = [
        r'(?:BOUGHT|BUY|ADDED|ADD)\s+(\d+)\s+([A-Z]+)\s+(?:AT|@)\s+(\d+(?:\.\d+)?)',
        r'(?:BOUGHT|BUY|ADDED|ADD)\s+(\d+)\s+([A-Z]+)\s+(\d+(?:\.\d+)?)',
    ]
    for pat in buy_patterns:
        match = re.search(pat, text)
        if match:
            return {
                'action': 'BUY',
                'qty': int(match.group(1)),
                'symbol': match.group(2),
                'price': float(match.group(3))
            }

    # SELL patterns
    sell_patterns = [
        r'(?:SOLD|SELL|EXIT)\s+(\d+)\s+([A-Z]+)\s+(?:AT|@)\s+(\d+(?:\.\d+)?)',
        r'(?:SOLD|SELL|EXIT)\s+(\d+)\s+([A-Z]+)\s+(\d+(?:\.\d+)?)',
        r'(?:SOLD|SELL|EXIT)\s+ALL\s+([A-Z]+)',
    ]
    for pat in sell_patterns:
        match = re.search(pat, text)
        if match:
            if 'ALL' in text:
                return {'action': 'SELL_ALL', 'qty': None, 'symbol': match.group(1), 'price': None}
            else:
                return {
                    'action': 'SELL',
                    'qty': int(match.group(1)),
                    'symbol': match.group(2),
                    'price': float(match.group(3))
                }

    # Portfolio query
    if any(k in text for k in ['PORTFOLIO', 'HOLDINGS', 'POSITIONS', 'PNL', 'PROFIT']):
        return {'action': 'QUERY_PORTFOLIO'}

    # Top picks query
    if any(k in text for k in ['TOP PICKS', 'BEST STOCKS', 'WHAT TO BUY', 'RECOMMEND']):
        return {'action': 'QUERY_TOP_PICKS'}

    # Market query
    if any(k in text for k in ['MARKET', 'NIFTY', 'SENSEX', 'TREND']):
        return {'action': 'QUERY_MARKET'}

    return None

def parse_order_image(image_file):
    """
    OCR on broker order screenshot.
    Supports Zerodha, Groww, Upstox style formats.
    """
    try:
        img = Image.open(image_file)
        text = pytesseract.image_to_string(img)
        text = text.upper()

        # Look for patterns like:
        # "BUY RELIANCE EQ 50 @ 2,450.00"
        # "NSE:RELIANCE | Qty: 50 | Avg: 2450"

        patterns = [
            r'(BUY|SELL)\s+([A-Z]+)\s+.*?(\d+(?:,\d+)*)\s*@\s*(\d+(?:,\d+)*(?:\.\d+)?)',
            r'(BUY|SELL)\s+([A-Z]+).*?QTY[:\s]+(\d+).*?(?:PRICE|AVG|@)[:\s]+(\d+(?:,\d+)*(?:\.\d+)?)',
            r'NSE[:\s]+([A-Z]+).*?(BUY|SELL).*?(\d+(?:,\d+)*)\s*@\s*(\d+(?:,\d+)*(?:\.\d+)?)',
        ]

        for pat in patterns:
            match = re.search(pat, text)
            if match:
                groups = match.groups()
                if len(groups) == 4:
                    # Determine which group is action and which is symbol
                    if groups[0] in ['BUY', 'SELL']:
                        action = groups[0]
                        symbol = groups[1]
                        qty_str = groups[2]
                        price_str = groups[3]
                    else:
                        symbol = groups[0]
                        action = groups[1]
                        qty_str = groups[2]
                        price_str = groups[3]

                    qty = int(qty_str.replace(',', ''))
                    price = float(price_str.replace(',', ''))

                    return {
                        'action': action,
                        'qty': qty,
                        'symbol': symbol,
                        'price': price,
                        'raw_text': text[:200]
                    }

        # Fallback: try to find any stock symbol and numbers
        symbols_found = re.findall(r'\b([A-Z]{2,10})\b', text)
        numbers = re.findall(r'\d+(?:,\d+)*(?:\.\d+)?', text)
        if symbols_found and len(numbers) >= 2:
            return {
                'action': 'UNKNOWN',
                'symbol': symbols_found[0],
                'qty': int(numbers[0].replace(',', '')),
                'price': float(numbers[1].replace(',', '')),
                'raw_text': text[:200],
                'needs_confirmation': True
            }

        return None
    except Exception as e:
        return {'error': str(e)}

def get_response(text, portfolio_df=None, market_df=None):
    """
    Generate agent response based on user input.
    """
    text_upper = text.upper().strip()
    parsed = parse_trade_text(text)

    if parsed:
        if parsed['action'] == 'BUY':
            return (f"🟢 Trade Detected: BUY {parsed['qty']} shares of {parsed['symbol']} @ ₹{parsed['price']}.\n"
                    f"Click 'Confirm & Add' below to add to your portfolio.")
        elif parsed['action'] == 'SELL':
            return (f"🔴 Trade Detected: SELL {parsed['qty']} shares of {parsed['symbol']} @ ₹{parsed['price']}.\n"
                    f"Go to Portfolio tab → Register Sale to execute.")
        elif parsed['action'] == 'SELL_ALL':
            return (f"🔴 Exit Detected: SELL ALL {parsed['symbol']}.\n"
                    f"Go to Portfolio tab → Register Sale with full quantity.")
        elif parsed['action'] == 'QUERY_PORTFOLIO':
            if portfolio_df is not None and not portfolio_df.empty:
                total = len(portfolio_df)
                return f"📊 You have {total} active holdings. Check the Portfolio Intelligence tab for exit signals and damage scores."
            return "📊 Your portfolio is empty. Go to Portfolio tab to add trades."
        elif parsed['action'] == 'QUERY_TOP_PICKS':
            if market_df is not None and not market_df.empty:
                top = market_df[market_df['PROBABILITY'] >= 65].sort_values('PROBABILITY', ascending=False).head(5)
                if not top.empty:
                    picks = ", ".join([f"{r['SYMBOL']} ({r['PROBABILITY']:.0f}%)" for _, r in top.iterrows()])
                    return f"🎯 Today's Top Picks: {picks}. Check the Today's Top Picks tab for details."
            return "🎯 No high-probability setups detected right now. Cash is a position."
        elif parsed['action'] == 'QUERY_MARKET':
            return "📈 Check the Market Weather banner at the top of the app for live NIFTY/SENSEX status and regime detection."

    # General conversational responses
    if any(k in text_upper for k in ['HELLO', 'HI', 'HEY']):
        return "👋 Hello! I'm Titan Agent. I can help you analyze stocks, check your portfolio, or parse trade screenshots. What would you like to do?"

    if any(k in text_upper for k in ['THANK', 'THANKS']):
        return "🙏 You're welcome! Happy trading."

    if any(k in text_upper for k in ['HELP', 'HOW']):
        return ("🤖 **What I can do:**\n"
                "1. Type trade commands: *'Bought 50 RELIANCE at 2450'*\n"
                "2. Ask about portfolio: *'How is my portfolio?'*\n"
                "3. Ask for picks: *'What are top picks?'*\n"
                "4. Upload order screenshots and I'll read them\n"
                "5. Ask market status: *'How is the market?'*")

    return "🤔 I didn't understand that. Try: *'Bought 50 RELIANCE at 2450'* or *'How is my portfolio?'* Type 'help' for more options."

import re
from PIL import Image, ImageEnhance, ImageOps
import pytesseract

def parse_trade_text(text):
    """
    Smarter local natural language parsing using expanded regex.
    """
    text = text.upper().strip()

    # Expanded vocabulary for actions
    buy_synonyms = r'(BOUGHT|BUY|ADDED|ADD|LONG|SCOOPED|GRABBED)'
    sell_synonyms = r'(SOLD|SELL|EXIT|SHORT|DUMPED|CLOSED)'
    
    # Matches formats like: "Bought 50 shares of RELIANCE at Rs 2450" or "Added 50 RELIANCE @ 2450.50"
    buy_patterns = [
        rf'{buy_synonyms}.*?(\d+).*?([A-Z]+).*?(?:AT|@|RS|₹|INR)\s*(\d+(?:\.\d+)?)',
        rf'{buy_synonyms}.*?(\d+).*?([A-Z]+).*?(\d+(?:\.\d+)?)'
    ]
    
    for pat in buy_patterns:
        match = re.search(pat, text)
        if match:
            return {'action': 'BUY', 'qty': int(match.group(2)), 'symbol': match.group(3), 'price': float(match.group(4))}

    sell_patterns = [
        rf'{sell_synonyms}.*?ALL.*?([A-Z]+)', # Catch "Exit all Reliance"
        rf'{sell_synonyms}.*?(\d+).*?([A-Z]+).*?(?:AT|@|RS|₹|INR)\s*(\d+(?:\.\d+)?)',
        rf'{sell_synonyms}.*?(\d+).*?([A-Z]+).*?(\d+(?:\.\d+)?)'
    ]
    
    for pat in sell_patterns:
        match = re.search(pat, text)
        if match:
            if 'ALL' in text:
                return {'action': 'SELL_ALL', 'qty': None, 'symbol': match.group(2), 'price': None}
            else:
                return {'action': 'SELL', 'qty': int(match.group(2)), 'symbol': match.group(3), 'price': float(match.group(4))}

    # Standard queries
    if any(k in text for k in ['PORTFOLIO', 'HOLDINGS', 'POSITIONS']): return {'action': 'QUERY_PORTFOLIO'}
    if any(k in text for k in ['TOP PICKS', 'BEST STOCKS', 'RECOMMEND']): return {'action': 'QUERY_TOP_PICKS'}
    if any(k in text for k in ['MARKET', 'NIFTY', 'SENSEX', 'TREND']): return {'action': 'QUERY_MARKET'}

    return None

def parse_order_image(image_file):
    """
    Enhanced OCR that pre-processes the image for better accuracy.
    """
    try:
        # 1. Pre-process the image to help Tesseract read it
        img = Image.open(image_file)
        img = ImageOps.grayscale(img) # Convert to black and white
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.5)   # Crank up contrast to make text pop
        
        # 2. Extract text
        text = pytesseract.image_to_string(img).upper()

        # 3. Look for broker-specific patterns (Zerodha, Groww, etc.)
        patterns = [
            r'(BUY|SELL)\s+([A-Z]+)\s+.*?(\d+(?:,\d+)*)\s*@\s*(\d+(?:,\d+)*(?:\.\d+)?)',
            r'(BUY|SELL)\s+([A-Z]+).*?QTY[:\s]+(\d+).*?(?:PRICE|AVG|@)[:\s]+(\d+(?:,\d+)*(?:\.\d+)?)',
            r'NSE[:\s]+([A-Z]+).*?(BUY|SELL).*?(\d+(?:,\d+)*)\s*@\s*(\d+(?:,\d+)*(?:\.\d+)?)',
        ]

        for pat in patterns:
            match = re.search(pat, text)
            if match:
                groups = match.groups()
                # Determine action vs symbol based on what regex caught
                if groups[0] in ['BUY', 'SELL']:
                    action, symbol, qty_str, price_str = groups[0], groups[1], groups[2], groups[3]
                else:
                    symbol, action, qty_str, price_str = groups[0], groups[1], groups[2], groups[3]

                return {
                    'action': action,
                    'qty': int(qty_str.replace(',', '')),
                    'symbol': symbol,
                    'price': float(price_str.replace(',', '')),
                    'raw_text': text[:100]
                }
        return {'error': "Could not find a recognizable trade pattern in the image."}
    except Exception as e:
        return {'error': str(e)}

def get_response(parsed, portfolio_df=None, market_df=None):
    if parsed and 'error' not in parsed:
        if parsed['action'] == 'BUY': return f"🟢 Detected: BUY {parsed['qty']} {parsed['symbol']} @ ₹{parsed['price']}. Click confirm below."
        elif parsed['action'] == 'SELL': return f"🔴 Detected: SELL {parsed['qty']} {parsed['symbol']} @ ₹{parsed['price']}. Go to Portfolio tab to execute."
        elif parsed['action'] == 'SELL_ALL': return f"🔴 Exit Detected: SELL ALL {parsed['symbol']}. Go to Portfolio tab."
        elif parsed['action'] == 'QUERY_PORTFOLIO': return "📊 Check the Portfolio Intelligence tab for your active holdings."
        elif parsed['action'] == 'QUERY_TOP_PICKS': return "🎯 Check the Today's Top Picks tab for details."
        elif parsed['action'] == 'QUERY_MARKET': return "📈 Check the Market Weather banner at the top of the app."
    
    return "🤔 I couldn't quite catch that. Try standard phrasing like 'Bought 50 RELIANCE at 2450' or use the manual entry tab."

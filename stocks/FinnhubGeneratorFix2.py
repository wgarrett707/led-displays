#!/usr/bin/python3
import json
KEYS = json.load(open('/home/pi/led-scripts/apikeys.json'))
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime, date, timedelta
import time
import requests
import finnhub
import ledpackage as lp
import os

FULL_PATH = '/home/pi/led-scripts/stocks'

# Missing BBBY, BIG, CAJ, DNKN, ?
stockSymbols = ["AAL", "AAPL", "ABBV", "ABT", "ADBE", "ADI", "ADP", "ADSK", "ALGN", "AMC", "AMD",
                "AMGN", "AMZN", "ATVI", "AVGO", "AXP", "BA", "BABA", "BAC", "BB", "BBY", "BIDU", "BP", "BRK-B",
                "C", "CAT", "CCL", "COF", "COST", "CSCO", "CVS", "CVX", "DELL", "DG", "DIS",
                "DLTR", "DOW", "EBAY", "ETSY", "F", "FDX", "FITB", "GE", "GEN", "GIS",
                "GM", "GME", "GOOG", "GS", "HAS", "HD", "HPQ", "HSBC", "HSY", "IBM",
                "INTC", "INTU", "JNJ", "JPM", "K", "KHC", "KO", "KR", "LOGI",
                "LOW", "M", "MA", "MAT", "MCD", "META", "MMM", "MRK", "MSFT", "MSI", "NFLX", "NIO",
                "NKE", "NOK", "NVDA", "ORCL", "PEP", "PFE", "PG", "PINS", "PNC", "PYPL",
                "SBUX", "SHEL", "SONY", "SQ", "T", "TGT", "TRV", "TSLA", "TXN", "UAL", "UBER",
                "UNH", "UPS", "V", "VZ", "WBA", "WDC", "WFC", "WHR", "WMT", "XOM", "YUM"]

configuration = finnhub.Configuration(
    api_key={
        'token': KEYS['finnhub']
    }
)

finnhub_client = finnhub.DefaultApi(finnhub.ApiClient(configuration))
index = 0
closeCycled = False

def resetReady():
    # This script simply resets the 'Ready.txt' file so no errors occur later on
    file = open(FULL_PATH + '/Ready.txt', 'w')
    file.writelines('0')
    file.close()
    print('Ready.txt has been reset.')

def checkReady():
    # This function checks to see when the other script is ready to continue.
    # (A loop rather than recursion, which hit Python's recursion limit on long waits.)
    while True:
        file = open(FULL_PATH + '/Ready.txt', 'r')
        content = file.read()
        file.close()
        if content == '1':
            print('Photo generator recognizes scroller\'s ready status.')
            resetReady()
            return
        time.sleep(0.5)

def nthWeekday(year, month, weekday, n):
    # n-th given weekday (Mon=0) of a month; n=-1 means the last one
    if n > 0:
        first = date(year, month, 1)
        return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    last = date(year, month + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)

def observed(day):
    # Holidays on a Saturday are observed Friday, on a Sunday the following Monday
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day

def easter(year):
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    return date(year, month, (h + l - 7 * m + 114) % 31 + 1)

def nyseHolidays(year):
    # Regular NYSE full-day closures (replaces pandas_market_calendars, which took ~13 s to import)
    holidays = {nthWeekday(year, 1, 0, 3),               # Martin Luther King Jr. Day
                nthWeekday(year, 2, 0, 3),               # Washington's Birthday
                easter(year) - timedelta(days=2),        # Good Friday
                nthWeekday(year, 5, 0, -1),              # Memorial Day
                observed(date(year, 6, 19)),             # Juneteenth
                observed(date(year, 7, 4)),              # Independence Day
                nthWeekday(year, 9, 0, 1),               # Labor Day
                nthWeekday(year, 11, 3, 4),              # Thanksgiving
                observed(date(year, 12, 25))}            # Christmas
    # New Year's Day on a Saturday is not observed on the Friday before
    newYear = date(year, 1, 1)
    if newYear.weekday() != 5:
        holidays.add(observed(newYear))
    return holidays

def isTradingDay(day):
    return day.weekday() < 5 and day not in nyseHolidays(day.year)

def fetchQuote(symbol):
    # Returns the quote, or None if the request failed (the old image is kept)
    try:
        return finnhub_client.quote(symbol, _request_timeout=10)
    except finnhub.ApiException as e:
        print('Finnhub error for ' + symbol + ': ' + str(e.status) + ' ' + str(e.reason))
        if e.status == 429:
            print('Rate limited, waiting 60 seconds.')
            time.sleep(60)
    except Exception as e:
        print('Request failed for ' + symbol + ': ' + repr(e))
        time.sleep(5)
    return None

def isMarketOpen():
    # In this function, the first value returned specifies if the market is open or not.
    # The second value returned specifies if the status of the market being open or
    # closed is going to change soon (ex. at 2 PM or later, the market will be within
    # an hour of closing).
    currentDT = datetime.now()
    # Testing command: currentDT = datetime(2020, 7, 14, 7, 45)
    currentDate = currentDT.strftime('%Y-%m-%d')
    print(currentDate)
    # Checks if it is a valid trading day (not a weekend or holiday)
    if isTradingDay(currentDT.date()):
        currentHour = int(currentDT.strftime('%H'))
        print(currentHour)
        # Checks if the hour is between 8 AM and 3 PM (approximate market hours in CST)
        if 7 <= currentHour <= 15:
            if currentHour == 14:
                print('Open, but the market is closing soon.')
                return True, True
            if currentHour == 7 or currentHour == 8: 
                currentMin = int(currentDT.strftime('%M'))
                # Checks to see if it is before or after 8:30 AM, which is the exact opening time
                if currentHour == 8 and currentMin < 30:
                    print('Closed. It is not market opening time just yet.')
                    return False, True
                # Checks to see if it is before or after 7:30 AM so the program knows if the market
                # is opening soon.
                if currentHour == 7 and currentMin >= 30:
                    print('Closed. It is not market opening time just yet.')
                    return False, True 
            print('Open')
            return True, False
        else:
            print('Closed. It is before or after market hours.')
            return False, False
    else:
        print('Closed. Market is not open today.')
        return False, False


# Reset Ready.txt before recording the PID: the scroller waits on the PID and then marks
# itself ready, so resetting after that could wipe out its ready status.
resetReady()
lp.localPID('stocks', str(os.getpid()))
# The first pass starts right away so fresh prices replace last session's images.
firstPass = True

while True:
    while True:
        # See the note I made at the top of the mentioned function
        marketOpen = isMarketOpen()
        # If the market is open, reset the closeCycled variable
        if marketOpen[0]:
            closeCycled = False
        else:
            # If the market is closed and already went through a close cycle, then wait for
            # a certain amount of time. If it still needs to do a close cycle, it will skip
            # this conditional statement and go through a single cycle
            if closeCycled:
                # If the market is going to open soon, then only wait 30 seconds before checking again
                if marketOpen[1]:
                    print('Sleeping for 30 seconds...')
                    time.sleep(30)
                    break
                # If the market is not going to open soon, then wait 30 *MINUTES*
                print('Sleeping for 30 minutes...')
                time.sleep(1800)
                break
        print(marketOpen)
        cycles = 0
        if not firstPass:
            checkReady()
        firstPass = False

        # The following code is the loop that creates images for each stock
        while True:
            if index <= len(stockSymbols) - 1:
                selectedSymbol = stockSymbols[index]
                stockQuote = fetchQuote(selectedSymbol)
                if stockQuote is None:
                    index += 1
                    continue
                print(stockQuote)
                symbolPrice = str(format(stockQuote.c, '.2f'))
                try:
                    symbolChange = str(format(round(float(((stockQuote.c - stockQuote.pc)/stockQuote.pc) * 100), 2), '.2f') + '%')
                except:
                    print('NO CHANGE!! 0%!! Might be a goofy stock symbol!!')
                    print('-------------------------------------------------')
                    symbolChange = '0.00%'
                print(selectedSymbol, symbolPrice, symbolChange)
                if symbolChange.find("-") == -1:
                    textRed = 0
                    textGreen = 255
                    arrowFile = FULL_PATH + "/uparrow.png"
                else:
                    textRed = 255
                    textGreen = 0
                    arrowFile = FULL_PATH + "/downarrow.png"
            
                img = Image.new('RGBA', (1000, 35), color = (0, 0, 0, 0))
                # Move textFont, arrowImage variable declarations outside of 'while True' loop
                textFont = ImageFont.truetype(FULL_PATH + '/calibrib.ttf', size=22)
            
                arrowImage = Image.open(arrowFile)
                print("File Path: " + str(os.path.dirname(__file__)))
                logoImagePath = FULL_PATH + "/logos/" + selectedSymbol + ".png"
                logoImage = Image.open(logoImagePath)
            
                img.paste(logoImage, (1, 3))
                logoWidth, logoHeight = logoImage.size
                print("logoWidth:", logoWidth)
            
                d = ImageDraw.Draw(img)
                d.fontmode = "1"
                d.text((logoWidth + 3, 17), symbolPrice, font=textFont, fill=(textRed, textGreen, 0))
                priceWidth, priceHeight = d.textsize(symbolPrice, font=textFont)
            
                img.paste(arrowImage, (logoWidth + priceWidth + 5, 21))
                d.text((logoWidth + priceWidth + 18, 17), symbolChange, font=textFont, fill=(textRed, textGreen, 0))
                changeWidth, changeHeight = d.textsize(symbolChange, font=textFont)

                d.text((logoWidth + 3, 1), selectedSymbol, font=textFont, fill=(255, 255, 255))
            
                img = img.crop((0, 3, logoWidth + priceWidth + changeWidth + 19, 35))
                fileName = FULL_PATH + "/displays/" + selectedSymbol + ".png"
                # Write to a temp file and rename, so the scroller never reads a half-written PNG
                img.save(fileName + '.tmp', format='PNG')
                os.replace(fileName + '.tmp', fileName)
                imgWidth, imgHeight = img.size
                waitTime = imgWidth * 0.005
                print(str(imgWidth) + " pixels wide image. Waiting " + str(waitTime) + " seconds.")
                index += 1
                time.sleep(waitTime)
            else:
                index = 0
                cycles += 1
                checkReady()
                # If the market is going to close soon, only cycle through 2 times before checking again
                if marketOpen[1]:
                    if cycles >= 2:
                        break
                # No matter what, if there have been over 7 consecutive cycles, check if the market is open/closed again
                if cycles >= 7:
                   break
                # If the market is closed and it just did a cycle, that means the close cycle has been completed
                if marketOpen[0] == False:
                    print('Completed close cycle.')
                    closeCycled = True
                    break
                    
                    

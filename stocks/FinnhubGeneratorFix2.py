#!/usr/bin/python3
import json
KEYS = json.load(open('/home/pi/led-scripts/apikeys.json'))
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime, time
import time
import requests
import finnhub
import pandas as pd
import pandas_market_calendars as mcal
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
nyse = mcal.get_calendar('NYSE')
index = 0
closeCycled = False
lp.localPID('stocks', str(os.getpid()))

def resetReady():
    # This script simply resets the 'Ready.txt' file so no errors occur later on
    file = open(FULL_PATH + '/Ready.txt', 'w')
    file.writelines('0')
    file.close()
    print('Ready.txt has been reset.')

def checkReady():
    # This function checks to see when the other script is ready to continue.
    file = open(FULL_PATH + '/Ready.txt', 'r')
    content = file.read()
    file.close()
    if content == '1':
        print('Photo generator recognizes scroller\'s ready status.')
        resetReady()
    else:
        time.sleep(0.5)
        checkReady()
        

def isMarketOpen():
    global nyse
    # In this function, the first value returned specifies if the market is open or not.
    # The second value returned specifies if the status of the market being open or
    # closed is going to change soon (ex. at 2 PM or later, the market will be within
    # an hour of closing).
    currentDT = datetime.now()
    # Testing command: currentDT = datetime(2020, 7, 14, 7, 45)
    currentDate = currentDT.strftime('%Y-%m-%d')
    print(currentDate)
    # Checks if it is a valid trading day (not a weekend or holiday)
    validDays = nyse.valid_days(start_date=currentDate, end_date=currentDate)
    print(validDays)
    if currentDate in str(validDays):
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

   
while True:
    while True:
        # Reset the Ready.txt file first, otherwise it might clear the other script's ready status
        resetReady()
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
        checkReady()

        # The following code is the loop that creates images for each stock
        while True:
            if index <= len(stockSymbols) - 1:
                selectedSymbol = stockSymbols[index]
                stockQuote = finnhub_client.quote(selectedSymbol)
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
                img.save(fileName)
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
                    
                    

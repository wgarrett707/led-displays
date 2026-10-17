#!/usr/bin/python3
import json
KEYS = json.load(open('/home/pi/led-scripts/apikeys.json'))
import time
import requests
from PIL import Image, ImageDraw, ImageFont
import yfinance as yf
import os

stockSymbols = ["AAL", "AAPL", "ABT", "ADBE", "AMD", "AMZN", "AXP", "BA",
                "BBBY", "BBY", "BIG", "BP", "BRK-A", "CAT", "COF",
                "COST", "CSCO", "CVS", "CVX", "DELL", "DG", "DIS", "DLTR",
                "DNKN", "DOW", "EBAY", "F", "FB", "FDX", "FITB", "GE", "GIS",
                "GM", "GOOG", "GS", "HAS", "HD", "HPQ", "HSBC", "HSY", "IBM",
                "KO", "MMM", "PEP", "PFE", "PG", "PNC", "RDS-A", "SBUX",
                "SNE", "TGT", "TRV", "TXN", "UAL", "UNH", "USD", "V",
                "VZ", "WBA", "WDC", "WFC", "WMT"]

finntoken = KEYS['finnhub_old']

index = 0

while True:
    if index <= len(stockSymbols) - 1:
        selectedSymbol = stockSymbols[index]
        request = requests.get('https://finnhub.io/api/v1/quote?symbol=' + selectedSymbol + '&token=' + finntoken)
        jsonFile = request.json()
        symbolPrice = str(jsonFile['c'])
        symbolChange = str(round(float(jsonFile['c'] - jsonFile['pc']), 2))
        print(selectedSymbol, symbolPrice, symbolChange)
        if symbolChange.find("-") == -1:
            textRed = 0
            textGreen = 255
            arrowFile = "uparrow.png"
        else:
            textRed = 255
            textGreen = 0
            arrowFile = "downarrow.png"
        
        img = Image.new('RGBA', (1000, 35), color = (0, 0, 0, 0))
        textFont = ImageFont.truetype('calibrib.ttf', size=22)
        
        arrowImage = Image.open(arrowFile)
        print("File Path: " + str(os.path.dirname(__file__)))
        logoImagePath = "./logos/" + selectedSymbol + ".png"
        logoImage = Image.open(logoImagePath)
        
        img.paste(logoImage, (1, 4))
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
        fileName = "./displays/" + selectedSymbol + ".png"
        img.save(fileName)
        index += 1
        time.sleep(0.5)
    else:
        index = 0

#!/usr/bin/python3
import time
from PIL import Image, ImageDraw, ImageFont
import yfinance as yf
import os

stockSymbols = ["AAL", "AAPL", "ABT", "ADBE", "AMD", "AMZN", "AXP", "BA",
                "BBBY", "BBY", "BIG", "BP", "BRK-A", "CAT", "CBS", "COF",
                "COST", "CSCO", "CVS", "CVX", "DELL", "DG", "DIS", "DLTR",
                "DNKN", "DOW", "EBAY", "F", "FB", "FDX", "FITB", "GE", "GIS",
                "GM", "GOOG", "GS", "HAS", "HD", "HPQ", "HSBC", "HSY", "IBM",
                "KO", "MCD", "MMM", "NSRGY", "SVNDY", "XON"]

index = 0

while True:
    if index <= len(stockSymbols) - 1:
        selectedSymbol = stockSymbols[index]
        yfSymbol = yf.Ticker(selectedSymbol)
        symbolPrice = format(round(yfSymbol.info['regularMarketPrice'], 2), ".2f")
        symbolChange = format(round(yfSymbol.info['regularMarketChange'], 2), ".2f")
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
        logoImagePath = str(os.path.dirname(__file__)) + "/logos/" + selectedSymbol + ".png"
        logoImage = Image.open(logoImagePath)
        
        img.paste(logoImage, (1, 4))
        logoWidth, logoHeight = logoImage.size
        print("logoWidth:", logoWidth)
        
        d = ImageDraw.Draw(img)
        d.text((logoWidth + 3, 17), symbolPrice, font=textFont, fill=(textRed, textGreen, 0))
        priceWidth, priceHeight = d.textsize(symbolPrice, font=textFont)
        
        img.paste(arrowImage, (logoWidth + priceWidth + 5, 21))
        d.text((logoWidth + priceWidth + 18, 17), symbolChange, font=textFont, fill=(textRed, textGreen, 0))
        changeWidth, changeHeight = d.textsize(symbolChange, font=textFont)

        d.text((logoWidth + 3, 1), selectedSymbol, font=textFont, fill=(255, 255, 255))
        
        img = img.crop((0, 3, logoWidth + priceWidth + changeWidth + 19, 35))
        fileName = selectedSymbol + ".png"
        img.save(fileName)
        index += 1
    else:
        index = 0

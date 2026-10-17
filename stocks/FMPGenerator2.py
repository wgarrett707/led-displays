#!/usr/bin/python3
import time
import requests
from PIL import Image, ImageDraw, ImageFont
import yfinance as yf
import os

stockSymbols = ["AAL", "AAPL", "ABT", "ADBE", "AMD", "AMZN", "ATVI", "AXP", "BA",
                "BAC", "BB", "BBBY", "BBY", "BIG", "BP", "BRK-A", "C", "CAJ", "CAT"]

#Tells the other script that it isn't ready to start yet 
file = open('Ready.txt', 'w')
file.write('0')
file.close()
#Sets the stock number to 0 to prevent errors
file = open('StockNumber.txt', 'w')
file.write('0')
file.close()
print('Picture generator has marked that it is still working (not ready).')

index = 0
first = True

while True:
    while True:
        if first == True:
            stockNum = 0
            rangeIter = 5
            
        else:
            while True:
                file = open('StockNumber.txt', 'r')
                fileContents = file.read()
                if fileContents != str(stockNum):
                    print('Picture generator has received the stocks to find from logoviewer.')
                    stockNum = int(fileContents)
                    file.close()
                    break
                else:
                    #print(str(stockNum) + " is the same as " + fileContents)
                    file.close()
                    time.sleep(0.2)

            if stockNum + 10 > len(stockSymbols) - 1:
                #Check this, idk if I'm doing the right math
                rangeIter = len(stockSymbols) - stockNum - 1
                
            else:
                rangeIter = 5
            
        stocksToCheck = ''
        for x in range(rangeIter):
            stocksToCheck += stockSymbols[stockNum + x]
            if x != rangeIter - 1:
                stocksToCheck += ','
                
        print('Stocks to Check:', stocksToCheck)
        request = requests.get('https://financialmodelingprep.com/api/v3/quote/' + stocksToCheck)
        try:
            jsonFile = request.json()
        except:
            print(selectedSymbol + " failed.")
            index += 1
            break
        for jsonStock in jsonFile:
            selectedSymbol = jsonStock['symbol']
            symbolPrice = str(format(round(jsonStock['price'], 2), '.2f'))
            symbolChange = str(format(round(jsonStock['change'], 2), '.2f'))
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
            logoImagePath = "./logos/" + selectedSymbol + ".png"
            logoImage = Image.open(logoImagePath)
        
            img.paste(logoImage, (1, 3))
            logoWidth, logoHeight = logoImage.size
        
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
            print("Image saved.")
            time.sleep(1)
            
        if first == True:
            print("Inside if statement.")
            file = open('Ready.txt', 'w')
            file.write('1')
            file.close()
            print('Picture generator has marked that it is ready.')
            first = False

#!/usr/bin/python3
import time
from rgbmatrix import RGBMatrix, RGBMatrixOptions
from samplebase import SampleBase
from PIL import Image, ImageDraw, ImageFont, ImageChops
import yfinance as yf
import os
import asyncio

options = RGBMatrixOptions()
options.rows = 32
options.chain_length = 1
options.parallel = 1
options.hardware_mapping = 'regular'
options.brightness = 30
options.multiplexing = 6
options.led_rgb_sequence = "BGR"
options.pwm_lsb_nanoseconds = 350

matrix = RGBMatrix(options = options)

stockSymbols = ["AAL", "AAPL", "ABT", "ADBE", "AMD", "AMZN", "AXP", "BA",
                "BBBY", "BBY", "BIG", "BP", "BRK-A", "CAT", "CBS", "COF",
                "COST", "CSCO", "CVS", "CVX", "DELL", "DG", "DIS", "DLTR",
                "DNKN", "DOW", "EBAY", "F", "FB", "FDX", "FITB", "GE", "GIS",
                "GM", "GOOG", "GS", "HAS", "HD", "HPQ", "HSBC", "HSY", "IBM",
                "KO", "MMM", "NSRGY", "SVNDY", "UNH", "USD", "UTX", "V",
                "VZ", "WBA", "WDC", "WFC", "WMT", "XON"]

async def logoviewer():
    index = 0
    LEDworkspace = options.chain_length * options.rows
    print(LEDworkspace)
    print("Starting LEDs in 10 seconds...")

    time.sleep(10)
        
    #Making a canvas big enough to fit what the matrix panels will show along with space outside of the matrix panels where images will be prepared
    canvas = Image.new('RGB', (500, 32), (0, 0, 0))
    matrixCanvas = matrix.CreateFrameCanvas()

    while True:
        if index != 0:
            canvas = ImageChops.offset(canvas, xoffset=-img_width, yoffset=0)
        print("Now presenting: " + stockSymbols[index])    
        imageElement = Image.open("./displays/" + stockSymbols[index] + ".png").convert('RGB')
        img_width, img_height = imageElement.size
        canvas.paste(imageElement, (250, 0))
        xpos = 0
        while True:
            if (xpos < -img_width):
                break

            matrixCanvas.SetImage(canvas, xpos - 250 + LEDworkspace)

            matrixCanvas = matrix.SwapOnVSync(matrixCanvas)
            time.sleep(0.05)

            xpos = xpos - 1
        index += 1

async def pictureMaker():
    index = 0
    while True:
        if index <= len(stockSymbols) - 1:
            selectedSymbol = stockSymbols[index]
            yfSymbol = yf.Ticker(selectedSymbol)
            symbolPriceUnrounded = yfSymbol.info['regularMarketPrice']
            symbolPrice = format(round(symbolPriceUnrounded, 2), ".2f")
            symbolChange = format(round(symbolPriceUnrounded - yfSymbol.info["previousClose"], 2), ".2f")
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
            if index == 3:
                await logoviewer()
        else:
            index = 0

asyncio.run(pictureMaker())

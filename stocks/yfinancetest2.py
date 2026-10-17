#!/usr/bin/env python
from rgbmatrix import RGBMatrix, RGBMatrixOptions
from PIL import Image, ImageDraw, ImageFont
import yfinance as yf

while True:
    symbol = yf.Ticker(input("What ticker would you like to view? "))
    price = str(symbol.info['regularMarketPrice'])
    change = str(round(symbol.info['regularMarketChange'], 2))
    text = price + " " + change

    font = [ImageFont.truetype(font='arial.ttf', size=20), 2]
    width, ignore = font[0].getsize(text)
    image = Image.new("RGB", (width + 40, 20), "black")
    draw = ImageDraw.Draw(image)
    draw.text((0, font[1]), text, "white", font=font[0])
    imgname = "C:/Users/memek/Desktop/Programming Saves/Python/LED Displays/Stocks"+"/"+str("20")+".png"
    image.save(imgname)

    image.resize((matrix.width, matrix.height), Image.ANTIALIAS)
    double_buffer = matrix.CreateFrameCanvas()
    img_width, img_height = image.size

    # let's scroll
    xpos = matrix.width
        
    while True:
        if (xpos <= -img_width):
            break

        double_buffer.SetImage(image, xpos)
                
        double_buffer = matrix.SwapOnVSync(double_buffer)
        time.sleep(0.03)

        xpos = xpos - 1
    
    

 

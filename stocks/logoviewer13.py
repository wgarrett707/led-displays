#!/usr/bin/env python3.7
import time
from rgbmatrix import RGBMatrix, RGBMatrixOptions
from samplebase import SampleBase
from PIL import Image, ImageChops

options = RGBMatrixOptions()
options.rows = 32
options.chain_length = 3
options.parallel = 1
options.hardware_mapping = 'regular'
options.brightness = 30
options.multiplexing = 6
options.led_rgb_sequence = "BGR"
options.pwm_lsb_nanoseconds = 350

matrix = RGBMatrix(options = options)

stockSymbols = ["AAL", "AAPL", "ABT", "ADBE", "AMD", "AMZN", "ATVI", "AXP", "BA",
                "BAC", "BB", "BBBY", "BBY", "BIG", "BP", "BRK-A", "C", "CAJ", "CAT"]

index = 0
first = True

stockLen = len(stockSymbols)
print(stockLen)
LEDworkspace = options.chain_length * options.rows
        
#Making a canvas big enough to fit what the matrix panels will show along with space outside of the matrix panels where images will be prepared
canvas = Image.new('RGB', (600, 32), (0, 0, 0))
matrixCanvas = matrix.CreateFrameCanvas()
time.sleep(3)

while True:
    print('Logoviewer is checking...')
    file = open('Ready.txt', 'r')
    if file.read() == '1':
        print('Logoviewer has recognized that the picture generator is ready.')
        file.close()
        fileWrite = open('Ready.txt', 'w')
        fileWrite.write('0')
        fileWrite.close()
        print('Logoviewer has reset the ready status.')
        break
    else:
        file.close()
        time.sleep(0.2)

while True:
    #Tells the other script what stocks to check over
    if (index + 1) % 5 == 0 and index + 5 <= stockLen - 1 or index == 0:
        #Might get overwritten each time the other script closes it
        print('Logoviewer is sending stocks for the picture generator to check.')
        f = open('StockNumber.txt', 'w')
        f.write(str(index))
        f.close()

    t0 = time.time()
    #The first stock does not need to offset the canvas
    if first == False:
        canvas = ImageChops.offset(canvas, xoffset=-img_width, yoffset=0)
    else:
        first = False
        
    try:
        imageElement = Image.open("./displays/" + stockSymbols[index] + ".png").convert('RGB')
    except:
        print("Image file not there, waiting.")
        time.sleep(0.1)
        imageElement = Image.open("./displays/" + stockSymbols[index] + ".png").convert('RGB')
        
    img_width, img_height = imageElement.size
    canvas.paste(imageElement, (250, 0))
    xpos = -1
    t1 = time.time()
    print(t1 - t0)
    while True:
        if (xpos < -img_width):
            break

        matrixCanvas.SetImage(canvas, xpos - 250 + LEDworkspace)

        matrixCanvas = matrix.SwapOnVSync(matrixCanvas)
        time.sleep(0.02)

        xpos = xpos - 1
    index += 1

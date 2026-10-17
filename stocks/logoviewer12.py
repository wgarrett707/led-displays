#!/usr/bin/env python3.7
import time
import os
import ledpackage as lp
from rgbmatrix import RGBMatrix, RGBMatrixOptions
from samplebase import SampleBase
from PIL import Image, ImageChops

options = RGBMatrixOptions()
options.rows = 32
options.chain_length = 8
options.parallel = 1
options.hardware_mapping = 'regular'
options.brightness = 30
options.multiplexing = 6
options.led_rgb_sequence = "BGR"
options.pwm_lsb_nanoseconds = 350

FULL_PATH = "/home/pi/led-scripts/stocks"

matrix = RGBMatrix(options = options)

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

def markReady():
    file = open(FULL_PATH + "/Ready.txt", "w")
    file.writelines("1")
    file.close()

index = 0
matrixCanvas = matrix.CreateFrameCanvas()
LEDworkspace = options.chain_length * options.rows
print(LEDworkspace)

loading = Image.open(FULL_PATH + "/loading.png").convert('RGB')
matrixCanvas.SetImage(loading)
matrixCanvas = matrix.SwapOnVSync(matrixCanvas)

print("Starting LEDs in about 20 seconds...")

time.sleep(10)

lp.recordPID('stocks', str(os.getpid()))
markReady()
print('Scroller is ready to begin in 10 seconds.')

time.sleep(10)
        
#Making a canvas big enough to fit what the matrix panels will show along with space outside of the matrix panels where images will be prepared
canvas = Image.new('RGB', (600, 32), (0, 0, 0))

while True:
    # The canvas does not need to be shifted if it is the first display being shown
    if index != 0:
        canvas = ImageChops.offset(canvas, xoffset=-img_width, yoffset=0)
    # This resets the 'index' variable back to 0 after showing all of the stocks in the list
    if index >= len(stockSymbols):
        index = 0
    # This calls the markReady function on the fifth-to-last logo so that the photo generator script knows when to start generating photos again
    if index == len(stockSymbols) - 5:
        markReady()
        print('Scroller is at the fifth-to-last logo and has marked that it is ready.')
    try:
        imageElement = Image.open(FULL_PATH + "/displays/" + stockSymbols[index] + ".png").convert('RGB')
    except:
        print("Image file not there, waiting.")
        time.sleep(0.1)
        imageElement = Image.open(FULL_PATH + "/displays/" + stockSymbols[index] + ".png").convert('RGB')
    img_width, img_height = imageElement.size
    canvas.paste(imageElement, (250, 0))
    xpos = -1
    while True:
        if (xpos < -img_width):
            break

        matrixCanvas.SetImage(canvas, xpos - 250 + LEDworkspace)

        matrixCanvas = matrix.SwapOnVSync(matrixCanvas)
        time.sleep(0.01)

        xpos = xpos - 1
    index += 1

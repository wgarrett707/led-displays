#!/usr/bin/env python3.7
import time
import os
import gc
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

# Target seconds per 1-pixel scroll step (about 62 px/s). Lower is faster.
# The actual step is a whole number of panel refreshes, so every step takes exactly the same time.
FRAME_TIME = 0.016

def measureRefresh(image, frames=60):
    # Times SwapOnVSync, which returns once per panel refresh, to find the refresh period
    global matrixCanvas
    start = time.monotonic()
    for _ in range(frames):
        matrixCanvas.SetImage(image)
        matrixCanvas = matrix.SwapOnVSync(matrixCanvas)
    return (time.monotonic() - start) / frames

def loadDisplay(symbol):
    # Returns the symbol's image, or None if it is missing or unreadable after a few tries
    for attempt in range(3):
        try:
            return Image.open(FULL_PATH + "/displays/" + symbol + ".png").convert('RGB')
        except Exception as e:
            print("Couldn't load " + symbol + " (" + repr(e) + "), retrying.")
            time.sleep(0.1)
    return None

refreshPeriod = measureRefresh(loading)
swapsPerStep = max(1, round(FRAME_TIME / refreshPeriod))
print('Panel refresh %.2f ms, %d refreshes per step (%.1f px/s)'
      % (refreshPeriod * 1000, swapsPerStep, 1 / (refreshPeriod * swapsPerStep)))

# The loading screen stays up until the generator has recorded its PID (recordPID waits for it).
lp.recordPID('stocks', str(os.getpid()))
markReady()
print('Scroller is ready.')

#Making a canvas big enough to fit what the matrix panels will show along with space outside of the matrix panels where images will be prepared
canvas = Image.new('RGB', (600, 32), (0, 0, 0))
img_width = 0

# Garbage collection pauses cause visible hitches, so it only runs between logos.
gc.disable()

while True:
    # Shift out the display that just finished scrolling (nothing to shift before the first one)
    if img_width:
        canvas = ImageChops.offset(canvas, xoffset=-img_width, yoffset=0)
        img_width = 0
    # This resets the 'index' variable back to 0 after showing all of the stocks in the list
    if index >= len(stockSymbols):
        index = 0
    # This calls the markReady function on the fifth-to-last logo so that the photo generator script knows when to start generating photos again
    if index == len(stockSymbols) - 5:
        markReady()
        print('Scroller is at the fifth-to-last logo and has marked that it is ready.')
    imageElement = loadDisplay(stockSymbols[index])
    if imageElement is None:
        index += 1
        continue
    gc.collect()
    img_width, img_height = imageElement.size
    canvas.paste(imageElement, (250, 0))
    xpos = -1
    while True:
        if (xpos < -img_width):
            break

        # Hold each position for the same number of refreshes. SwapOnVSync hands back the
        # other buffer, which still has the previous position, so it is redrawn every swap.
        for _ in range(swapsPerStep):
            matrixCanvas.SetImage(canvas, xpos - 250 + LEDworkspace)
            matrixCanvas = matrix.SwapOnVSync(matrixCanvas)

        xpos = xpos - 1
    index += 1

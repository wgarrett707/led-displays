#!/usr/bin/env python3.7
import time
import os
import gc
import io
from concurrent.futures import ThreadPoolExecutor
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

def measureRefresh(image, frames=120):
    # Times SwapOnVSync, which returns once per panel refresh, to find the refresh period
    global matrixCanvas
    matrixCanvas.SetImage(image)
    matrixCanvas = matrix.SwapOnVSync(matrixCanvas)
    start = time.monotonic()
    for _ in range(frames):
        matrixCanvas.SetImage(image)
        matrixCanvas = matrix.SwapOnVSync(matrixCanvas)
    return (time.monotonic() - start) / frames

def showStep(image, offset):
    # SwapOnVSync swaps at the end of the refresh in progress, so calling it straight after
    # the previous swap would show each position for only one refresh. Instead, draw into the
    # free buffer now (SetImage takes 2-6 ms, occasionally 13), then hand it over in the middle
    # of this step's last refresh. It then appears exactly swapsPerStep refreshes after the
    # previous one, with ~12 ms of slack instead of the ~5 ms that drawing every refresh left.
    global matrixCanvas, lastSwap
    matrixCanvas.SetImage(image, offset)
    delay = lastSwap + swapDelay - time.monotonic()
    if delay > 0:
        time.sleep(delay)
    matrixCanvas = matrix.SwapOnVSync(matrixCanvas)
    lastSwap = time.monotonic()

def loadDisplay(symbol):
    # Returns the symbol's image, or None if it is missing or unreadable after a few tries
    for attempt in range(3):
        try:
            return Image.open(FULL_PATH + "/displays/" + symbol + ".png").convert('RGB')
        except Exception as e:
            print("Couldn't load " + symbol + " (" + repr(e) + "), retrying.")
            time.sleep(0.1)
    return None

def readDisplay(symbol):
    # Runs on the prefetch thread. SD card reads occasionally stall for 60+ ms, which would
    # freeze the scroll, so the file is read while the previous logo is still scrolling.
    with open(FULL_PATH + "/displays/" + symbol + ".png", 'rb') as f:
        return f.read()

def takeDisplay(symbol, pending):
    # Decodes the prefetched file (about 1 ms), falling back to a normal load on any error
    try:
        return Image.open(io.BytesIO(pending.result())).convert('RGB')
    except Exception as e:
        print("Prefetch of " + symbol + " failed (" + repr(e) + ").")
        return loadDisplay(symbol)

# The refresh thread is pinned to CPU 3 at top real-time priority. If this thread also runs
# on CPU 3 it has to wait for it and misses frames, so keep it (and the prefetch thread,
# which inherits this) on the other cores.
if os.cpu_count() >= 4:
    os.sched_setaffinity(0, {0, 1, 2})
prefetcher = ThreadPoolExecutor(max_workers=1)

refreshPeriod = measureRefresh(loading)
swapsPerStep = max(1, round(FRAME_TIME / refreshPeriod))
swapDelay = (swapsPerStep - 0.5) * refreshPeriod
print('Panel refresh %.2f ms, %d refreshes per step (%.1f px/s)'
      % (refreshPeriod * 1000, swapsPerStep, 1 / (refreshPeriod * swapsPerStep)))

# The loading screen stays up until the generator has recorded its PID (recordPID waits for it).
lp.recordPID('stocks', str(os.getpid()))
markReady()
print('Scroller is ready.')

#Making a canvas big enough to fit what the matrix panels will show along with space outside of the matrix panels where images will be prepared
canvas = Image.new('RGB', (LEDworkspace + 400, 32), (0, 0, 0))
img_width = 0
# New logos go just past the right edge of the visible area. SetImage only writes the canvas
# columns that land on the panel, so the canvas must always cover all 256 columns; otherwise
# the uncovered columns keep stale pixels from an older frame (they showed 1-2 px out of place).
ENTRY_X = LEDworkspace - 1

# Garbage collection: a full collection took ~16 ms (two scroll steps). Freezing everything
# allocated during startup leaves almost nothing to scan, so collecting between logos is ~0 ms.
gc.collect()
gc.freeze()
gc.disable()

pending = prefetcher.submit(readDisplay, stockSymbols[index])
lastSwap = time.monotonic()

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
    imageElement = takeDisplay(stockSymbols[index], pending)
    # Start reading the next logo while this one scrolls
    pending = prefetcher.submit(readDisplay, stockSymbols[(index + 1) % len(stockSymbols)])
    if imageElement is None:
        index += 1
        continue
    gc.collect()
    img_width, img_height = imageElement.size
    if ENTRY_X + img_width > canvas.size[0]:
        wider = Image.new('RGB', (ENTRY_X + img_width, 32), (0, 0, 0))
        wider.paste(canvas, (0, 0))
        canvas = wider
    canvas.paste(imageElement, (ENTRY_X, 0))
    xpos = -1
    while True:
        if (xpos < -img_width):
            break

        showStep(canvas, xpos - ENTRY_X + LEDworkspace)

        xpos = xpos - 1
    index += 1

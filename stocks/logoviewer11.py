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

stockSymbols = ["AAL", "AAPL", "ABT", "ADBE", "AMD", "AMZN"]

index = 0

LEDworkspace = options.chain_length * options.rows
print(LEDworkspace)
print("Starting LEDs in 10 seconds...")

time.sleep(10)
        
#Making a canvas big enough to fit what the matrix panels will show along with space outside of the matrix panels where images will be prepared
canvas = Image.new('RGB', (500, 32), (0, 0, 0))
matrixCanvas = matrix.CreateFrameCanvas()

while True:
    t0 = 0
    t1 = 0
    if index != 0:
        t0 = time.time()
        canvas = ImageChops.offset(canvas, xoffset=-img_width, yoffset=0)
        t1 = time.time()
    t2 = time.time()
    imageElement = Image.open("./displays/" + stockSymbols[index] + ".png").convert('RGB')
    t3 = time.time()
    img_width, img_height = imageElement.size
    canvas.paste(imageElement, (250, 0))
    xpos = 0
    t4 = time.time()
    openTime = t3 - t2
    everythingElseTime = (t4 - t3)
    print(openTime)
    print(everythingElseTime)
    while True:
        if (xpos < -img_width):
            break

        matrixCanvas.SetImage(canvas, xpos - 250 + LEDworkspace)

        matrixCanvas = matrix.SwapOnVSync(matrixCanvas)
        time.sleep(0.02)

        xpos = xpos - 1
    index += 1
            


# Main function
# e.g. call with
#  sudo ./image-scroller.py --chain=4
# if you have a chain of four
if __name__ == "__main__":
    print("test")

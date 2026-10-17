#!/usr/bin/env python

import time
import sys

from rgbmatrix import RGBMatrix, RGBMatrixOptions
from samplebase import SampleBase
from PIL import Image

stockSymbols = ["AAL", "AAPL", "ABT", "ADBE", "AMD", "AMZN", "AXP", "BA",
                "BBBY", "BBY", "BIG", "BP", "BRK-A", "CAT", "CBS", "COF",
                "COST", "CSCO", "CVS", "CVX", "DELL", "DG", "DIS", "DLTR",
                "DNKN", "DOW", "EBAY", "F", "FB", "FDX", "FITB", "GE", "GIS",
                "GM", "GOOG", "GS", "HAS", "HD", "HPQ", "HSBC", "HSY", "IBM",
                "KO", "MCD", "MMM", "NSRGY", "SVNDY", "XON"]

# Configuration for the matrix
options = RGBMatrixOptions()
options.rows = 32
options.chain_length = 1
options.parallel = 1
options.hardware_mapping = 'regular'  # If you have an Adafruit HAT: 'adafruit-hat'
options.multiplexing = 6
options.brightness = 30
options.led_rgb_sequence = "BGR"
options.pwm_lsb_nanoseconds = 350

matrix = RGBMatrix(options = options)
print("Press CTRL-C to stop.")

index = 0

class ImageScroller(SampleBase):
    def __init__(self, *args, **kwargs):
        print("test1.1")
        super(ImageScroller, self).__init__(*args, **kwargs)
        print("test1.2")
        self.parser.add_argument("-i", "--image", help="The image to display", default="../../../examples-api-use/runtext.ppm")
        print("test1.3")

    def run(self):

	print("test2")

	global index
        image_file = stockSymbols[index] + ".png"
        image = Image.open(image_file).convert('RGB')

	print("test3")

        # Make image fit our screen.
        # image.thumbnail((matrix.width, matrix.height), Image.ANTIALIAS)

        matrix.SetImage(image.convert('RGB'))
        
	print("test4")

        double_buffer = self.matrix.CreateFrameCanvas()
        index = index + 1
        
        xpos = 0

        while True:
            if (xpos <= matrix.width):
                xpos += 1
	        print("test5")
                double_buffer.SetImage(image, -xpos)
	        print("test6")
                double_buffer.SetImage(image, -xpos + matrix.width)
                print("test7")

                double_buffer = self.matrix.SwapOnVSync(double_buffer)
                print("test8")
                time.sleep(0.5)
	        print("test9")
            else:
                break
        
        if index > len(stockSymbols):
            index = 0

        print("test10")
    print("test88")
        
print("test")        
if __name__ == "__main__":
    image_scroller = ImageScroller()
    print("test0.1")
    ImageScroller(SampleBase)
    print("test0.2")
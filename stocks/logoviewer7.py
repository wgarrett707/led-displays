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

stockSymbols = ["AAL", "AAPL", "ABT", "ADBE", "AMD", "AMZN", "AXP", "BA",
                "BBBY", "BBY", "BIG", "BP", "BRK-A", "CAT", "CBS", "COF",
                "COST", "CSCO", "CVS", "CVX", "DELL", "DG", "DIS", "DLTR",
                "DNKN", "DOW", "EBAY", "F", "FB", "FDX", "FITB", "GE", "GIS",
                "GM", "GOOG", "GS", "HAS"]

index = 0

time.sleep(5)

class ImageScroller(SampleBase):
    print("test1")
    def run(self):
        global index
        global stockSymbols
        #Making a canvas big enough to fit what the matrix panels will show along with space outside of the matrix panels where images will be prepared
        canvas = Image.new('RGBA', (500, 32), (255, 255, 255, 0))
        matrixCanvas = matrix.CreateFrameCanvas()
        #make this into a function so i don't have to do it twice
        imageElement = Image.open(stockSymbols[index] + ".png").convert('RGB')
        img_width, img_height = imageElement.size
        image = []
        while True:
            print("test2")
            imageElement = Image.open(stockSymbols[index] + ".png").convert('RGB')
            image.insert(index, imageElement)
            canvas = ImageChops.offset(canvas, xoffset=-img_width, yoffset=None)
            canvas.paste(image[index], (250, 0))

            img_width, img_height = image[index].size

            # let's scroll
            xpos = 250
        
            while True:
                if (xpos < 280 - img_width):
                    break

                matrixCanvas.SetImage(image[index], xpos - 282)

                matrixCanvas = matrix.SwapOnVSync(matrixCanvas)
                time.sleep(0.03)

                xpos = xpos - 1
                print(xpos)

            index += 1


# Main function
# e.g. call with
#  sudo ./image-scroller.py --chain=4
# if you have a chain of four
if __name__ == "__main__":
    image_scroller = ImageScroller()
    image_scroller.run()
    print("test")

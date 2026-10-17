#!/usr/bin/env python3.7
import json
KEYS = json.load(open('/home/pi/led-scripts/apikeys.json'))

# Import statements
from rgbmatrix import RGBMatrix, RGBMatrixOptions
from PIL import Image, ImageDraw, ImageFont, ImageChops
from newsapi import NewsApiClient
import ledpackage as lp
import time
import math
import os

lp.recordPID('news', str(os.getpid()))

# Declare constants
FULL_PATH = '/home/pi/led-scripts/news/'
NEWS_API = NewsApiClient(api_key=KEYS['newsapi'])
TEXT_FONT = ImageFont.truetype(FULL_PATH + 'arial.ttf', size=26)
STANDARD_WIDTH = 500
SEPARATOR = Image.open(FULL_PATH + 'separator.png')

options = RGBMatrixOptions()
options.rows = 32
options.chain_length = 8
options.parallel = 1
options.hardware_mapping = 'regular'
options.brightness = 30
options.multiplexing = 6
options.led_rgb_sequence = "BGR"
options.pwm_lsb_nanoseconds = 350

matrix = RGBMatrix(options = options)

# Create matrix canvas
matrixCanvas = matrix.CreateFrameCanvas()

# Show loading screen
loading = Image.open(FULL_PATH + 'loading.png').convert('RGB')
matrixCanvas.SetImage(loading)
matrixCanvas = matrix.SwapOnVSync(matrixCanvas)

def getArticles():
    # Get the top headlines 
    top_headlines = NEWS_API.get_top_headlines(category='business', language='en', country='us', page_size=100)['articles']

    # Create list of article titles
    titleList = []
    for article in top_headlines:
        titleList.append(article['title'])

    return titleList

def clearDisplays():
    i = 0
    try:
        while True:
            os.remove(FULL_PATH + 'displays/' + str(i) + '.png')
            i += 1
    except:
        print('Deleted all displays.')
        generateImages()
        return

def getColor(n):
    colorDecide = n % 3
    if colorDecide == 0:
        rgb = (204, 0, 0) # Red
    if colorDecide == 1:
        rgb = (0, 204, 0) # Green
    if colorDecide == 2:
        rgb = (0, 0, 204) # Blue

    return rgb

def generateImages():
    # Declare variables for 'while' loop
    xpos = 500
    start = 0
    i = 0
    titleNum = 0
    startNum = 0
    done = False
    waiting = False
    imgs = []
    titleList = getArticles()
    
    # NOTE: THIS LOOP JUST GENERATES THE PHOTOS TO BE SHOWN. IT DOESN'T DO ANY OF THE DISPLAYING.
    while done == False:
        # Create a new image and the ability to draw on it
        img = Image.new('RGBA', (STANDARD_WIDTH, 32), color = (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # On the first iteration, grab the first title and get its dimensions
        if i == 0:
            title = titleList[titleNum]
            firstWidth, firstHeight = d.textsize(title, font=TEXT_FONT)
            mainColor = getColor(startNum)
        # Get the dimensions of the current title being displayed
        hlWidth, hlHeight = d.textsize(title, font=TEXT_FONT)
        # This if-statement makes sure that the current title being shown still has room to be shown even after scrolling a set amount of pixels (ex. 500).
        # If it doesn't, then it won't be shown at all since the next title will be displayed.
        if xpos - STANDARD_WIDTH > -hlWidth:
            xpos -= STANDARD_WIDTH
            d.text((xpos, 1), title, font=TEXT_FONT, fill=mainColor)
            # Checks if there's room for a separator that needs to be thrown in there at the end of the image
            if STANDARD_WIDTH - 32 <= xpos + hlWidth <= STANDARD_WIDTH:
                img.paste(SEPARATOR, (xpos + hlWidth, 0))
        # This if-statement is just to make sure that the very first article title has already been shown and there is room for the next one.
        if i >= math.floor((firstWidth + 32)/STANDARD_WIDTH):
            # This only runs if the next article title is waiting to be shown. This happens when another article title is already fully on-screen and there is no room for the next one.
            if waiting:
                # This continues waiting if the first article STILL is fully on-screen even after another complete scroll.
                if start >= STANDARD_WIDTH:
                    start -= STANDARD_WIDTH
                    waiting = True
                # If it's now able to be on-screen and thus done waiting, the next article is pasted along with the separator (the little circle).
                else:
                    d.text((start, 1), startTitle, font=TEXT_FONT, fill=startColor)
                    img.paste(SEPARATOR, (start - 32, 0))
                    waiting = False
                    # This makes the article that was waiting to be shown the MAIN article the script will focus on. 
                    title = startTitle
                    xpos = start
                    mainColor = startColor

            #If there is no article waiting to be shown, then the script identifies the next article to be shown. This article may then wait, meaning this process is a continuous cycle.
            else:
                startNum += 1
                # This checks to make sure the script isn't past the range of generated articles. If it is, it marks that it's done and the 'while' loop ends.
                if startNum == len(titleList):
                    done = True
                else:
                    startTitle = titleList[startNum]
                    startColor = getColor(startNum)
                # A quick formula to figure out where the next article currently is.
                start = hlWidth - STANDARD_WIDTH + start + 32
                # Special case for the second news display that makes sure it is posted right after the first one. This part of the loop doesn't happen until the first display has room
                # for the next display (see the "if i >= math.floor" statement), so there is absolutely no need for the second display to be marked as "waiting."
                if startNum == 1:
                    while start >= 500:
                        start -= 500
                # If it's starting position is currently off-screen, then it waits until the next iteration (after scrolling a set amount of pixels, like 500).
                if start >= 500:
                    start -= 500
                    waiting = True
                # If it's currently going to be on screen, then it places it on the screen with the separator and becomes the MAIN article the script will focus on.
                else:
                    # It only runs if the loop isn't marked as done. When it's marked as done, it runs through this section one last time so I have to stop it from pasting unnecessary text.
                    if not done:
                        d.text((start, 1), startTitle, font=TEXT_FONT, fill=startColor)
                        img.paste(SEPARATOR, (start - 32, 0))
                        title = startTitle
                        xpos = start
                        mainColor = startColor

        # This saves the image and prints out some information about it.
        imgs.append(img)
        print('hlWidth: ' + str(hlWidth) + '\nxpos: ' + str(xpos) + '\nstartNum: ' + str(startNum) + '\ni: ' + str(i))
        i += 1
    display(imgs)

def display(imgs):
    global matrixCanvas
    canvas = Image.new('RGB', (756, 32), (0, 0, 0))
    imageCount = len(imgs)
    index = 0
    
    while True:
        print(index)
        img = imgs[index]       
        canvas = ImageChops.offset(canvas, xoffset=-STANDARD_WIDTH, yoffset=0)
        canvas.paste(img, (256, 0))
    
        xpos = -1
        while True:
            if (xpos == -STANDARD_WIDTH):
                break

            matrixCanvas.SetImage(canvas, xpos)

            matrixCanvas = matrix.SwapOnVSync(matrixCanvas)
            time.sleep(0.01)

            xpos = xpos - 1
            
        if index == imageCount - 1:
            print('RESETTING')
            index = 0
        else:
            print('NOT RESETTING')
            index += 1
        
clearDisplays()


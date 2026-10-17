import json
KEYS = json.load(open('/home/pi/led-scripts/apikeys.json'))
from googleapiclient.discovery import build
from rgbmatrix import RGBMatrix, RGBMatrixOptions
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
import json
import time
import math
import os
import ledpackage as lp

lp.recordPID('subs', str(os.getpid()))

options = RGBMatrixOptions()
options.rows = 32
options.chain_length = 8
options.parallel = 1
options.hardware_mapping = 'regular'
options.brightness = 30
options.multiplexing = 6
options.led_rgb_sequence = "BGR"
options.pwm_lsb_nanoseconds = 350

FULL_PATH = '/home/pi/led-scripts/subs/'
matrix = RGBMatrix(options = options)
matrixCanvas = matrix.CreateFrameCanvas()

api_key = KEYS['youtube']
channel_list = ['UCk2x8Sc9iu8fSnwfpgJ3gSA', 'UC-la9-srEJVXXyj_r-giUdw', 'UCbmV4e0cAZvsqlgO2EqlJxg']
channel_data = ', '.join(channel_list)
youtube = build('youtube', 'v3', developerKey=api_key)

font7 = ImageFont.truetype(FULL_PATH + '5x7.ttf', size=16)
font5 = ImageFont.truetype(FULL_PATH + '5x5.ttf', size=10)
    
iconList = [Image.open(FULL_PATH + 'icons/1.png'),
            Image.open(FULL_PATH + 'icons/2.png'),
            Image.open(FULL_PATH + 'icons/3.png')]

# TO-DO: Make a centering system that works. Right now it's a few squares off
# if you use big view counts
def findCenter(infoList):
    add = 0
    for i in range(0, len(infoList)):
        if int(infoList[i][1]) >= 99999:
            add += ((len(infoList[i][1]) - 5) * 6) - 2
    totalX = (len(iconList) * 64) + add
    print(totalX)
    return round(((256 - totalX)/2) - 2)

def findUser(uID):
    for i in range(0, len(channel_list)):
        if uID == channel_list[i]:
            return i

def display(img):
    global matrixCanvas
    matrixCanvas.SetImage(img, 0)
    matrixCanvas = matrix.SwapOnVSync(matrixCanvas)

def listReturn(r):
    infoList = [None for i in range(0, len(channel_list))]
    for channel in r['items']:
        position = findUser(channel['id'])
        stats = channel['statistics']
        infoList[position] = (stats['subscriberCount'], stats['viewCount'])
    return infoList

def generateImage(infoList):
    img = Image.new('RGBA', (256, 32), color = (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.fontmode = '1'
    start = 0
    add = 0

    for i in range(0, len(infoList)):
        xpos = start + (i * 64) + add
        img.paste(iconList[i], (xpos, 0))
        d.text((xpos + 32, -3), 'SUBS:', font=font5)
        d.text((xpos + 32, 3), infoList[i][0], font=font7)
        d.text((xpos + 32, 13), 'VIEWS:', font=font5)
        d.text((xpos + 32, 19), infoList[i][1], font=font7)
        if int(infoList[i][1]) >= 99999:
            add += ((len(infoList[i][1]) - 5) * 6) - 2

    display(img.convert('RGB'))
    wait()

def gatherData():
    request = youtube.channels().list(
        part='statistics',
        id=channel_data)

    response = request.execute()

    generateImage(listReturn(response))

def wait():
    print('Waiting 5 minutes...')
    lp.waitAMinute(datetime.now().minute, 5)
    gatherData()

gatherData()

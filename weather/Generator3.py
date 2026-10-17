#!/usr/bin/env python3.7
import json
KEYS = json.load(open('/home/pi/led-scripts/apikeys.json'))
from rgbmatrix import RGBMatrix, RGBMatrixOptions
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
import ledpackage as lp
import requests
import time
import math
import os

lp.recordPID('weather', str(os.getpid()))

options = RGBMatrixOptions()
options.rows = 32
options.chain_length = 8
options.parallel = 1
options.hardware_mapping = 'regular'
options.brightness = 30
options.multiplexing = 6
options.led_rgb_sequence = "BGR"
options.pwm_lsb_nanoseconds = 350

FULL_PATH = '/home/pi/led-scripts/weather/'
error = Image.open(FULL_PATH + 'error.png').convert('RGB')
matrix = RGBMatrix(options = options)
matrixCanvas = matrix.CreateFrameCanvas()

fontBig = ImageFont.truetype(FULL_PATH + '6x11.ttf', size=32)
fontMedium = ImageFont.truetype(FULL_PATH + '6x11.ttf', size=16)
fontSmall = ImageFont.truetype(FULL_PATH + '5x5.ttf', size=10)

fcColors = [(178, 157, 217), (253, 253, 152), (254, 107, 100), (119, 221, 119), (119, 158, 203)]

weatherColors = {(-100, 15): (121, 159, 203),
                 (16, 30): (149, 180, 204),
                 (31, 45): (175, 199, 208),
                 (46, 60): (238, 241, 230),
                 (61, 70): (255, 227, 227),
                 (71, 80): (254, 201, 201),
                 (81, 90): (255, 148, 148),
                 (91, 200): (249, 102, 94)}

# Maybe resort this into a dictionary?
def findIcon(code):
    if code.startswith('01'):
        return '1.png'
    elif code.startswith('02'):
        return '2.png'
    elif code.startswith('03') or code.startswith('04'):
        return '3.png'
    elif code.startswith('09'):
        return '4.png'
    elif code.startswith('10'):
        return '5.png'
    elif code.startswith('11'):
        return '6.png'
    elif code.startswith('13'):
        return '7.png'
    elif code.startswith('50'):
        return '8.png'

def getFahrenheit(num):
   return str(round(((num - 273.15) * 9/5) + 32))

def getWeatherColor(t):
    for wRange in weatherColors:
        color = weatherColors[wRange]
        print(wRange)
        if wRange[0] <= t <= wRange[1]:
            return color

# The x position of the little "°F" sign changes depending on how many numbers
# are in the temperature. This function helps with that.
def getXCoord(t, fl):
    if t == 1:
        return 127, fl * 5 + 144 - (3 - fl)
    if t == 2:
        if fl == 3:
            return 141, 159
        else:
            return 141, 155
    if t == 3:
        return 155, 169

def getLists(forecastJson, weatherJson, fmtNow):
    getHigh = True
    passedToday = False
    fcIterator = 0
    fcDays = []
    fcTemps = []
    
    for daily in forecastJson['properties']['periods']:
        if fcIterator == 5:
            break
        if not passedToday:
            if fmtNow in daily['startTime']:
                continue
            else:
                passedToday = True

        # Because of how the API is organized, each day's high and low are in
        # two separate sections. This code checks to see if the iterator is
        # even, which means the section has the high, or odd, which means the
        # section has the low.
        if getHigh:
            dayName = daily['name'][:3]
            fcDays.append(dayName)
            fcTemps.append(str(daily['temperature']))
            getHigh = False
        else:
            fcTemps[fcIterator] += " " + str(daily['temperature'])
            getHigh = True
            fcIterator += 1
    return fcDays, fcTemps

def main():
    global matrixCanvas
    dateNow = datetime.now()

    while True:
        try:
            request = requests.get('http://api.openweathermap.org/data/2.5/weather?id=4896336&appid=' + KEYS['openweathermap'])
            weatherJson = request.json()
            request = requests.get('https://api.weather.gov/gridpoints/LOT/63,57/forecast')
            forecastJson = request.json()
            
            fcDays, fcTemps = getLists(forecastJson, weatherJson, dateNow.strftime('%Y-%m-%d'))
            break
        except:
            print('Errored out! Trying again...')
            matrixCanvas.SetImage(error)
            matrixCanvas = matrix.SwapOnVSync(matrixCanvas)
            time.sleep(1)
            pass
        
    print(fcDays, fcTemps)  
    print(weatherJson['main']['temp'])
    temperature = getFahrenheit(weatherJson['main']['temp'])
    feelslike = getFahrenheit(weatherJson['main']['feels_like'])
    #humidity = str(weatherJson['main']['humidity'])
    #windSpeed = str(round(weatherJson['wind']['speed'] * 2.23694))
    weatherIcon = Image.open(FULL_PATH + 'icons/' + findIcon(weatherJson['weather'][0]['icon']))
    wColor = getWeatherColor(int(temperature))
    weatherX, forecastX = getXCoord(len(temperature), len(feelslike))
    print(temperature, feelslike)

    img = Image.new('RGBA', (256, 32), color = (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.fontmode = '1'
    currentTime = dateNow.strftime('%I:%M')
    AMPMstatus = dateNow.strftime('%p')
    currentDate = dateNow.strftime('%a %b %d')

    # Time and Date
    d.text((1, 1), currentTime, font=fontBig)
    if AMPMstatus == 'AM':
        d.text((63, 1), AMPMstatus, font=fontMedium, fill=(255, 102, 102))
    else:
        d.text((63, 12), AMPMstatus, font=fontMedium, fill=(153, 102, 255))
    
    d.text((1, 21), currentDate, font=fontSmall)

    # Weather
    img.paste(weatherIcon, (80, 0))
    d.text((113, 1), temperature, font=fontBig, fill=wColor)
    d.text((weatherX, 1), '°F', font=fontMedium, fill=wColor)
    d.text((113, 21), 'FL: ' + feelslike + '°F', font=fontSmall)

    # Forecast
    for i in range(0, 5):
        d.text((forecastX, i * 5 - 3 + i), fcDays[i] + "  " + fcTemps[i], font=fontSmall, fill=fcColors[i])

    # Displaying on the Matrix Panel
    matrixCanvas.SetImage(img.convert('RGB'))
    matrixCanvas = matrix.SwapOnVSync(matrixCanvas)

    lp.waitAMinute(dateNow.minute, 1)

while True:
    main()

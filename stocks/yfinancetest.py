#!/usr/bin/env python
import yfinance as yf

while True:
    symbol = yf.Ticker(input("What ticker would you like to view? "))

    print(symbol.info['regularMarketPrice'], round(symbol.info['regularMarketChange'], 2))

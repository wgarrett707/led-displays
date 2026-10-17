#!/usr/bin/env python
path = "/home/pi/.local/lib/python2.7/site-packages/yfinance/utils.py"

f = open(path, "r+")
content = f.readlines()
print(content)
f.seek(0)
old = "maxsplit=1"
new = "1"
content = [w.replace(old, new) for w in content]
print(content)
f.write(content)
f.close()

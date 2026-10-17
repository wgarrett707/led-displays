import subprocess

subprocess.run("nice -n 10 sudo python3 /home/pi/led-scripts/stocks/FinnhubGeneratorFix2.py & nice -n -20 sudo python3 /home/pi/led-scripts/stocks/logoviewer12.py", shell=True)

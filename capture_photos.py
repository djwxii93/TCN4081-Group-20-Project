import picamera2
import time
import smbus2
import adafruit_as7341
import os

bus = smbus2.SMBus(1)
as7341 = adafruit_as7341.AS7341(bus)
picam2 = picamera2.Picamera2()
picam2.configure(picam2.create_preview_configuration(main={"size": (800, 600)}))
picam2.start()

os.makedirs("/home/pi/banana_images", exist_ok=True)
csv = open("/home/pi/banana_images/spectral.csv", "w")
csv.write("image_id,channel_415nm,...,channel_680nm\n")

image_id = 0
while True:
    filename = f"/home/pi/banana_images/img_{image_id:06d}.jpg"
    picam2.capture_file(filename)
    readings = as7341.all_channels
    csv.write(f"{filename},{','.join(map(str, readings))}\n")
    csv.flush()
    image_id += 1
    time.sleep(60)

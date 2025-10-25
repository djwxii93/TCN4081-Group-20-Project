import cv2
import numpy as np
import tflite_runtime.interpreter as tflite
from PIL import Image, ImageDraw, ImageFont
from waveshare_epd import epd2in13_V4
import picamera2
import time

labels = ['Unripe', 'Ripe', 'Spoiled']
interpreter = tflite.Interpreter(model_path='/home/pi/banana_ripeness.tflite')
interpreter.allocate_tensors()
input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()

epd = epd2in13_V4.EPD()
epd.init()
def update_eink(text):
    image = Image.new('1', (250, 122), 255)
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 20)
    draw.text((10, 10), text, font=font, fill=0)
    epd.display(epd.getbuffer(image))

picam2 = picamera2.Picamera2()
picam2.configure(picam2.create_preview_configuration(main={"size": (800, 600)}))
picam2.start()

while True:
    frame = picam2.capture_array()
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    input_shape = input_details[0]['shape']
    img = cv2.resize(rgb_frame, (input_shape[1], input_shape[2]))
    img = np.expand_dims(img, axis=0).astype(np.float32) / 255.0

    interpreter.set_tensor(input_details[0]['index'], img)
    interpreter.invoke()
    output_data = interpreter.get_tensor(output_details[0]['index'])
    predictions = np.argmax(output_data[0])
    confidence = np.max(output_data[0]) * 100

    result_text = f"{labels[predictions]}: {confidence:.1f}%"
    update_eink(result_text)
    print(result_text)
    time.sleep(60)

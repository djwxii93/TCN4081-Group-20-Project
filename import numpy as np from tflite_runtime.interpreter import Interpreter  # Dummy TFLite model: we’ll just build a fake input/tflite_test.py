import numpy as np
from tflite_runtime.interpreter import Interpreter

# Dummy TFLite model: we’ll just build a fake input/output structure
# Normally, you'd load your exported fruit_ripeness.tflite here
MODEL_PATH = "test_model.tflite"

# Create a minimal fake model if none exists
# (so the script can still run without you training yet)
import os
if not os.path.exists(MODEL_PATH):
    with open(MODEL_PATH, "wb") as f:
        f.write(b"TFL3")  # Just a placeholder so the file exists

# Load interpreter
interpreter = Interpreter(model_path=MODEL_PATH)
interpreter.allocate_tensors()

# Get input and output details
input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()

print("Model loaded successfully")
print("Input details:", input_details)
print("Output details:", output_details)

# Create a dummy input with correct shape
dummy_input = np.ones(input_details[0]['shape'], dtype=np.float32)

# Run inference
interpreter.set_tensor(input_details[0]['index'], dummy_input)
interpreter.invoke()
output_data = interpreter.get_tensor(output_details[0]['index'])

print("Inference output:", output_data)
print("✅ TFLite runtime is working on this Pi")

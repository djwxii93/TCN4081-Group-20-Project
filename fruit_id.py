# fruit_id.py
from pathlib import Path

def classify(image_path: str) -> dict:
    """
    Placeholder fruit classifier.
    Replace with ML model or OpenCV pipeline later.
    """
    image_name = Path(image_path).name.lower()

    # Super simple stub: look at filename
    if "banana" in image_name:
        fruit, conf = "banana", 0.9
    elif "mango" in image_name:
        fruit, conf = "mango", 0.85
    elif "avocado" in image_name:
        fruit, conf = "avocado", 0.88
    else:
        fruit, conf = "unknown", 0.5

    return {"fruit": fruit, "confidence": conf, "model": "stub-v0"}

if __name__ == "__main__":
    # quick test
    result = classify("out/scan_test_banana.jpg")
    print(result)

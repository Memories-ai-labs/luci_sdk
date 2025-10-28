import cv2
import os
import time

class SingleCameraCapture:
    """
    A simple RTSP camera capture & saving SDK
    - Supports real-time preview
    - Press 's' to save the current frame
    - Press 'q' to quit
    """

    def __init__(self, rtsp_url, save_dir="captures", name="cam"):
        self.rtsp_url = rtsp_url
        self.save_dir = save_dir
        self.name = name
        os.makedirs(save_dir, exist_ok=True)

        # Open RTSP stream
        print(f"[INFO] Connecting to camera: {rtsp_url}")
        self.cap = cv2.VideoCapture(self.rtsp_url)
        if not self.cap.isOpened():
            raise RuntimeError(f"Failed to open RTSP stream: {rtsp_url}")

    def run(self):
        """Real-time preview and saving"""
        print("✅ Camera started")
        print("📸 Press 's' to save current frame")
        print("❌ Press 'q' to quit")

        while True:
            ret, frame = self.cap.read()
            if not ret:
                print("[WARNING] Failed to read frame, please check RTSP connection.")
                time.sleep(0.5)
                continue

            cv2.imshow(f"Camera - {self.name}", frame)
            key = cv2.waitKey(1) & 0xFF

            if key == ord('q'):
                print("[INFO] Exiting.")
                break
            elif key == ord('s'):
                ts = time.strftime("%Y-%m-%d_%H-%M-%S")
                filename = os.path.join(self.save_dir, f"{self.name}_{ts}.jpg")
                cv2.imwrite(filename, frame)
                print(f"[Saved] {filename}")

        self.cap.release()
        cv2.destroyAllWindows()


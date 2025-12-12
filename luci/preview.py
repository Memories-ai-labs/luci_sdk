import cv2
import threading
import time


class LivePreview:
    def __init__(self, rtsp_url):
        self.rtsp_url = rtsp_url
        self.running = False
        self.status = "Idle"

    def start(self):
        self.running = True
        self.status = "Recording"
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.status = "Stopped"
        self.running = False

    def _run(self):
        cap = cv2.VideoCapture(self.rtsp_url)
        if not cap.isOpened():
            print("[Preview] Failed to open RTSP stream")
            return

        while self.running:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.1)
                continue

            # Overlay recording status
            cv2.putText(
                frame,
                f"Status: {self.status}",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 0, 255),
                2
            )

            cv2.imshow("LUCI Live Preview", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

        cap.release()
        cv2.destroyAllWindows()

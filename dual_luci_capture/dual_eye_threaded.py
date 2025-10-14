import cv2
import os
import time
import threading
import queue
from typing import Optional, Tuple


class CameraReader:
    """Background frame grabber for a single camera source (low latency)."""
    def __init__(self, src: str, name: str, drop_old: bool = True):
        self.src = src
        self.name = name
        self.drop_old = drop_old
        self.cap = cv2.VideoCapture(self.src)
        if not self.cap.isOpened():
            raise RuntimeError(f"Failed to open {name}: {src}")
        try:
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        self._frame_q = queue.Queue(maxsize=1 if drop_old else 0)
        self._last_fullres_frame = None
        self._stop_evt = threading.Event()
        self._thread = threading.Thread(target=self._worker, name=f"{name}-reader", daemon=True)

    def start(self): self._thread.start()
    def stop(self):
        self._stop_evt.set(); self._thread.join(timeout=2.0); self.cap.release()

    def _worker(self):
        while not self._stop_evt.is_set():
            ok, frame = self.cap.read()
            if not ok or frame is None:
                time.sleep(0.005); continue
            self._last_fullres_frame = frame
            if self.drop_old and self._frame_q.full():
                try: self._frame_q.get_nowait()
                except queue.Empty: pass
            try: self._frame_q.put_nowait((time.time(), frame))
            except queue.Full: pass

    def latest(self):
        try: return self._frame_q.get_nowait()
        except queue.Empty: return None
    def last_fullres(self): return self._last_fullres_frame


class DualCameraCaptureThreaded:
    """
    Dual-camera preview + paired saving.
    - Press 's' to save two full-resolution images: cam1_<timestamp>.jpg and cam2_<timestamp>.jpg
    - Press 'q' to quit.
    """
    def __init__(self, rtsp1, rtsp2, save_dir="captures", window_name="Dual Camera"):
        self.rtsp1, self.rtsp2 = rtsp1, rtsp2
        self.save_dir = os.path.abspath(save_dir)
        os.makedirs(self.save_dir, exist_ok=True)
        self.window_name = window_name
        self.cam1, self.cam2 = CameraReader(rtsp1, "cam1"), CameraReader(rtsp2, "cam2")
        self._running = False
        self._toast_until = 0
        self._toast_msg = ""

    @staticmethod
    def _hstack_resize_to_min_height(f1, f2):
        h1, w1 = f1.shape[:2]; h2, w2 = f2.shape[:2]; h = min(h1, h2)
        if h1 != h: f1 = cv2.resize(f1, (int(w1*h/h1), h))
        if h2 != h: f2 = cv2.resize(f2, (int(w2*h/h2), h))
        return cv2.hconcat([f1, f2])

    def _save_two(self):
        f1, f2 = self.cam1.last_fullres(), self.cam2.last_fullres()
        if f1 is None or f2 is None:
            print("[WARN] Save skipped: one or both cameras have no frame yet.")
            self._toast_msg, self._toast_until = "Save skipped (no frame)", time.time()+1
            return False

        now = time.time()
        ts = time.strftime("%Y%m%d-%H%M%S") + f"_{int((now%1)*1000):03d}"
        path1 = os.path.join(self.save_dir, f"cam1_{ts}.jpg")
        path2 = os.path.join(self.save_dir, f"cam2_{ts}.jpg")

        ok1, ok2 = cv2.imwrite(path1, f1), cv2.imwrite(path2, f2)
        if ok1 and ok2:
            print(f"[Saved] {path1}, {path2}")
            self._toast_msg, self._toast_until = "Saved pair", time.time()+1
            return True
        print(f"[ERROR] Save failed. ok1={ok1}, ok2={ok2}")
        self._toast_msg, self._toast_until = "Save failed", time.time()+1
        return False

    def run(self):
        print("Press 's' to save pair, 'q' to quit.")
        print(f"Saving to: {self.save_dir}")
        self.cam1.start(); self.cam2.start()
        self._running = True
        last_time = time.time(); frame_counter, fps = 0, 0.0
        try:
            while self._running:
                g1, g2 = self.cam1.latest(), self.cam2.latest()
                if g1 is None or g2 is None:
                    cv2.waitKey(1); continue
                _, fr1 = g1; _, fr2 = g2
                combined = self._hstack_resize_to_min_height(fr1, fr2)
                frame_counter += 1
                now = time.time()
                if now - last_time >= 1.0:
                    fps = frame_counter / (now - last_time)
                    frame_counter, last_time = 0, now
                cv2.putText(combined, f"Display FPS: {fps:.1f}", (12,28),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255),2)
                if time.time() < self._toast_until:
                    cv2.putText(combined, self._toast_msg, (12,60),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,0),2)
                cv2.imshow(self.window_name, combined)
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'): self._running = False
                elif key in (ord('s'), ord('S')): self._save_two()
        finally:
            self.cam1.stop(); self.cam2.stop(); cv2.destroyAllWindows()


if __name__ == "__main__":
    RTSP_LEFT = "rtsp://192.168.137.23:50001/live/0"
    RTSP_RIGHT = "rtsp://192.168.137.188:50001/live/0"
    app = DualCameraCaptureThreaded(RTSP_LEFT, RTSP_RIGHT, save_dir="captures")
    app.run()



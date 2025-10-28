from capture_sdk import SingleCameraCapture

cap = SingleCameraCapture(
    rtsp_url="rtsp://192.168.137.141:50001/live/0",
    save_dir="captures",
    name="cam"
)
cap.run()  # Press 's' to save, 'q' to exit

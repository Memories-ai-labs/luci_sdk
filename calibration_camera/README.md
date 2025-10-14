# Stereo Camera Calibration (Intrinsics & Extrinsics) — Workflow

This README documents a **complete, reproducible pipeline** to calibrate **camera intrinsics** and **stereo extrinsics**, export parameters to YAML, and quickly validate with rectification and a depth demo.

> Works with OpenCV 4.x on Windows/macOS/Linux. Chessboard or Charuco supported. Outputs are compatible with downstream scripts.

---

## 1) Environment

```bash

pip install opencv-python opencv-contrib-python numpy pyyaml matplotlib
# Optional: for depth demo
pip install open3d
```
If using system OpenCV, ensure it includes **contrib** (for Charuco).

---

## 2) Print or generate a calibration target

- **Chessboard** (recommended): inner corners, e.g. `8x5` (9 columns × 6 rows of inner intersections).
- **Charuco**: `DICT_4X4_100` or `DICT_5X5_100`, with known square size and marker size.
- Measure **square size** precisely in **meters** (e.g., 0.030 m). You will need it as `--square 0.030`.

> Keep the board **flat** and **rigid**. Avoid glossy lamination that causes glare.

---

## 3) Data capture (left/right image pairs or videos)

Capture at least **20–40 distinct poses**:
- Vary distance (near/far), tilt, yaw, and position.
- Cover **all four corners** and center of the image.
- Use **simultaneous** capture for stereo (ensure timestamps/pairs match).

Folder structure (example):
```
calibration_images_dual_eye/
  
  cam1_xxx.png
  cam1_xxx.png
  ...
  cam2_xxx.png
  cam2_xxx.png
  ...
```
> Filenames must match across cam1/cam2 (same count, same ordering), cam1 is the left one, cam2 is the right one.

If you recorded videos, extract frames first (example command included below).

---

## 4) Intrinsic calibration (per camera)

Run for **left** and **right** separately. You can use chessboard or Charuco.

### 4.1 Chessboard intrinsics
```bash
python calibration_images_dual_eye/calibration_intrinsics.py 
```


**Outputs (YAML):**
- `K` (3×3 camera matrix)
- `D` (distortion: k1, k2, p1, p2, k3[, k4…])
- `size` (width, height)
- `rms` (reprojection error)

> **Target RMS**: typically **<0.5 px** for good lenses; **<1.0 px** is acceptable.

---

## 5) Stereo extrinsic calibration (R, T between cameras)

After **both** intrinsics are done:

```bash
python calibration_images_dual_eye/stereo_calibration.py
```

**Outputs (YAML):**
- `K1`, `D1`, `K2`, `D2`
- `R`, `T` (rotation & translation from left to right)
- `R1`, `R2`, `P1`, `P2`, `Q` (rectification and reprojection matrices)
- `rms_stereo` (stereo reprojection error)
- `baseline` (meters), derived from `T`

> Tip: if you get **high RMS** (>1.0 px) or **odd baseline**, remove outliers images (blurred/extreme angles) and re-run.

---



---

## 12) References

- OpenCV Camera Calibration: <https://docs.opencv.org/master/dc/dbb/tutorial_py_calibration.html>
- Stereo Calibration + Rectification: <https://docs.opencv.org/master/dd/d53/tutorial_py_depthmap.html>
- Charuco Boards: <https://docs.opencv.org/master/d9/d6a/group__aruco.html>
- Hartley & Zisserman, *Multiple View Geometry in Computer Vision*, 2nd Ed.
- Zach & Pock, *A Practical Guide to Optical Flow & Stereo Matching*, 2017 (lecture notes)

---

### Citation

If this calibration pipeline or the resulting parameters are used in your publication or project, please cite your repo accordingly.

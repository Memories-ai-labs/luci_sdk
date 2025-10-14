# calibrate_cam1_cam2.py
import os
import glob
import json
from pathlib import Path
import numpy as np
import cv2

# ===================== Configuration (edit as needed) =====================
IMG_DIR = r"../calibration_images_dual_eye"             # Folder containing raw binocular images
CAM1_KEY = "cam1"                 # Filename keyword for cam1 (case-insensitive)
CAM2_KEY = "cam2"                 # Filename keyword for cam2 (case-insensitive)

# Number of chessboard inner corners (e.g., 9x6 means 9 per row, 6 per column)
PATTERN_COLS = 8                  # Number of inner corners horizontally
PATTERN_ROWS = 5                  # Number of inner corners vertically
SQUARE_SIZE = 0.03           #unit meters      # Unit length (any unit); affects only extrinsic scale, not intrinsics

# Processing and output
OUTPUT_DIR = "../intrisic_result"        # Output directory for results
SAVE_CORNER_VIS = True            # Save corner visualization images
SAVE_UNDISTORT_PREVIEW = True     # Save undistortion preview images
UNDISTORT_SAMPLES = 6             # Number of undistortion preview samples (per camera)
RATIONAL_MODEL = True             # Use richer distortion model (k1..k6, p1, p2)
# ========================================================================


def glob_images(img_dir, key, exts=("*.jpg","*.jpeg","*.png","*.bmp","*.tif","*.tiff")):
    img_dir = Path(img_dir)
    files = []
    for ext in exts:
        files.extend(glob.glob(str(img_dir / ext)))
    files = [f for f in files if key.lower() in Path(f).name.lower()]
    files.sort()
    return files


def build_object_points(pattern_size, square_size):
    cols, rows = pattern_size
    objp = np.zeros((rows*cols, 3), np.float32)
    # Column-major or row-major is fine; it just needs to match the order returned by findChessboardCorners (OpenCV guarantees this)
    objp[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)
    objp *= float(square_size)
    return objp


def detect_corners(images, pattern_size):
    cols, rows = pattern_size
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_COUNT, 30, 1e-3)
    flags = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_FAST_CHECK

    objpoints = []     # 3D points (chessboard coordinates)
    imgpoints = []     # 2D points (pixel coordinates)
    img_sizes = None   # (w, h)
    ok_images = []     # Files with successfully detected corners
    vis_images = []    # For visualization: original image + corners overlay

    for f in images:
        img = cv2.imdecode(np.fromfile(f, dtype=np.uint8), cv2.IMREAD_COLOR)  # Support non-ASCII paths
        if img is None:
            print(f"[WARN] Failed to read: {f}")
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if img_sizes is None:
            h, w = gray.shape[:2]
            img_sizes = (w, h)

        ret, corners = cv2.findChessboardCorners(gray, (cols, rows), flags)
        if not ret:
            # Try again with FAST_CHECK disabled
            ret, corners = cv2.findChessboardCorners(gray, (cols, rows),
                                                     cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE)
        if ret:
            # Sub-pixel refinement
            corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
            objpoints.append(build_object_points((cols, rows), SQUARE_SIZE))
            imgpoints.append(corners)
            ok_images.append(f)

            # Draw detected corners
            vis = img.copy()
            cv2.drawChessboardCorners(vis, (cols, rows), corners, ret)
            vis_images.append((f, vis))
        else:
            print(f"[INFO] Chessboard corners not found: {f}")

    return objpoints, imgpoints, img_sizes, ok_images, vis_images


def calibrate_single_camera(objpoints, imgpoints, img_size, use_rational):
    if use_rational:
        calib_flags = cv2.CALIB_RATIONAL_MODEL
    else:
        calib_flags = 0

    rms, K, D, rvecs, tvecs = cv2.calibrateCamera(
        objectPoints=objpoints,
        imagePoints=imgpoints,
        imageSize=img_size,
        cameraMatrix=None,
        distCoeffs=None,
        flags=calib_flags
    )
    return rms, K, D, rvecs, tvecs


def per_image_reprojection_errors(objpoints, imgpoints, rvecs, tvecs, K, D):
    errs = []
    for i in range(len(objpoints)):
        proj, _ = cv2.projectPoints(objpoints[i], rvecs[i], tvecs[i], K, D)
        e = cv2.norm(imgpoints[i], proj, cv2.NORM_L2) / len(proj)
        errs.append(float(e))
    errs = np.array(errs, dtype=np.float64)
    return {
        "mean": float(np.mean(errs)) if len(errs) else None,
        "median": float(np.median(errs)) if len(errs) else None,
        "max": float(np.max(errs)) if len(errs) else None,
        "min": float(np.min(errs)) if len(errs) else None,
        "list": errs.tolist() if len(errs) else []
    }


def save_yaml(path, K, D, img_size, rms, err_stats, ok_images):
    data = {
        "image_width": img_size[0],
        "image_height": img_size[1],
        "camera_matrix": {"rows": 3, "cols": 3, "data": K.flatten().tolist()},
        "distortion_coefficients": {"rows": 1, "cols": len(D.flatten()), "data": D.flatten().tolist()},
        "rms_reprojection_error": float(rms),
        "per_image_error": err_stats,
        "used_images": ok_images,
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("%YAML:1.0\n")
        # For readability, also output a JSON payload
        f.write("# Below is JSON payload for convenience\n")
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_corner_visualizations(vis_images, out_dir, tag):
    out = Path(out_dir) / f"{tag}_corners"
    out.mkdir(parents=True, exist_ok=True)
    for f, vis in vis_images:
        name = Path(f).name
        out_path = out / name
        # Use imencode to support non-ASCII paths
        ext = ".jpg"
        success, buf = cv2.imencode(ext, vis)
        if success:
            out_path.write_bytes(buf.tobytes())


def save_projection_overlay(objpoints, imgpoints, rvecs, tvecs, K, D, ok_images, out_dir, tag, max_samples=10):
    out = Path(out_dir) / f"{tag}_projection_overlay"
    out.mkdir(parents=True, exist_ok=True)
    idxs = np.linspace(0, len(ok_images)-1, num=min(len(ok_images), max_samples), dtype=int).tolist()
    for i in idxs:
        f = ok_images[i]
        img = cv2.imdecode(np.fromfile(f, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            continue
        # Draw detected corners (green) and projected corners (red)
        proj, _ = cv2.projectPoints(objpoints[i], rvecs[i], tvecs[i], K, D)
        for p in imgpoints[i]:
            cv2.circle(img, tuple(np.int32(p[0])), 4, (0, 255, 0), -1)
        for p in proj:
            cv2.circle(img, tuple(np.int32(p[0])), 2, (0, 0, 255), -1)

        out_path = out / Path(f).name
        success, buf = cv2.imencode(".jpg", img)
        if success:
            out_path.write_bytes(buf.tobytes())


def save_undistort_previews(K, D, ok_images, out_dir, tag, sample_n=6):
    out = Path(out_dir) / f"{tag}_undistort"
    out.mkdir(parents=True, exist_ok=True)
    choose = ok_images[:sample_n] if len(ok_images) <= sample_n else list(np.random.choice(ok_images, sample_n, replace=False))
    for f in choose:
        img = cv2.imdecode(np.fromfile(f, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            continue
        h, w = img.shape[:2]
        newK, roi = cv2.getOptimalNewCameraMatrix(K, D, (w, h), alpha=0)  # alpha=0 crop black borders, =1 keep more FOV
        und = cv2.undistort(img, K, D, None, newK)
        # Side-by-side comparison
        vis = np.hstack([img, und])
        out_path = out / ("undistort_" + Path(f).name)
        success, buf = cv2.imencode(".jpg", vis)
        if success:
            out_path.write_bytes(buf.tobytes())


def run_for_key(key, tag):
    print(f"\n==== Processing {tag} (keyword: {key}) ====")
    images = glob_images(IMG_DIR, key)
    print(f"Found {len(images)} images")
    if len(images) == 0:
        return None

    objpoints, imgpoints, img_size, ok_images, vis_images = detect_corners(images, (PATTERN_COLS, PATTERN_ROWS))
    print(f"Corner detection success {len(ok_images)}/{len(images)}")

    if len(ok_images) < 8:
        print("[WARN] Fewer than 8 valid images. Consider collecting more or checking the chessboard/exposure/sharpness")
    if len(ok_images) < 3:
        print("[ERROR] Too few valid samples to calibrate")
        return None

    rms, K, D, rvecs, tvecs = calibrate_single_camera(objpoints, imgpoints, img_size, RATIONAL_MODEL)
    print(f"[{tag}] Single-camera calibration done: RMS reprojection error = {rms:.4f} px")

    err_stats = per_image_reprojection_errors(objpoints, imgpoints, rvecs, tvecs, K, D)
    print(f"[{tag}] Error stats: mean={err_stats['mean']:.4f}, median={err_stats['median']:.4f}, "
          f"max={err_stats['max']:.4f}, min={err_stats['min']:.4f}")

    # Save results
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    save_yaml(Path(OUTPUT_DIR) / f"{tag}_intrinsics.yaml", K, D, img_size, rms, err_stats, ok_images)

    # Visualization and validation
    if SAVE_CORNER_VIS and len(vis_images):
        save_corner_visualizations(vis_images, OUTPUT_DIR, tag)
    save_projection_overlay(objpoints, imgpoints, rvecs, tvecs, K, D, ok_images, OUTPUT_DIR, tag, max_samples=8)
    if SAVE_UNDISTORT_PREVIEW:
        save_undistort_previews(K, D, ok_images, OUTPUT_DIR, tag, sample_n=UNDISTORT_SAMPLES)

    # Print intrinsics
    print(f"\n[{tag}] K =\n{K}\n[{tag}] D = {D.ravel()}\n")
    return {
        "tag": tag,
        "K": K,
        "D": D,
        "rms": rms,
        "err_stats": err_stats,
        "ok_images": ok_images,
        "img_size": img_size
    }


def main():
    print("=== Monocular intrinsics calibration (split from binocular captures by keyword) ===")
    print(f"Image directory: {IMG_DIR}")
    print(f"Chessboard: {PATTERN_COLS} x {PATTERN_ROWS} inner corners, square size: {SQUARE_SIZE}")

    res1 = run_for_key(CAM1_KEY, "cam1")
    res2 = run_for_key(CAM2_KEY, "cam2")

    # Simple consistency note (optional)
    if res1 and res2:
        h1, w1 = res1["img_size"][1], res1["img_size"][0]
        h2, w2 = res2["img_size"][1], res2["img_size"][0]
        if (w1, h1) != (w2, h2):
            print("[NOTE] cam1 and cam2 resolutions differ. This is allowed, but keep it in mind for stereo calibration/rectification.")
        # Print approximate focal length comparison
        fx1, fy1 = res1["K"][0, 0], res1["K"][1, 1]
        fx2, fy2 = res2["K"][0, 0], res2["K"][1, 1]
        print(f"[Compare] Focal length in pixels: cam1 (fx,fy)=({fx1:.1f},{fy1:.1f}), cam2 (fx,fy)=({fx2:.1f},{fy2:.1f})")

    print(f"\nAll done. Results saved to: {Path(OUTPUT_DIR).absolute()}")


if __name__ == "__main__":
    main()

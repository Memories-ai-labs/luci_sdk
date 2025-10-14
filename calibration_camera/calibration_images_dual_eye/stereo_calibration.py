# stereo_calibrate_from_pairs.py
import os, glob, json
from pathlib import Path
import numpy as np
import cv2

# ========== Configuration ==========
IMG_DIR = r"../calibration_images_dual_eye"           # Directory containing stereo raw images
CAM1_KEY = "cam1"               # cam1 filename keyword (case insensitive)
CAM2_KEY = "cam2"               # cam2 filename keyword (case insensitive)

# Number of chessboard "inner corners" (please modify to your actual specifications)
PATTERN_COLS = 8
PATTERN_ROWS = 5
SQUARE_SIZE = 0.03               # Square side length (arbitrary unit, used to determine T scale) m

# Whether to prioritize using existing monocular intrinsics (strongly recommended to use previous step results)
USE_EXISTING_INTRINSICS = True
CAM1_INTRINSIC_PATH = "../intrinsic_result/cam1_intrinsics.yaml"
CAM2_INTRINSIC_PATH = "../intrinsic_result/cam2_intrinsics.yaml"

# Model/Output
RATIONAL_MODEL = True           # Use richer distortion model (k1..k6, p1, p2)
OUTPUT_DIR = "../stereo_calibration_result"
SAVE_VIS = True                 # Save corner points/epipolar lines/rectification visualization
MAX_PAIR_VIS = 8                # Number of visualization examples
# ==========================


def glob_images(img_dir, key, exts=("*.jpg","*.jpeg","*.png","*.bmp","*.tif","*.tiff")):
    img_dir = Path(img_dir)
    files = []
    for ext in exts:
        files.extend(glob.glob(str(img_dir / ext)))
    files = [f for f in files if key.lower() in Path(f).name.lower()]
    files.sort()
    return files


def try_pair_lists(list1, list2, key1, key2):
    """
    Strict one-to-one pairing:
    - Find corresponding cam2 files only by replacing the first occurrence of key1 with key2 in cam1 filenames
    - If any cam1 cannot find corresponding cam2, or there are extra cam2 files, throw exception directly with fix hints
    - Never degenerate to "index-based pairing"
    """
    key1l, key2l = key1.lower(), key2.lower()

    # Right camera filename -> full path
    right_map = {Path(f).name.lower(): f for f in list2}

    pairs = []
    missing = []  # [(left_name, expected_right_name), ...]
    left_names = [Path(f).name for f in list1]

    # Construct expected right image filename for each left image (case insensitive)
    expected_right_names = []
    for f1 in list1:
        n1 = Path(f1).name
        n1l = n1.lower()
        if key1l not in n1l:
            # This should not happen normally (glob already filtered by keyword), but still provide hint
            missing.append((n1, f"<filename does not contain keyword {key1}>"))
            continue
        exp = n1l.replace(key1l, key2l, 1)  # Only replace first occurrence to avoid mistakes
        expected_right_names.append(exp)
        if exp in right_map:
            pairs.append((f1, right_map[exp]))
        else:
            missing.append((n1, exp))

    # Check if right camera has "extra files" (outside expected set)
    expected_set = set(expected_right_names)
    extra_right = [Path(f).name for f in list2 if Path(f).name.lower() not in expected_set]

    if missing or extra_right or len(pairs) == 0:
        msg_lines = []
        msg_lines.append("❌ Cannot pair files one-to-one by filename (strict mode).")
        if missing:
            msg_lines.append(f"- Missing right camera pairs: {len(missing)} files (showing max 10 examples)")
            for left_name, exp in missing[:10]:
                msg_lines.append(f"  · Left: {left_name} → Expected right: {exp}")
        if extra_right:
            msg_lines.append(f"- Extra right camera files: {len(extra_right)} files (showing max 10 examples)")
            for name in extra_right[:10]:
                msg_lines.append(f"  · Right: {name}")
        msg_lines.append("")
        msg_lines.append("👉 Solution: Ensure naming allows one-to-one replacement matching, e.g.:")
        msg_lines.append("   scene_0001_cam1.jpg ↔ scene_0001_cam2.jpg")
        msg_lines.append(f"   (keywords: {key1} / {key2}; distinguish first replacement)")
        raise RuntimeError("\n".join(msg_lines))

    print(f"[PAIR] Strict pairing successful: {len(pairs)} pairs")
    return pairs

def build_object_points(pattern_size, square_size):
    cols, rows = pattern_size
    objp = np.zeros((rows*cols, 3), np.float32)
    objp[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)
    objp *= float(square_size)
    return objp


def detect_corners_single(img_path, cols, rows):
    """Compatible with horizontal/vertical (swap cols/rows) automatic corner detection, normalize order to (cols, rows) row-first."""
    img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None: return None, None, None, False
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    flags_base = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE
    flags_fast = flags_base | cv2.CALIB_CB_FAST_CHECK
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_COUNT, 30, 1e-3)

    # First try (cols, rows)
    ret, corners = cv2.findChessboardCorners(gray, (cols, rows), flags_fast)
    if not ret:
        ret, corners = cv2.findChessboardCorners(gray, (cols, rows), flags_base)

    used_swapped = False
    if not ret:
        # Then try (rows, cols)
        ret2, corners2 = cv2.findChessboardCorners(gray, (rows, cols), flags_fast)
        if not ret2:
            ret2, corners2 = cv2.findChessboardCorners(gray, (rows, cols), flags_base)
        if ret2:
            corners2 = cv2.cornerSubPix(gray, corners2, (11,11), (-1,-1), criteria)
            grid = corners2.reshape((rows, cols, 1, 2))
            grid = np.transpose(grid, (1, 0, 2, 3))  # Swap rows and columns, convert back to standard direction
            corners = grid.reshape((-1, 1, 2))
            used_swapped = True
            ret = True

    if ret:
        if not used_swapped:
            corners = cv2.cornerSubPix(gray, corners, (11,11), (-1,-1), criteria)
        return img, corners, (w, h), True
    else:
        return img, None, (w, h), False


def load_intrinsics_from_yaml(path):
    """Read intrinsics saved from previous stage; compatible with our written JSON structure."""
    if not Path(path).exists():
        return None, None
    txt = Path(path).read_text(encoding="utf-8")
    # Simply extract JSON block (we wrote JSON after YAML header when saving)
    brace_start = txt.find("{")
    brace_end = txt.rfind("}")
    if brace_start == -1 or brace_end == -1:
        return None, None
    data = json.loads(txt[brace_start:brace_end+1])
    K = np.array(data["camera_matrix"]["data"], dtype=np.float64).reshape(3,3)
    D = np.array(data["distortion_coefficients"]["data"], dtype=np.float64).reshape(1, -1)
    return K, D


def save_yaml(path, payload: dict):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("%YAML:1.0\n# JSON payload below for convenience\n")
        json.dump(payload, f, ensure_ascii=False, indent=2)


def main():
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    print("=== Stereo calibration started ===")
    print(f"Directory: {IMG_DIR} | Keywords: {CAM1_KEY} / {CAM2_KEY}")
    print(f"Chessboard: {PATTERN_COLS}x{PATTERN_ROWS}, square side length: {SQUARE_SIZE}")

    left_list = glob_images(IMG_DIR, CAM1_KEY)
    right_list = glob_images(IMG_DIR, CAM2_KEY)
    print(f"Found cam1={len(left_list)}, cam2={len(right_list)} images")

    pairs = try_pair_lists(left_list, right_list, CAM1_KEY, CAM2_KEY)
    print(f"Valid candidate pairs: {len(pairs)}")
    if len(pairs) < 8:
        print("[ERROR] Paired images < 8 pairs, insufficient samples for stable stereo calibration.")
        return

    # Detect corners for each pair
    cols, rows = PATTERN_COLS, PATTERN_ROWS
    objp = build_object_points((cols, rows), SQUARE_SIZE)

    objpoints = []
    imgpoints_l, imgpoints_r = [], []
    img_size = None
    used_pairs = []
    vis_pairs = []

    for fL, fR in pairs:
        imgL, cornersL, sizeL, okL = detect_corners_single(fL, cols, rows)
        imgR, cornersR, sizeR, okR = detect_corners_single(fR, cols, rows)
        if img_size is None:
            img_size = sizeL  # Assume left and right resolutions are consistent; if not, can continue but rectification needs to use respective sizes
        if okL and okR:
            objpoints.append(objp.copy())
            imgpoints_l.append(cornersL)
            imgpoints_r.append(cornersR)
            used_pairs.append((fL, fR))
            if SAVE_VIS and len(vis_pairs) < MAX_PAIR_VIS:
                vL = imgL.copy(); vR = imgR.copy()
                cv2.drawChessboardCorners(vL, (cols, rows), cornersL, True)
                cv2.drawChessboardCorners(vR, (cols, rows), cornersR, True)
                vis_pairs.append((Path(fL).name, vL, Path(fR).name, vR))
        else:
            print(f"[INFO] Skipped (corner detection failed): {Path(fL).name} | {Path(fR).name}")

    n_ok = len(objpoints)
    print(f"Number of stereo pairs with successful corner detection: {n_ok}")
    if n_ok < 8:
        print("[ERROR] Valid samples < 8, stereo calibration will be unstable. Please take more photos or check corner quality.")
        return

    # Read or initialize intrinsics
    K1 = D1 = K2 = D2 = None
    if USE_EXISTING_INTRINSICS:
        K1, D1 = load_intrinsics_from_yaml(CAM1_INTRINSIC_PATH)
        K2, D2 = load_intrinsics_from_yaml(CAM2_INTRINSIC_PATH)
        if K1 is None or K2 is None:
            print("[WARN] Cannot find monocular intrinsic files, will estimate intrinsics simultaneously in stereo calibration.")
    calib_flags = 0
    if RATIONAL_MODEL:
        calib_flags |= cv2.CALIB_RATIONAL_MODEL
    if K1 is not None and K2 is not None:
        calib_flags |= cv2.CALIB_FIX_INTRINSIC  # Trust monocular intrinsics, only estimate extrinsics
        print("[INFO] Using existing intrinsics (FIX_INTRINSIC)")

    # stereoCalibrate
    criteria = (cv2.TERM_CRITERIA_MAX_ITER + cv2.TERM_CRITERIA_EPS, 100, 1e-6)
    ret, K1, D1, K2, D2, R, T, E, F = cv2.stereoCalibrate(
        objectPoints=objpoints,
        imagePoints1=imgpoints_l,
        imagePoints2=imgpoints_r,
        cameraMatrix1=K1,
        distCoeffs1=D1,
        cameraMatrix2=K2,
        distCoeffs2=D2,
        imageSize=img_size,
        criteria=criteria,
        flags=calib_flags
    )
    print(f"\n[Result] Stereo calibration RMS = {ret:.4f} pixels")
    print(f"[Extrinsics] Baseline |T| = {np.linalg.norm(T):.4f} (unit = SQUARE_SIZE)")

    # Stereo rectification (Rectify)
    R1, R2, P1, P2, Q, roi1, roi2 = cv2.stereoRectify(
        K1, D1, K2, D2, img_size, R, T, flags=cv2.CALIB_ZERO_DISPARITY, alpha=0
    )
    map1x, map1y = cv2.initUndistortRectifyMap(K1, D1, R1, P1, img_size, cv2.CV_32FC1)
    map2x, map2y = cv2.initUndistortRectifyMap(K2, D2, R2, P2, img_size, cv2.CV_32FC1)

    # Verification: After rectification, "vertical disparity" should be close to 0 (corresponding points have similar y coordinates)
    y_errs = []
    for i in range(n_ok):
        ptsL = cv2.undistortPoints(imgpoints_l[i], K1, D1, R=R1, P=P1)
        ptsR = cv2.undistortPoints(imgpoints_r[i], K2, D2, R=R2, P=P2)
        # Shape (N,1,2)
        dy = np.abs(ptsL[:,0,1] - ptsR[:,0,1])
        y_errs.append(dy)
    y_errs = np.concatenate(y_errs) if y_errs else np.array([])
    vmean, vmed, vmax = float(np.mean(y_errs)), float(np.median(y_errs)), float(np.max(y_errs))
    print(f"[Verification] Post-rectification vertical error |Δy|: mean={vmean:.4f}, median={vmed:.4f}, max={vmax:.4f} pixels (smaller is better)")

    # Save parameters
    payload = {
        "image_size": {"w": img_size[0], "h": img_size[1]},
        "K1": K1.flatten().tolist(),
        "D1": D1.flatten().tolist(),
        "K2": K2.flatten().tolist(),
        "D2": D2.flatten().tolist(),
        "R": R.flatten().tolist(),
        "T": T.flatten().tolist(),
        "E": E.flatten().tolist(),
        "F": F.flatten().tolist(),
        "R1": R1.flatten().tolist(), "R2": R2.flatten().tolist(),
        "P1": P1.flatten().tolist(), "P2": P2.flatten().tolist(),
        "Q": Q.flatten().tolist(),
        "rectify_roi1": list(map(int, roi1)), "rectify_roi2": list(map(int, roi2)),
        "stereo_rms": float(ret),
        "vertical_error_stats": {"mean": vmean, "median": vmed, "max": vmax},
        "square_size_unit_hint": "All translations (T) are in units of SQUARE_SIZE."
    }
    save_yaml(Path(OUTPUT_DIR) / "stereo_params.yaml", payload)
    print(f"[Save] Parameters written to: {Path(OUTPUT_DIR, 'stereo_params.yaml').resolve()}")

    # Visualization output
    if SAVE_VIS:
        # 1) Corner visualization
        corners_dir = Path(OUTPUT_DIR) / "corners_pair"
        corners_dir.mkdir(parents=True, exist_ok=True)
        for nameL, vL, nameR, vR in vis_pairs:
            cv2.imencode(".jpg", vL)[1].tofile(str(corners_dir / f"L_{nameL}"))
            cv2.imencode(".jpg", vR)[1].tofile(str(corners_dir / f"R_{nameR}"))

        # 2) Rectified left and right images side by side + horizontal epipolar lines
        rect_dir = Path(OUTPUT_DIR) / "rectified_pairs"
        rect_dir.mkdir(parents=True, exist_ok=True)
        for idx, (fL, fR) in enumerate(used_pairs[:MAX_PAIR_VIS]):
            imgL = cv2.imdecode(np.fromfile(fL, dtype=np.uint8), cv2.IMREAD_COLOR)
            imgR = cv2.imdecode(np.fromfile(fR, dtype=np.uint8), cv2.IMREAD_COLOR)
            rL = cv2.remap(imgL, map1x, map1y, cv2.INTER_LINEAR)
            rR = cv2.remap(imgR, map2x, map2y, cv2.INTER_LINEAR)
            H = max(rL.shape[0], rR.shape[0])
            canvas = np.hstack([rL, rR])
            # Draw several horizontal reference lines
            lines = 10
            step = H // (lines+1)
            for k in range(1, lines+1):
                y = k * step
                cv2.line(canvas, (0, y), (canvas.shape[1]-1, y), (0, 255, 0), 1)
            outp = rect_dir / f"rectified_{idx:02d}.jpg"
            cv2.imencode(".jpg", canvas)[1].tofile(str(outp))

        # 3) Epipolar line demonstration on original images (select 4 pairs)
        epi_dir = Path(OUTPUT_DIR) / "epipolar_demo"
        epi_dir.mkdir(parents=True, exist_ok=True)
        demo_pairs = used_pairs[:min(4, len(used_pairs))]
        for (fL, fR), pl, pr in zip(demo_pairs, imgpoints_l[:len(demo_pairs)], imgpoints_r[:len(demo_pairs)]):
            imgL = cv2.imdecode(np.fromfile(fL, dtype=np.uint8), cv2.IMREAD_COLOR)
            imgR = cv2.imdecode(np.fromfile(fR, dtype=np.uint8), cv2.IMREAD_COLOR)
            # Use F to draw epipolar lines on right image
            ptsL = pl.reshape(-1,1,2)
            linesR = cv2.computeCorrespondEpilines(ptsL, 1, F).reshape(-1,3)  # 1 means points from left image
            for r in linesR[::max(1, len(linesR)//20)]:  # Sample drawing lines
                a,b,c = r
                x0, y0 = 0, int(-c/b) if abs(b)>1e-6 else 0
                x1, y1 = imgR.shape[1], int(-(c+a*imgR.shape[1])/b) if abs(b)>1e-6 else imgR.shape[0]-1
                cv2.line(imgR, (x0,y0), (x1,y1), (0,255,0), 1)
            outL = epi_dir / ("L_" + Path(fL).name)
            outR = epi_dir / ("R_" + Path(fR).name)
            cv2.imencode(".jpg", imgL)[1].tofile(str(outL))
            cv2.imencode(".jpg", imgR)[1].tofile(str(outR))

    print("\n=== Completed. Check output directory:", Path(OUTPUT_DIR).resolve())
    print("Suggestion: Observe if rows in left and right images in rectified_pairs/ are aligned; smaller vertical_error_stats is better.")

if __name__ == "__main__":
    main()
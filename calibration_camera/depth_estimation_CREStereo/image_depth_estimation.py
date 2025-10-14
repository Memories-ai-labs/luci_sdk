import cv2
import numpy as np
#from imread_from_url import imread_from_url

from crestereo import CREStereo

# Model Selection options (not all options supported together)
iters = 10            # Lower iterations are faster, but will lower detail.
		             # Options: 2, 5, 10, 20 

shape = (720, 1280)   # Input resolution.
				     # Options: (240,320), (320,480), (380, 480), (360, 640), (480,640), (720, 1280)

version = "combined" # The combined version does 2 passes, one to get an initial estimation and a second one to refine it.
					 # Options: "init", "combined"

# Initialize model
model_path = f'models/crestereo_init_iter10_480x640.onnx'
depth_estimator = CREStereo(model_path)

# Load images ---test
left_img = cv2.imread('C:/Users/vq24975/OneDrive - University of Bristol/Desktop/luci_sdk/test_images/cam1_2025-09-23_14-56-16.jpg')
right_img = cv2.imread('C:/Users/vq24975/OneDrive - University of Bristol/Desktop/luci_sdk/test_images/cam2_2025-09-23_14-56-16.jpg')

'''
# Load images --- calibration
left_img = cv2.imread('C:/Users/vq24975/OneDrive - University of Bristol/Desktop/luci_sdk/calibration_images_9.23/cam1_2025-09-22_19-59-57.jpg')
right_img = cv2.imread('C:/Users/vq24975/OneDrive - University of Bristol/Desktop/luci_sdk/calibration_images_9.23/cam2_2025-09-22_19-59-57.jpg')
'''
# Estimate the depth
disparity_map = depth_estimator(left_img, right_img)

color_disparity = depth_estimator.draw_disparity()
combined_image = np.hstack((left_img, color_disparity))

cv2.imwrite("out_test.jpg", combined_image)

cv2.namedWindow("Estimated disparity", cv2.WINDOW_NORMAL)	
cv2.imshow("Estimated disparity", combined_image)
cv2.waitKey(0)

cv2.destroyAllWindows()

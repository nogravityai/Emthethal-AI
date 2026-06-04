import sys
import traceback
import numpy as np
from PIL import Image

try:
    print("Importing paddle...")
    import paddle
    
    print("Monkey-patching AnalysisConfig...")
    # Monkey-patch set_optimization_level on AnalysisConfig
    try:
        paddle.base.libpaddle.AnalysisConfig.set_optimization_level = lambda self, level: None
        print("Patched paddle.base.libpaddle.AnalysisConfig")
    except AttributeError:
        pass
    
    try:
        import paddle.fluid.core as core
        core.AnalysisConfig.set_optimization_level = lambda self, level: None
        print("Patched paddle.fluid.core.AnalysisConfig")
    except (AttributeError, ImportError):
        pass

    print("Importing PaddleOCR...")
    from paddleocr import PaddleOCR
    
    print("Initializing PaddleOCR with local model paths...")
    ocr = PaddleOCR(
        lang='ar',
        det_model_dir='/root/.paddleocr/whl/det/ml/Multilingual_PP-OCRv3_det_infer',
        rec_model_dir='/root/.paddleocr/whl/rec/arabic/arabic_PP-OCRv4_rec_infer',
        cls_model_dir='/root/.paddleocr/whl/cls/ch_ppocr_mobile_v2.0_cls_infer',
        use_angle_cls=False,
        use_gpu=False,
        enable_mkldnn=False,
    )
    print("PaddleOCR initialization SUCCESS!")
    
    print("Creating dummy image to test OCR inference...")
    # Create a 300x100 white image
    image = Image.new('RGB', (300, 100), color=(255, 255, 255))
    img_array = np.array(image)
    
    print("Running OCR inference...")
    result = ocr.ocr(img_array, cls=False)
    print("OCR inference SUCCESS! Result:", result)

except Exception as e:
    traceback.print_exc()
    sys.exit(1)

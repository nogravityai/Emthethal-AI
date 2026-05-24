/**
 * Coordinate Transform Registry
 * 
 * Central registry for coordinate conversions across CFIS workbench:
 * - DPI scaling adjustments
 * - PDF -> Image coordinates translations
 * - Canvas/Viewport display scaling
 * - Replay/Normalized coordinate mapping
 */

export class CoordinateTransformRegistry {
  constructor(pageWidth = 1000, pageHeight = 1000, pdfDpi = 72, targetDpi = 150) {
    this.pageWidth = pageWidth;
    this.pageHeight = pageHeight;
    this.pdfDpi = pdfDpi;
    this.targetDpi = targetDpi;
    
    // Default calibration values if matching a chart
    this.calibration = null;
  }

  updatePageDimensions(width, height) {
    this.pageWidth = width;
    this.pageHeight = height;
  }

  updateDpi(pdfDpi, targetDpi) {
    this.pdfDpi = pdfDpi;
    this.targetDpi = targetDpi;
  }

  setChartCalibration(calibration) {
    this.calibration = calibration;
  }

  /** Convert PDF Points (72 DPI) to Image Pixels (e.g. 150 DPI) */
  pdfToPixels(val) {
    return val * (this.targetDpi / this.pdfDpi);
  }

  /** Convert Image Pixels to PDF Points */
  pixelsToPdf(val) {
    return val * (this.pdfDpi / this.targetDpi);
  }

  /** Map page pixels to canvas coordinates based on viewport width */
  pageToCanvas(x, y, canvasWidth, canvasHeight) {
    const scaleX = canvasWidth / this.pageWidth;
    const scaleY = canvasHeight / this.pageHeight;
    return {
      x: x * scaleX,
      y: y * scaleY
    };
  }

  /** Map canvas coordinates back to page pixels */
  canvasToPage(x, y, canvasWidth, canvasHeight) {
    const scaleX = this.pageWidth / canvasWidth;
    const scaleY = this.pageHeight / canvasHeight;
    return {
      x: x * scaleX,
      y: y * scaleY
    };
  }

  /** Convert page pixel coordinate to real chart values (if calibrated) */
  pixelToReal(x, y) {
    if (!this.calibration) {
      // Fallback: simple normalized 0-1 coordinate space
      return {
        x: x / this.pageWidth,
        y: 1.0 - (y / this.pageHeight) // Inverted Y is standard in plots
      };
    }

    const { x_axis, y_axis } = this.calibration;
    let rx = 0;
    let ry = 0;

    // X Axis
    if (x_axis.scale_type === 'linear') {
      const pct = (x - x_axis.min_pixel) / (x_axis.max_pixel - x_axis.min_pixel);
      rx = x_axis.min_value + pct * (x_axis.max_value - x_axis.min_value);
    }

    // Y Axis
    if (y_axis.scale_type === 'linear') {
      const pct = (y - y_axis.min_pixel) / (y_axis.max_pixel - y_axis.min_pixel);
      ry = y_axis.min_value + pct * (y_axis.max_value - y_axis.min_value);
    }

    return { x: rx, y: ry };
  }

  /** Convert real values back to page pixels */
  realToPixel(rx, ry) {
    if (!this.calibration) {
      return {
        x: rx * this.pageWidth,
        y: (1.0 - ry) * this.pageHeight
      };
    }

    const { x_axis, y_axis } = this.calibration;
    let px = 0;
    let py = 0;

    if (x_axis.scale_type === 'linear') {
      const pct = (rx - x_axis.min_value) / (x_axis.max_value - x_axis.min_value);
      px = x_axis.min_pixel + pct * (x_axis.max_pixel - x_axis.min_pixel);
    }

    if (y_axis.scale_type === 'linear') {
      const pct = (ry - y_axis.min_value) / (y_axis.max_value - y_axis.min_value);
      py = y_axis.min_pixel + pct * (y_axis.max_pixel - y_axis.min_pixel);
    }

    return { x: px, y: py };
  }
}

export const globalCoordinateRegistry = new CoordinateTransformRegistry();

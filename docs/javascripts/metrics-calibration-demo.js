(function () {
  "use strict";

  const WIDTH = 792;
  const HEIGHT = 612;
  const SAMPLE_SCALE = [[150, 105], [430, 105]];
  const SAMPLE_ROI = [[175, 188], [620, 170], [690, 455], [565, 525], [230, 505]];
  const MASK_POLYGON = [
    [82, 362], [135, 286], [222, 226], [330, 198], [454, 205],
    [575, 244], [680, 320], [735, 405], [680, 482], [555, 526],
    [415, 530], [276, 496], [158, 438],
  ];
  const SAMPLE_STEP = 4;

  let nextDemoId = 0;

  function element(tagName, className, text) {
    const node = document.createElement(tagName);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function clonePoints(points) {
    return points.map((point) => [point[0], point[1]]);
  }

  function distance(a, b) {
    return Math.hypot(b[0] - a[0], b[1] - a[1]);
  }

  function pointInPolygon(x, y, polygon) {
    let inside = false;
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i, i += 1) {
      const xi = polygon[i][0];
      const yi = polygon[i][1];
      const xj = polygon[j][0];
      const yj = polygon[j][1];
      const crosses = ((yi > y) !== (yj > y))
        && (x < ((xj - xi) * (y - yi)) / (yj - yi) + xi);
      if (crosses) inside = !inside;
    }
    return inside;
  }

  function sampleAreas(roiPoints, applyRoi) {
    let fullFrame = 0;
    let mask = 0;
    let roi = 0;
    let selectedMask = 0;
    for (let y = SAMPLE_STEP / 2; y < HEIGHT; y += SAMPLE_STEP) {
      for (let x = SAMPLE_STEP / 2; x < WIDTH; x += SAMPLE_STEP) {
        const pixels = SAMPLE_STEP * SAMPLE_STEP;
        const inMask = pointInPolygon(x, y, MASK_POLYGON);
        const inRoi = !applyRoi || pointInPolygon(x, y, roiPoints);
        fullFrame += pixels;
        if (inMask) mask += pixels;
        if (inRoi) roi += pixels;
        if (inMask && inRoi) selectedMask += pixels;
      }
    }
    return {fullFrame, mask, roi, selectedMask};
  }

  function svgPath(points, close) {
    if (!points.length) return "";
    return `M ${points.map((point) => `${point[0]} ${point[1]}`).join(" L ")}${close ? " Z" : ""}`;
  }

  function createNumberField(id, labelText, value, min, max, step) {
    const field = element("label", "swell-metrics-demo__field");
    field.htmlFor = id;
    field.append(element("span", "", labelText));
    const input = document.createElement("input");
    input.id = id;
    input.type = "number";
    input.value = String(value);
    input.min = String(min);
    input.max = String(max);
    input.step = String(step);
    field.append(input);
    return {field, input};
  }

  class MetricsCalibrationDemo {
    constructor(root) {
      this.root = root;
      this.id = `swell-metrics-demo-${nextDemoId += 1}`;
      this.image = new Image();
      this.imageReady = false;
      this.scalePoints = clonePoints(SAMPLE_SCALE);
      this.roiPoints = clonePoints(SAMPLE_ROI);
      this.roiClosed = true;
      this.mode = "inspect";
      this.drag = null;
      this.selectedHandle = {kind: "scale", index: 1};
    }

    initialize() {
      this.root.replaceChildren();
      this.build();
      const source = this.root.dataset.svgSrc;
      if (source) {
        this.image.addEventListener("load", () => {
          this.imageReady = true;
          this.render();
        }, {once: true});
        this.image.addEventListener("error", () => this.render(), {once: true});
        this.image.src = source;
      }
      this.render();
      this.announce("Calibration exercise ready. Drag the line or ROI handles, or redraw either measurement.");
    }

    build() {
      const shell = element("section", "swell-metrics-demo__shell");
      shell.setAttribute("aria-label", "ROI and physical-scale calibration exercise");

      const heading = element("div", "swell-metrics-demo__heading");
      heading.append(
        element("strong", "", "Calibrate first, then constrain the measurement"),
        element("span", "", "The exercise uses event-local settings and simulated mask geometry.")
      );
      shell.append(heading);

      const body = element("div", "swell-metrics-demo__body");
      const viewer = element("div", "swell-metrics-demo__viewer");
      this.canvas = document.createElement("canvas");
      this.canvas.className = "swell-metrics-demo__canvas";
      this.canvas.width = WIDTH;
      this.canvas.height = HEIGHT;
      this.canvas.tabIndex = 0;
      this.canvas.setAttribute("role", "img");
      this.canvas.setAttribute("aria-label", "Example image with calibration line, segmented mask, and ROI polygon");
      this.canvas.addEventListener("pointerdown", (event) => this.onPointerDown(event));
      this.canvas.addEventListener("pointermove", (event) => this.onPointerMove(event));
      this.canvas.addEventListener("pointerup", (event) => this.onPointerUp(event));
      this.canvas.addEventListener("pointercancel", (event) => this.onPointerUp(event));
      this.canvas.addEventListener("keydown", (event) => this.onKeydown(event));
      viewer.append(this.canvas);

      this.instruction = element("p", "swell-metrics-demo__instruction", "");
      viewer.append(this.instruction);

      const toolbar = element("div", "swell-metrics-demo__toolbar");
      this.scaleButton = this.makeButton("Redraw scale line", () => this.redrawScale());
      this.roiButton = this.makeButton("Redraw ROI", () => this.redrawRoi());
      this.closeButton = this.makeButton("Close ROI", () => this.closeRoi());
      this.restoreButton = this.makeButton("Restore sample", () => this.restoreSample());
      toolbar.append(this.scaleButton, this.roiButton, this.closeButton, this.restoreButton);
      viewer.append(toolbar);

      const panel = element("div", "swell-metrics-demo__panel");
      panel.append(element("span", "swell-metrics-demo__eyebrow", "Measurement inputs"));

      const controls = element("div", "swell-metrics-demo__controls");
      const lengthField = createNumberField(`${this.id}-length`, "Known length (mm)", 2, 0.001, 1000, 0.1);
      this.lengthInput = lengthField.input;
      const fpsField = createNumberField(`${this.id}-fps`, "Frames per second (FPS)", 2, 0.001, 10000, 0.1);
      this.fpsInput = fpsField.input;
      controls.append(lengthField.field, fpsField.field);

      const shiftField = element("label", "swell-metrics-demo__field swell-metrics-demo__field--wide");
      shiftField.htmlFor = `${this.id}-shift`;
      const shiftHeading = element("span", "swell-metrics-demo__field-heading");
      shiftHeading.append(document.createTextNode("Example boundary shift"));
      this.shiftOutput = element("output", "", "6 px/frame");
      this.shiftOutput.htmlFor = `${this.id}-shift`;
      shiftHeading.append(this.shiftOutput);
      this.shiftInput = document.createElement("input");
      this.shiftInput.id = `${this.id}-shift`;
      this.shiftInput.type = "range";
      this.shiftInput.min = "1";
      this.shiftInput.max = "20";
      this.shiftInput.step = "1";
      this.shiftInput.value = "6";
      shiftField.append(shiftHeading, this.shiftInput);
      controls.append(shiftField);

      const roiToggle = element("label", "swell-metrics-demo__toggle");
      this.applyRoiInput = document.createElement("input");
      this.applyRoiInput.type = "checkbox";
      this.applyRoiInput.checked = true;
      this.applyRoiInput.setAttribute("aria-label", "Apply ROI to example mask");
      roiToggle.append(this.applyRoiInput, document.createTextNode("Apply ROI to example mask"));
      controls.append(roiToggle);
      panel.append(controls);

      [this.lengthInput, this.fpsInput, this.shiftInput, this.applyRoiInput].forEach((input) => {
        input.addEventListener("input", () => this.render());
        input.addEventListener("change", () => this.render());
      });

      panel.append(element("span", "swell-metrics-demo__eyebrow", "Live metric preview"));
      this.results = element("div", "swell-metrics-demo__results");
      this.metricNodes = {};
      [
        ["line", "Calibration line"],
        ["scale", "Physical scale"],
        ["sampling", "Pixel size"],
        ["roi", "Measurement scope"],
        ["area", "Selected mask area"],
        ["fill", "ROI fill"],
        ["speed", "Propagation speed"],
      ].forEach(([key, label]) => {
        const card = element("div", "swell-metrics-demo__result");
        card.append(element("span", "", label));
        const output = element("strong", "", "—");
        output.dataset.metric = key;
        card.append(output);
        this.results.append(card);
        this.metricNodes[key] = output;
      });
      panel.append(this.results);

      this.formula = element("p", "swell-metrics-demo__formula", "");
      panel.append(this.formula);

      body.append(viewer, panel);
      shell.append(body);

      this.status = element("p", "swell-metrics-demo__sr-status", "");
      this.status.setAttribute("aria-live", "polite");
      shell.append(this.status);
      this.root.append(shell);
    }

    makeButton(label, handler) {
      const button = element("button", "swell-metrics-demo__button", label);
      button.type = "button";
      button.addEventListener("click", handler);
      return button;
    }

    values() {
      const knownLength = Number.parseFloat(this.lengthInput.value);
      const fps = Number.parseFloat(this.fpsInput.value);
      const shift = Number.parseFloat(this.shiftInput.value);
      const linePixels = this.scalePoints.length === 2 ? distance(this.scalePoints[0], this.scalePoints[1]) : NaN;
      const scale = Number.isFinite(knownLength) && knownLength > 0 && Number.isFinite(linePixels)
        ? linePixels / knownLength
        : NaN;
      return {knownLength, fps, shift, linePixels, scale};
    }

    render() {
      this.drawCanvas();
      const value = this.values();
      const applyRoi = this.applyRoiInput.checked && this.roiClosed && this.roiPoints.length >= 3;
      const areas = sampleAreas(this.roiPoints, applyRoi);
      const validScale = Number.isFinite(value.scale) && value.scale > 0;
      const validFps = Number.isFinite(value.fps) && value.fps > 0;
      const validShift = Number.isFinite(value.shift) && value.shift >= 0;
      const mmPerPx = validScale ? 1 / value.scale : NaN;
      const umPerPx = validScale ? 1000 / value.scale : NaN;
      const areaMm2 = validScale ? areas.selectedMask * (mmPerPx ** 2) : NaN;
      const speed = validScale && validFps && validShift ? value.shift * umPerPx * value.fps : NaN;
      const fill = areas.roi > 0 ? (areas.selectedMask / areas.roi) * 100 : NaN;

      this.shiftOutput.textContent = `${Number.isFinite(value.shift) ? value.shift.toFixed(0) : "—"} px/frame`;
      this.metricNodes.line.textContent = Number.isFinite(value.linePixels) ? `${value.linePixels.toFixed(1)} px` : "Draw two points";
      this.metricNodes.scale.textContent = validScale ? `${value.scale.toFixed(2)} px/mm` : "Enter a valid line and length";
      this.metricNodes.sampling.textContent = validScale ? `${umPerPx.toFixed(2)} μm/px` : "—";
      this.metricNodes.roi.textContent = applyRoi ? `${Math.round(areas.roi).toLocaleString()} ROI px` : `${Math.round(areas.fullFrame).toLocaleString()} full-frame px`;
      this.metricNodes.area.textContent = validScale ? `${areaMm2.toFixed(4)} mm² (${Math.round(areas.selectedMask).toLocaleString()} px)` : `${Math.round(areas.selectedMask).toLocaleString()} px`;
      this.metricNodes.fill.textContent = applyRoi && Number.isFinite(fill) ? `${fill.toFixed(1)}%` : "ROI not applied";
      this.metricNodes.speed.textContent = Number.isFinite(speed) ? `${speed.toFixed(1)} μm/s` : "Enter valid scale and FPS";
      this.formula.textContent = validScale
        ? `Area = pixels ÷ ${value.scale.toFixed(2)}². Speed = ${value.shift.toFixed(0)} px/frame × ${umPerPx.toFixed(2)} μm/px × ${validFps ? value.fps.toFixed(1) : "FPS"} FPS.`
        : "Draw a two-point line and enter its known physical length to unlock physical units.";
      this.updateInstruction();
      this.closeButton.disabled = this.roiClosed || this.roiPoints.length < 3;
      this.scaleButton.classList.toggle("is-active", this.mode === "scale");
      this.roiButton.classList.toggle("is-active", this.mode === "roi");
      this.canvas.setAttribute(
        "aria-label",
        `Example measurement image. ${this.scalePoints.length === 2 ? `Calibration line ${value.linePixels.toFixed(1)} pixels.` : `${this.scalePoints.length} of 2 scale points placed.`} ${this.roiClosed ? `Closed ROI with ${this.roiPoints.length} vertices.` : `Open ROI with ${this.roiPoints.length} vertices.`}`
      );
    }

    updateInstruction() {
      if (this.mode === "scale") {
        this.instruction.textContent = `Scale mode: click ${2 - this.scalePoints.length} more point${this.scalePoints.length === 1 ? "" : "s"}. The line completes after the second point.`;
      } else if (this.mode === "roi") {
        this.instruction.textContent = "ROI mode: click at least three vertices, then choose Close ROI. Closed vertices remain draggable.";
      } else {
        this.instruction.textContent = "Drag a line endpoint or ROI vertex to change the measurement. Focus the image and use arrow keys to nudge the selected handle.";
      }
    }

    drawCanvas() {
      const ctx = this.canvas.getContext("2d");
      ctx.clearRect(0, 0, WIDTH, HEIGHT);
      if (this.imageReady) {
        ctx.drawImage(this.image, 0, 0, WIDTH, HEIGHT);
      } else {
        const gradient = ctx.createLinearGradient(0, 0, WIDTH, HEIGHT);
        gradient.addColorStop(0, "#252c34");
        gradient.addColorStop(1, "#10151b");
        ctx.fillStyle = gradient;
        ctx.fillRect(0, 0, WIDTH, HEIGHT);
      }

      ctx.save();
      ctx.fillStyle = "rgba(244, 194, 72, 0.46)";
      ctx.strokeStyle = "rgba(255, 223, 132, 0.95)";
      ctx.lineWidth = 3;
      this.tracePolygon(ctx, MASK_POLYGON, true);
      ctx.fill();
      ctx.stroke();
      ctx.restore();

      if (this.applyRoiInput.checked && this.roiClosed && this.roiPoints.length >= 3) {
        const shade = new Path2D();
        shade.rect(0, 0, WIDTH, HEIGHT);
        shade.addPath(new Path2D(svgPath(this.roiPoints, true)));
        ctx.fillStyle = "rgba(4, 8, 13, 0.58)";
        ctx.fill(shade, "evenodd");
      }

      if (this.roiPoints.length) {
        ctx.save();
        ctx.strokeStyle = "#63d2ff";
        ctx.fillStyle = "rgba(47, 174, 226, 0.12)";
        ctx.lineWidth = 4;
        ctx.setLineDash(this.roiClosed ? [] : [10, 7]);
        this.tracePolygon(ctx, this.roiPoints, this.roiClosed);
        if (this.roiClosed) ctx.fill();
        ctx.stroke();
        ctx.setLineDash([]);
        this.drawHandles(ctx, this.roiPoints, "#63d2ff", "roi");
        ctx.restore();
      }

      if (this.scalePoints.length) {
        ctx.save();
        ctx.strokeStyle = "#b38cff";
        ctx.fillStyle = "#b38cff";
        ctx.lineWidth = 6;
        ctx.setLineDash(this.scalePoints.length === 2 ? [] : [10, 7]);
        if (this.scalePoints.length === 2) {
          ctx.beginPath();
          ctx.moveTo(this.scalePoints[0][0], this.scalePoints[0][1]);
          ctx.lineTo(this.scalePoints[1][0], this.scalePoints[1][1]);
          ctx.stroke();
        }
        ctx.setLineDash([]);
        this.drawHandles(ctx, this.scalePoints, "#b38cff", "scale");
        if (this.scalePoints.length === 2) {
          const midpoint = [(this.scalePoints[0][0] + this.scalePoints[1][0]) / 2, (this.scalePoints[0][1] + this.scalePoints[1][1]) / 2];
          const pixels = distance(this.scalePoints[0], this.scalePoints[1]);
          ctx.font = "700 22px system-ui, sans-serif";
          ctx.textAlign = "center";
          ctx.fillStyle = "#f5efff";
          ctx.fillText(`${pixels.toFixed(1)} px`, midpoint[0], midpoint[1] - 16);
        }
        ctx.restore();
      }

      ctx.save();
      ctx.fillStyle = "rgba(10, 15, 20, 0.82)";
      ctx.fillRect(14, HEIGHT - 52, 380, 38);
      ctx.font = "700 17px system-ui, sans-serif";
      ctx.textAlign = "left";
      ctx.fillStyle = "#f5c248";
      ctx.fillText("yellow: example mask", 26, HEIGHT - 27);
      ctx.fillStyle = "#63d2ff";
      ctx.fillText("blue: ROI", 228, HEIGHT - 27);
      ctx.restore();
    }

    tracePolygon(ctx, points, close) {
      if (!points.length) return;
      ctx.beginPath();
      ctx.moveTo(points[0][0], points[0][1]);
      points.slice(1).forEach((point) => ctx.lineTo(point[0], point[1]));
      if (close) ctx.closePath();
    }

    drawHandles(ctx, points, color, kind) {
      points.forEach((point, index) => {
        const selected = this.selectedHandle && this.selectedHandle.kind === kind && this.selectedHandle.index === index;
        ctx.beginPath();
        ctx.arc(point[0], point[1], selected ? 11 : 8, 0, Math.PI * 2);
        ctx.fillStyle = selected ? "#ffffff" : color;
        ctx.fill();
        ctx.strokeStyle = "#10151b";
        ctx.lineWidth = 3;
        ctx.stroke();
      });
    }

    canvasPoint(event) {
      const rect = this.canvas.getBoundingClientRect();
      return [
        Math.max(0, Math.min(WIDTH, ((event.clientX - rect.left) / rect.width) * WIDTH)),
        Math.max(0, Math.min(HEIGHT, ((event.clientY - rect.top) / rect.height) * HEIGHT)),
      ];
    }

    nearestHandle(point) {
      let nearest = null;
      let best = 22;
      [["scale", this.scalePoints], ["roi", this.roiPoints]].forEach(([kind, points]) => {
        points.forEach((candidate, index) => {
          const current = distance(point, candidate);
          if (current < best) {
            best = current;
            nearest = {kind, index};
          }
        });
      });
      return nearest;
    }

    onPointerDown(event) {
      const point = this.canvasPoint(event);
      const handle = this.nearestHandle(point);
      if (handle && this.mode === "inspect") {
        this.drag = handle;
        this.selectedHandle = handle;
        this.canvas.setPointerCapture(event.pointerId);
      } else if (this.mode === "scale") {
        if (this.scalePoints.length < 2) this.scalePoints.push(point);
        this.selectedHandle = {kind: "scale", index: this.scalePoints.length - 1};
        if (this.scalePoints.length === 2) {
          this.mode = "inspect";
          this.announce("Scale line complete. Enter the known physical length or drag either endpoint.");
        }
      } else if (this.mode === "roi" && !this.roiClosed) {
        this.roiPoints.push(point);
        this.selectedHandle = {kind: "roi", index: this.roiPoints.length - 1};
        this.announce(`ROI vertex ${this.roiPoints.length} added.`);
      } else if (handle) {
        this.drag = handle;
        this.selectedHandle = handle;
        this.canvas.setPointerCapture(event.pointerId);
      }
      this.canvas.focus();
      this.render();
    }

    onPointerMove(event) {
      if (!this.drag) return;
      const point = this.canvasPoint(event);
      const points = this.drag.kind === "scale" ? this.scalePoints : this.roiPoints;
      points[this.drag.index] = point;
      this.render();
    }

    onPointerUp(event) {
      if (!this.drag) return;
      try {
        this.canvas.releasePointerCapture(event.pointerId);
      } catch (_error) {
        // The pointer may already have been released by the browser.
      }
      this.drag = null;
      this.announce("Measurement handle moved; metric preview updated.");
      this.render();
    }

    onKeydown(event) {
      if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
      const handle = this.selectedHandle || {kind: "scale", index: 0};
      const points = handle.kind === "scale" ? this.scalePoints : this.roiPoints;
      if (!points[handle.index]) return;
      event.preventDefault();
      const amount = event.shiftKey ? 10 : 2;
      const delta = {
        ArrowLeft: [-amount, 0],
        ArrowRight: [amount, 0],
        ArrowUp: [0, -amount],
        ArrowDown: [0, amount],
      }[event.key];
      points[handle.index][0] = Math.max(0, Math.min(WIDTH, points[handle.index][0] + delta[0]));
      points[handle.index][1] = Math.max(0, Math.min(HEIGHT, points[handle.index][1] + delta[1]));
      this.announce(`${handle.kind === "scale" ? "Scale endpoint" : "ROI vertex"} nudged; metric preview updated.`);
      this.render();
    }

    redrawScale() {
      this.scalePoints = [];
      this.mode = "scale";
      this.selectedHandle = null;
      this.announce("Scale line cleared. Click two points across a known distance.");
      this.render();
    }

    redrawRoi() {
      this.roiPoints = [];
      this.roiClosed = false;
      this.mode = "roi";
      this.selectedHandle = null;
      this.announce("ROI cleared. Click at least three polygon vertices, then close the ROI.");
      this.render();
    }

    closeRoi() {
      if (this.roiPoints.length < 3) return;
      this.roiClosed = true;
      this.mode = "inspect";
      this.applyRoiInput.checked = true;
      this.selectedHandle = {kind: "roi", index: this.roiPoints.length - 1};
      this.announce(`ROI closed with ${this.roiPoints.length} vertices; measurement preview updated.`);
      this.render();
    }

    restoreSample() {
      this.scalePoints = clonePoints(SAMPLE_SCALE);
      this.roiPoints = clonePoints(SAMPLE_ROI);
      this.roiClosed = true;
      this.mode = "inspect";
      this.selectedHandle = {kind: "scale", index: 1};
      this.lengthInput.value = "2";
      this.fpsInput.value = "2";
      this.shiftInput.value = "6";
      this.applyRoiInput.checked = true;
      this.announce("Sample calibration, ROI, FPS, and boundary shift restored.");
      this.render();
    }

    announce(message) {
      this.status.textContent = message;
    }
  }

  function mountMetricsCalibrationDemos() {
    document.querySelectorAll("[data-swell-metrics-calibration-demo]").forEach((root) => {
      if (root.dataset.swellMetricsCalibrationMounted === "true") return;
      root.dataset.swellMetricsCalibrationMounted = "true";
      try {
        const demo = new MetricsCalibrationDemo(root);
        root.swellMetricsCalibrationDemo = demo;
        demo.initialize();
      } catch (error) {
        root.replaceChildren(
          element("p", "swell-metrics-demo__fallback", `Calibration exercise unavailable: ${error.message}`)
        );
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mountMetricsCalibrationDemos, {once: true});
  } else {
    mountMetricsCalibrationDemos();
  }
  if (typeof document$ !== "undefined") document$.subscribe(mountMetricsCalibrationDemos);
}());

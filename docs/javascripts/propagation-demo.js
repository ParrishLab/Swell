(function () {
  "use strict";

  const VIEW_WIDTH = 792;
  const VIEW_HEIGHT = 612;
  const MASK_WIDTH = 396;
  const MASK_HEIGHT = 306;
  const MASK_SCALE = MASK_WIDTH / VIEW_WIDTH;
  const MASK_BLUE = [27, 117, 188];
  const SEQUENCE_MASK_SCALE = 1.16;
  const SEQUENCE_FILES = ["002122", "002123", "002124", "002125", "002126", "002127", "002128"];
  const FRAME_COUNT = SEQUENCE_FILES.length;
  const DRIFT_START = 3; // zero-based: propagation drifts from frame 4 onward

  // Faithful to the desktop app (swell/analysis/core/render.py, overlay_renderer.py, theme.py).
  const GHOST_PAST = [0, 191, 255];
  const GHOST_FUTURE = [255, 0, 128];
  const ACCENT = "#1b75bc";
  const ANCHOR_PURPLE = "#b26bff";
  const TIMELINE_TRACK = "#1a2028";
  const PLAYHEAD = "#ffffff";
  const GHOST_RANGE_DEFAULT = 2;

  // matplotlib "RdYlGn" sampled at nine class stops (red -> yellow -> green).
  const RDYLGN = [
    [0.0, [165, 0, 38]],
    [0.25, [244, 109, 67]],
    [0.5, [255, 255, 191]],
    [0.75, [166, 217, 106]],
    [1.0, [0, 104, 55]],
  ];

  function clamp(value, low, high) {
    return Math.max(low, Math.min(high, value));
  }

  function countMask(mask) {
    let count = 0;
    for (let index = 0; index < mask.length; index += 1) count += mask[index];
    return count;
  }

  function combineMasks(left, right, operation) {
    const output = new Uint8Array(left.length);
    for (let index = 0; index < output.length; index += 1) {
      if (operation === "union") output[index] = left[index] || right[index] ? 1 : 0;
      if (operation === "subtract") output[index] = left[index] && !right[index] ? 1 : 0;
      if (operation === "intersect") output[index] = left[index] && right[index] ? 1 : 0;
    }
    return output;
  }

  function symmetricDifference(left, right) {
    let count = 0;
    for (let index = 0; index < left.length; index += 1) {
      if (Boolean(left[index]) !== Boolean(right[index])) count += 1;
    }
    return count;
  }

  function maskFromCanvas(canvas) {
    const context = canvas.getContext("2d", { willReadFrequently: true });
    const pixels = context.getImageData(0, 0, MASK_WIDTH, MASK_HEIGHT).data;
    const mask = new Uint8Array(MASK_WIDTH * MASK_HEIGHT);
    for (let index = 0; index < mask.length; index += 1) mask[index] = pixels[index * 4 + 3] > 0 ? 1 : 0;
    return mask;
  }

  function maskFromBinaryImage(image) {
    const canvas = document.createElement("canvas");
    canvas.width = MASK_WIDTH;
    canvas.height = MASK_HEIGHT;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    context.drawImage(image, 0, 0, MASK_WIDTH, MASK_HEIGHT);
    const pixels = context.getImageData(0, 0, MASK_WIDTH, MASK_HEIGHT).data;
    const mask = new Uint8Array(MASK_WIDTH * MASK_HEIGHT);
    for (let index = 0; index < mask.length; index += 1) mask[index] = pixels[index * 4] > 127 ? 1 : 0;
    return mask;
  }

  function scaleMaskAroundCentroid(mask, scale) {
    let totalX = 0;
    let totalY = 0;
    let count = 0;
    for (let y = 0; y < MASK_HEIGHT; y += 1) {
      for (let x = 0; x < MASK_WIDTH; x += 1) {
        if (!mask[y * MASK_WIDTH + x]) continue;
        totalX += x;
        totalY += y;
        count += 1;
      }
    }
    if (!count || scale === 1) return new Uint8Array(mask);
    const centerX = totalX / count;
    const centerY = totalY / count;
    const output = new Uint8Array(mask.length);
    for (let y = 0; y < MASK_HEIGHT; y += 1) {
      for (let x = 0; x < MASK_WIDTH; x += 1) {
        const sourceX = Math.round(centerX + (x - centerX) / scale);
        const sourceY = Math.round(centerY + (y - centerY) / scale);
        if (sourceX < 0 || sourceX >= MASK_WIDTH || sourceY < 0 || sourceY >= MASK_HEIGHT) continue;
        output[y * MASK_WIDTH + x] = mask[sourceY * MASK_WIDTH + sourceX];
      }
    }
    return output;
  }

  function translateMask(mask, offsetX, offsetY) {
    const output = new Uint8Array(mask.length);
    for (let y = 0; y < MASK_HEIGHT; y += 1) {
      for (let x = 0; x < MASK_WIDTH; x += 1) {
        const sourceX = x - offsetX;
        const sourceY = y - offsetY;
        if (sourceX < 0 || sourceX >= MASK_WIDTH || sourceY < 0 || sourceY >= MASK_HEIGHT) continue;
        output[y * MASK_WIDTH + x] = mask[sourceY * MASK_WIDTH + sourceX];
      }
    }
    return output;
  }

  function alignMaskToWhiteMatter(mask, whiteMatterMask) {
    for (let offsetY = 0; offsetY < MASK_HEIGHT; offsetY += 1) {
      const shifted = translateMask(mask, 0, offsetY);
      if (countMask(combineMasks(shifted, whiteMatterMask, "intersect"))) {
        return shifted;
      }
    }
    return new Uint8Array(mask);
  }

  // A growing slab of white matter, simulating propagation that over-segments
  // downward into the wrong tissue. Higher level -> deeper, larger spill.
  function whiteMatterSlab(whiteMatterMask, level) {
    const topRow = 148; // ~view y296, just below the cortical band
    const bottomRow = 165 + level * 20;
    const output = new Uint8Array(whiteMatterMask.length);
    for (let y = topRow; y <= bottomRow && y < MASK_HEIGHT; y += 1) {
      for (let x = 0; x < MASK_WIDTH; x += 1) {
        const index = y * MASK_WIDTH + x;
        if (whiteMatterMask[index]) output[index] = 1;
      }
    }
    return output;
  }

  function rasterizePath(pathData) {
    const canvas = document.createElement("canvas");
    canvas.width = MASK_WIDTH;
    canvas.height = MASK_HEIGHT;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    context.setTransform(MASK_SCALE, 0, 0, MASK_SCALE, 0, 0);
    context.fill(new Path2D(pathData));
    return maskFromCanvas(canvas);
  }

  function rasterizePolygon(points) {
    const canvas = document.createElement("canvas");
    canvas.width = MASK_WIDTH;
    canvas.height = MASK_HEIGHT;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    context.setTransform(MASK_SCALE, 0, 0, MASK_SCALE, 0, 0);
    context.beginPath();
    points.forEach((point, index) => {
      if (index === 0) context.moveTo(point.x, point.y);
      else context.lineTo(point.x, point.y);
    });
    context.closePath();
    context.fill();
    return maskFromCanvas(canvas);
  }

  // Centroid snapped to the nearest set pixel, so the point always lands inside the
  // region even when it is non-convex (white matter wraps the ventricle).
  function representativePoint(mask) {
    let totalX = 0;
    let totalY = 0;
    let count = 0;
    for (let y = 0; y < MASK_HEIGHT; y += 1) {
      for (let x = 0; x < MASK_WIDTH; x += 1) {
        if (!mask[y * MASK_WIDTH + x]) continue;
        totalX += x;
        totalY += y;
        count += 1;
      }
    }
    if (!count) return { x: VIEW_WIDTH / 2, y: VIEW_HEIGHT / 2 };
    const centerX = totalX / count;
    const centerY = totalY / count;
    let best = Infinity;
    let bestX = centerX;
    let bestY = centerY;
    for (let y = 0; y < MASK_HEIGHT; y += 1) {
      for (let x = 0; x < MASK_WIDTH; x += 1) {
        if (!mask[y * MASK_WIDTH + x]) continue;
        const distance = (x - centerX) ** 2 + (y - centerY) ** 2;
        if (distance < best) {
          best = distance;
          bestX = x;
          bestY = y;
        }
      }
    }
    return { x: bestX / MASK_SCALE, y: bestY / MASK_SCALE };
  }

  function filledPathNodes(documentNode) {
    const nonFilledClasses = new Set();
    documentNode.querySelectorAll("style").forEach((style) => {
      const matches = style.textContent.matchAll(/\.([-\w]+)\s*\{[^}]*\bfill\s*:\s*none\b[^}]*\}/gi);
      for (const match of matches) nonFilledClasses.add(match[1]);
    });
    return Array.from(documentNode.querySelectorAll("path[d]")).filter((node) => {
      const classes = String(node.getAttribute("class") || "").split(/\s+/);
      return !classes.some((className) => nonFilledClasses.has(className));
    });
  }

  function lerpColor(a, b, t) {
    return [
      Math.round(a[0] + (b[0] - a[0]) * t),
      Math.round(a[1] + (b[1] - a[1]) * t),
      Math.round(a[2] + (b[2] - a[2]) * t),
    ];
  }

  function rgb(triple) {
    return `rgb(${triple[0]}, ${triple[1]}, ${triple[2]})`;
  }

  // High leverage -> red ("edit here"); low -> green ("settled"). Mirrors _leverage_hex.
  function leverageColor(norm) {
    const t = 1 - clamp(norm, 0, 1);
    for (let index = 0; index < RDYLGN.length - 1; index += 1) {
      const [lowStop, lowColor] = RDYLGN[index];
      const [highStop, highColor] = RDYLGN[index + 1];
      if (t <= highStop) {
        const span = highStop - lowStop || 1;
        return rgb(lerpColor(lowColor, highColor, (t - lowStop) / span));
      }
    }
    return rgb(RDYLGN[RDYLGN.length - 1][1]);
  }

  const PART_COPY = {
    propagate: {
      aria: "Propagation-from-anchor viewer",
      ready: "Anchor placed on frame 1. Press Run Propagation to carry the mask across the range.",
    },
    ghosts: {
      aria: "Ghost-outline review viewer",
      ready: "Scrub the frames, then enable Ghost Outlines to compare each mask with its neighbors.",
    },
    leverage: {
      aria: "Leverage-heatmap review viewer",
      ready: "Read the leverage heatmap below, then jump to the frame that needs a correction.",
    },
  };

  class PropagationDemo {
    constructor(root) {
      this.root = root;
      this.part = root.dataset.swellPropagationDemo || "propagate";
      this.frame = 0;
      this.cleanMasks = [];
      this.driftMasks = [];
      this.displayMasks = [];
      this.anchors = new Set([0]);
      this.correctionFrames = new Set();
      this.greenPoint = null;
      this.redPoint = null;
      this.sourceImage = null;
      this.ghostsEnabled = false;
      this.ghostRange = GHOST_RANGE_DEFAULT;
      this.heatmapVisible = true;
      this.propagating = false;
      this.hasRun = false;
      this.animTimer = null;
    }

    async initialize() {
      this.buildInterface();
      const svgUrl = new URL(this.root.dataset.svgSrc, window.location.href);
      const response = await fetch(svgUrl);
      if (!response.ok) throw new Error(`Unable to load slice SVG (${response.status}).`);
      const svgText = await response.text();
      const documentNode = new DOMParser().parseFromString(svgText, "image/svg+xml");
      if (documentNode.querySelector("parsererror")) throw new Error("Unable to parse slice SVG.");
      await this.loadSourceImage(svgText);
      this.prepareBaseMask(documentNode);
      await this.loadSequence();
      // Positions for the simulated manual point prompts: a positive point on the
      // cortical target, and a negative point inside the drift spill the mask must avoid.
      const spillRegion = combineMasks(this.driftMasks[FRAME_COUNT - 1], this.cleanMasks[FRAME_COUNT - 1], "subtract");
      this.greenPoint = representativePoint(this.corticalMask);
      this.redPoint = representativePoint(spillRegion);
      if (this.part === "propagate") {
        this.displayMasks = this.cleanMasks.map((mask, index) => (index === 0 ? mask : null));
      } else {
        this.displayMasks = this.driftMasks.slice();
      }
      this.leverage = this.computeLeverage();
      this.announce((PART_COPY[this.part] || PART_COPY.propagate).ready);
      this.render();
    }

    async loadSourceImage(svgText) {
      const blobUrl = URL.createObjectURL(new Blob([svgText], { type: "image/svg+xml" }));
      try {
        this.sourceImage = new Image();
        await new Promise((resolve, reject) => {
          this.sourceImage.onload = resolve;
          this.sourceImage.onerror = () => reject(new Error("Unable to render slice SVG."));
          this.sourceImage.src = blobUrl;
        });
      } finally {
        URL.revokeObjectURL(blobUrl);
      }
    }

    prepareBaseMask(documentNode) {
      const pathNodes = filledPathNodes(documentNode);
      const rawMasks = pathNodes.map((node) => rasterizePath(node.getAttribute("d")));
      const visibleMasks = rawMasks.map((mask, index) => {
        let visible = new Uint8Array(mask);
        for (let later = index + 1; later < rawMasks.length; later += 1) visible = combineMasks(visible, rawMasks[later], "subtract");
        return visible;
      });
      const sdIndex = pathNodes.findIndex((node) => node.getAttribute("class") === "cls-5");
      const whiteMatterIndex = pathNodes.findIndex((node) => node.getAttribute("class") === "cls-1");
      if (sdIndex === -1 || whiteMatterIndex === -1) throw new Error("The slice SVG is missing required tissue regions.");
      this.corticalMask = new Uint8Array(visibleMasks[sdIndex]);
      this.whiteMatterMask = new Uint8Array(visibleMasks[whiteMatterIndex]);
    }

    async loadSequence() {
      const baseUrl = new URL(this.root.dataset.maskBase, window.location.href);
      const masks = await Promise.all(SEQUENCE_FILES.map(async (file) => {
        const image = new Image();
        await new Promise((resolve, reject) => {
          image.onload = resolve;
          image.onerror = () => reject(new Error(`Unable to load simulated mask frame ${file}.`));
          image.src = new URL(`${file}.png`, baseUrl).href;
        });
        return alignMaskToWhiteMatter(
          scaleMaskAroundCentroid(maskFromBinaryImage(image), SEQUENCE_MASK_SCALE),
          this.whiteMatterMask,
        );
      }));
      // Clean propagated run: the real exported masks constrained to cortical tissue.
      this.cleanMasks = masks.map((mask) => combineMasks(mask, this.corticalMask, "intersect"));
      // Drift run: from DRIFT_START the mask over-segments into white matter and grows.
      this.driftMasks = this.cleanMasks.map((mask, index) => {
        if (index < DRIFT_START) return new Uint8Array(mask);
        const spill = whiteMatterSlab(this.whiteMatterMask, index - DRIFT_START);
        return combineMasks(mask, spill, "union");
      });
      if (this.cleanMasks.some((mask) => countMask(mask) === 0)) throw new Error("A simulated mask frame does not overlap the tutorial slice.");
    }

    // Resolve a propagated frame given the current anchors: a correction anchor at or
    // after the drift onset (and at or before the frame) keeps that frame clean.
    resolveFrame(index) {
      if (index < DRIFT_START) return this.cleanMasks[index];
      for (const anchor of this.anchors) {
        if (anchor >= DRIFT_START && anchor <= index) return this.cleanMasks[index];
      }
      return this.driftMasks[index];
    }

    computeLeverage() {
      const masks = this.currentSequence();
      const raw = new Array(FRAME_COUNT).fill(0);
      for (let index = 1; index < FRAME_COUNT; index += 1) {
        if (!masks[index] || !masks[index - 1]) continue;
        const union = countMask(combineMasks(masks[index], masks[index - 1], "union")) || 1;
        raw[index] = symmetricDifference(masks[index], masks[index - 1]) / union;
      }
      // Absolute trouble floor: smooth frame-to-frame growth reads as settled (green);
      // only genuine drift climbs above it. Peak sets the red end of the scale.
      const floor = 0.12;
      const peak = Math.max(...raw);
      const suggested = peak > floor ? raw.indexOf(peak) : null;
      return { raw, floor, peak, suggested };
    }

    currentSequence() {
      if (this.part === "propagate") return this.displayMasks;
      if (this.part === "ghosts") return this.cleanMasks;
      return this.driftMasks;
    }

    buildInterface() {
      const prefix = "swell-propagation-demo";
      this.root.innerHTML = "";
      this.shell = document.createElement("div");
      this.shell.className = `${prefix}__shell`;
      this.stage = document.createElement("div");
      this.stage.className = `${prefix}__stage`;
      this.canvas = document.createElement("canvas");
      this.canvas.className = `${prefix}__canvas`;
      this.canvas.width = VIEW_WIDTH;
      this.canvas.height = VIEW_HEIGHT;
      this.canvas.tabIndex = 0;
      this.canvas.setAttribute("aria-label", (PART_COPY[this.part] || PART_COPY.propagate).aria);
      this.context = this.canvas.getContext("2d");
      this.status = document.createElement("p");
      this.status.className = `${prefix}__sr-status`;
      this.status.setAttribute("aria-live", "polite");
      this.stage.append(this.canvas, this.status);

      this.toolHelp = document.createElement("p");
      this.toolHelp.className = `${prefix}__tool-help`;
      this.toolHelp.setAttribute("aria-live", "polite");

      this.controls = document.createElement("div");
      this.controls.className = `${prefix}__controls`;
      this.buildControls();

      this.shell.append(this.stage, this.toolHelp, this.controls);
      this.root.appendChild(this.shell);
    }

    frameSlider() {
      const label = document.createElement("label");
      label.textContent = "Frame";
      const input = document.createElement("input");
      input.type = "range";
      input.min = "1";
      input.max = String(FRAME_COUNT);
      input.value = "1";
      input.setAttribute("aria-label", "Current frame");
      input.addEventListener("input", () => this.setFrame(Number(input.value) - 1));
      this.frameInput = input;
      this.frameValue = document.createElement("output");
      label.htmlFor = "";
      return [label, input, this.frameValue];
    }

    timelineCanvas() {
      const timeline = document.createElement("canvas");
      timeline.className = "swell-propagation-demo__timeline";
      timeline.width = VIEW_WIDTH;
      timeline.height = 44;
      timeline.setAttribute("role", "img");
      timeline.setAttribute("aria-label", "Propagation timeline");
      timeline.addEventListener("pointerdown", (event) => {
        const rect = timeline.getBoundingClientRect();
        const ratio = clamp((event.clientX - rect.left) / rect.width, 0, 0.9999);
        this.setFrame(Math.floor(ratio * FRAME_COUNT));
      });
      this.timeline = timeline;
      return timeline;
    }

    toggle(labelText, initial, onChange) {
      const wrap = document.createElement("label");
      wrap.className = "swell-propagation-demo__toggle";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = initial;
      input.addEventListener("change", () => onChange(input.checked));
      wrap.append(input, document.createTextNode(` ${labelText}`));
      return wrap;
    }

    commandButton(labelText, command, variant) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = labelText;
      if (variant) button.classList.add(`swell-propagation-demo__button--${variant}`);
      button.addEventListener("click", command);
      return button;
    }

    buildControls() {
      if (this.part === "propagate") {
        this.controls.append(...this.frameSlider());
        this.controls.append(this.timelineCanvas());
        this.runButton = this.commandButton("Run Propagation", () => this.runPropagation(), "run");
        this.anchorButton = this.commandButton("Add manual correction", () => this.addCorrectionAnchor());
        this.controls.append(this.runButton, this.anchorButton);
      } else if (this.part === "ghosts") {
        this.controls.append(...this.frameSlider());
        this.controls.append(this.toggle("Ghost Outlines", false, (on) => {
          this.ghostsEnabled = on;
          this.render();
        }));
        const rangeLabel = document.createElement("label");
        rangeLabel.textContent = "Ghost range";
        const rangeInput = document.createElement("input");
        rangeInput.type = "range";
        rangeInput.min = "1";
        rangeInput.max = "3";
        rangeInput.value = String(GHOST_RANGE_DEFAULT);
        rangeInput.setAttribute("aria-label", "Ghost range");
        this.rangeValue = document.createElement("output");
        rangeInput.addEventListener("input", () => {
          this.ghostRange = Number(rangeInput.value);
          this.render();
        });
        this.controls.append(rangeLabel, rangeInput, this.rangeValue);
      } else {
        this.controls.append(...this.frameSlider());
        this.controls.append(this.timelineCanvas());
        this.controls.append(this.toggle("Show Leverage Heatmap", true, (on) => {
          this.heatmapVisible = on;
          this.render();
        }));
        this.jumpButton = this.commandButton("Jump to Suggested Correction", () => this.jumpToSuggested());
        this.controls.append(this.jumpButton);
      }
    }

    setFrame(index) {
      this.frame = clamp(index, 0, FRAME_COUNT - 1);
      if (this.frameInput) this.frameInput.value = String(this.frame + 1);
      this.render();
    }

    runPropagation() {
      if (this.propagating) return;
      window.clearTimeout(this.animTimer);
      this.propagating = true;
      this.hasRun = true;
      this.runButton.disabled = true;
      // Propagation carries forward from the earliest anchor across the whole range;
      // later correction anchors only change which mask each downstream frame resolves to.
      const firstAnchor = Math.min(...this.anchors);
      this.displayMasks = this.cleanMasks.map((mask, index) => (index <= firstAnchor ? this.resolveFrame(index) : null));
      this.propagatedThrough = firstAnchor;
      this.setFrame(this.propagatedThrough);
      this.announce("Propagating the mask across the range...");
      const step = () => {
        if (!this.root.isConnected) return;
        this.propagatedThrough += 1;
        if (this.propagatedThrough < FRAME_COUNT) {
          this.displayMasks[this.propagatedThrough] = this.resolveFrame(this.propagatedThrough);
          this.setFrame(this.propagatedThrough);
          this.animTimer = window.setTimeout(step, 190);
          return;
        }
        this.propagatedThrough = FRAME_COUNT - 1;
        this.propagating = false;
        this.runButton.disabled = false;
        this.leverage = this.computeLeverage();
        this.finishPropagation();
      };
      this.animTimer = window.setTimeout(step, 260);
    }

    finishPropagation() {
      const corrected = Array.from(this.anchors).some((anchor) => anchor >= DRIFT_START);
      if (corrected) {
        const firstCorrection = Math.min(...this.correctionFrames);
        this.setFrame(Number.isFinite(firstCorrection) ? firstCorrection : FRAME_COUNT - 1);
        this.announce("Propagation now stays on cortical tissue across the range. The manual correction fixed the downstream frames.");
      } else {
        this.setFrame(DRIFT_START);
        this.runButton.textContent = "Re-run Propagation";
        this.announce(`Propagation drifted into white matter from frame ${DRIFT_START + 1}. Scrub to a drifted frame, add a manual correction, and re-run.`);
      }
      this.render();
    }

    addCorrectionAnchor() {
      if (!this.hasRun) {
        this.announce("Run propagation first, then place a manual correction on a frame that drifted.");
        return;
      }
      if (this.frame < DRIFT_START) {
        this.announce(`The drift starts at frame ${DRIFT_START + 1}. Place the manual correction on a drifted frame.`);
        return;
      }
      this.anchors.add(this.frame);
      this.correctionFrames.add(this.frame);
      this.announce(`Placed a manual correction on frame ${this.frame + 1}: a positive point on the cortical target (green) and a negative point in the white matter (red). Re-run propagation to refine the drifted frames.`);
      this.render();
    }

    jumpToSuggested() {
      const suggested = this.leverage ? this.leverage.suggested : null;
      if (suggested === null || suggested === undefined) {
        this.announce("No suggested correction frame available.");
        return;
      }
      this.setFrame(suggested);
      this.announce(`Jumped to suggested correction: frame ${suggested + 1}.`);
    }

    render() {
      this.context.clearRect(0, 0, VIEW_WIDTH, VIEW_HEIGHT);
      this.context.fillStyle = "#0f1318";
      this.context.fillRect(0, 0, VIEW_WIDTH, VIEW_HEIGHT);
      if (this.sourceImage) this.context.drawImage(this.sourceImage, 0, 0, VIEW_WIDTH, VIEW_HEIGHT);
      const sequence = this.currentSequence();
      const mask = sequence[this.frame];
      if (mask) {
        this.drawMask(mask);
        if (this.part === "ghosts" && this.ghostsEnabled) this.drawGhosts(sequence);
      } else {
        this.drawAwaitingLabel();
      }
      if (this.part === "propagate" && this.correctionFrames.has(this.frame)) {
        this.drawPromptDot(this.greenPoint, [55, 200, 113]);
        this.drawPromptDot(this.redPoint, [255, 92, 92]);
      }
      if (this.frameValue) this.frameValue.textContent = `${this.frame + 1} / ${FRAME_COUNT}`;
      if (this.rangeValue) this.rangeValue.textContent = String(this.ghostRange);
      if (this.timeline) this.drawTimeline();
      this.updateHelp();
    }

    drawMask(mask) {
      const overlay = document.createElement("canvas");
      overlay.width = MASK_WIDTH;
      overlay.height = MASK_HEIGHT;
      const context = overlay.getContext("2d");
      const image = context.createImageData(MASK_WIDTH, MASK_HEIGHT);
      for (let y = 0; y < MASK_HEIGHT; y += 1) {
        for (let x = 0; x < MASK_WIDTH; x += 1) {
          const index = y * MASK_WIDTH + x;
          if (!mask[index]) continue;
          const edge = x === 0 || y === 0 || x === MASK_WIDTH - 1 || y === MASK_HEIGHT - 1 || !mask[index - 1] || !mask[index + 1] || !mask[index - MASK_WIDTH] || !mask[index + MASK_WIDTH];
          const pixel = index * 4;
          image.data[pixel] = MASK_BLUE[0];
          image.data[pixel + 1] = MASK_BLUE[1];
          image.data[pixel + 2] = MASK_BLUE[2];
          image.data[pixel + 3] = edge ? 235 : 92;
        }
      }
      context.putImageData(image, 0, 0);
      this.context.save();
      this.context.imageSmoothingEnabled = false;
      this.context.drawImage(overlay, 0, 0, VIEW_WIDTH, VIEW_HEIGHT);
      this.context.restore();
    }

    drawContour(mask, color, alpha) {
      const overlay = document.createElement("canvas");
      overlay.width = MASK_WIDTH;
      overlay.height = MASK_HEIGHT;
      const context = overlay.getContext("2d");
      const image = context.createImageData(MASK_WIDTH, MASK_HEIGHT);
      for (let y = 0; y < MASK_HEIGHT; y += 1) {
        for (let x = 0; x < MASK_WIDTH; x += 1) {
          const index = y * MASK_WIDTH + x;
          if (!mask[index]) continue;
          const edge = x === 0 || y === 0 || x === MASK_WIDTH - 1 || y === MASK_HEIGHT - 1 || !mask[index - 1] || !mask[index + 1] || !mask[index - MASK_WIDTH] || !mask[index + MASK_WIDTH];
          if (!edge) continue;
          const pixel = index * 4;
          image.data[pixel] = color[0];
          image.data[pixel + 1] = color[1];
          image.data[pixel + 2] = color[2];
          image.data[pixel + 3] = alpha;
        }
      }
      context.putImageData(image, 0, 0);
      this.context.save();
      this.context.imageSmoothingEnabled = false;
      this.context.drawImage(overlay, 0, 0, VIEW_WIDTH, VIEW_HEIGHT);
      this.context.restore();
    }

    drawGhosts(sequence) {
      for (let distance = this.ghostRange; distance >= 1; distance -= 1) {
        const alpha = clamp(215 - (distance - 1) * 70, 60, 215);
        const pastIndex = this.frame - distance;
        const futureIndex = this.frame + distance;
        if (pastIndex >= 0 && sequence[pastIndex]) this.drawContour(sequence[pastIndex], GHOST_PAST, alpha);
        if (futureIndex < FRAME_COUNT && sequence[futureIndex]) this.drawContour(sequence[futureIndex], GHOST_FUTURE, alpha);
      }
    }

    drawPromptDot(point, color) {
      if (!point) return;
      const context = this.context;
      context.save();
      context.beginPath();
      context.arc(point.x, point.y, 12, 0, Math.PI * 2);
      context.fillStyle = `rgb(${color[0]}, ${color[1]}, ${color[2]})`;
      context.shadowColor = "rgba(0, 0, 0, 0.55)";
      context.shadowBlur = 4;
      context.fill();
      context.shadowBlur = 0;
      context.lineWidth = 3;
      context.strokeStyle = "#ffffff";
      context.stroke();
      context.restore();
    }

    drawAwaitingLabel() {
      this.context.save();
      this.context.fillStyle = "rgba(215, 221, 227, 0.75)";
      this.context.font = "500 26px system-ui, sans-serif";
      this.context.textAlign = "center";
      this.context.fillText("Not yet propagated", VIEW_WIDTH / 2, VIEW_HEIGHT / 2);
      this.context.restore();
    }

    drawTimeline() {
      const context = this.timeline.getContext("2d");
      const width = this.timeline.width;
      const height = this.timeline.height;
      const cellWidth = width / FRAME_COUNT;
      context.clearRect(0, 0, width, height);
      context.fillStyle = TIMELINE_TRACK;
      context.fillRect(0, 0, width, height);

      if (this.part === "leverage" && this.heatmapVisible) {
        const span = (this.leverage.peak - this.leverage.floor) || 1;
        for (let index = 0; index < FRAME_COUNT; index += 1) {
          const value = this.leverage.raw[index];
          const norm = value > this.leverage.floor ? clamp((value - this.leverage.floor) / span, 0, 1) : 0;
          context.fillStyle = leverageColor(norm);
          context.fillRect(index * cellWidth + 1, 22, cellWidth - 2, height - 26);
        }
      }

      if (this.part === "propagate") {
        const filled = this.displayMasks.filter((mask) => mask).length;
        context.fillStyle = ACCENT;
        context.fillRect(0, 8, (filled / FRAME_COUNT) * width, 16);
      }

      // Anchor markers (purple), matching the app's user/anchor frame band.
      context.fillStyle = ANCHOR_PURPLE;
      this.anchors.forEach((anchor) => {
        context.fillRect(anchor * cellWidth + cellWidth / 2 - 2, 2, 4, height - 4);
      });

      // Suggested-correction tick (white, low in the strip).
      if (this.part === "leverage" && this.leverage.suggested !== null && this.leverage.suggested !== undefined) {
        const center = this.leverage.suggested * cellWidth + cellWidth / 2;
        context.fillStyle = PLAYHEAD;
        context.fillRect(center - cellWidth / 2 + 2, height - 6, cellWidth - 4, 4);
      }

      // Current-frame playhead (white, full height) drawn last so it stays on top.
      context.fillStyle = PLAYHEAD;
      context.fillRect(this.frame * cellWidth + cellWidth / 2 - 1, 0, 2, height);
    }

    updateHelp() {
      if (!this.toolHelp) return;
      let message = "";
      if (this.part === "propagate") {
        message = "Propagation carries the anchor-frame mask across the event range. It does not run SAM 2.1; the sequence is a fixed simulation.";
      } else if (this.part === "ghosts") {
        message = "Ghost outlines show neighboring-frame contours: cyan for past frames, magenta for future frames, so you can follow how the mask shifts and grows across the sequence.";
      } else {
        message = "The heatmap grades each frame by how much the mask changes from the previous frame: red is high leverage (edit here), green is settled.";
      }
      this.toolHelp.textContent = message;
    }

    announce(message) {
      this.status.textContent = message;
    }
  }

  function mountPropagationDemos() {
    document.querySelectorAll("[data-swell-propagation-demo]").forEach((root) => {
      if (root.dataset.swellPropagationMounted === "true") return;
      root.dataset.swellPropagationMounted = "true";
      const demo = new PropagationDemo(root);
      root.swellPropagationDemo = demo;
      demo.initialize().catch((error) => {
        root.innerHTML = `<p class="swell-propagation-demo__fallback">Propagation demo unavailable: ${error.message}</p>`;
      });
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mountPropagationDemos, { once: true });
  else mountPropagationDemos();
  if (typeof document$ !== "undefined") document$.subscribe(mountPropagationDemos);
}());
